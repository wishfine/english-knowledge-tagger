"""Deterministic offline packets for low-quality label remediation experiments."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping


CONVERSION_LABEL = "知识点@词汇@构词法@转化法"
MIXED_POS_LEGAL_ROUTE = ("parent", "单选题", "选择题")
_TYPE_METADATA = re.compile(r"(?m)^题型(结构|名称)为：([^\r\n]*)")


@dataclass(frozen=True)
class ConversionTreeT1Quotas:
    direct_match: int = 15
    derived: int = 10
    word_form: int = 10
    vocabulary: int = 5
    fixed_phrase: int = 5
    grammar: int = 5
    translation: int = 4
    spelling: int = 3
    parent_fill: int = 3

    @property
    def total(self) -> int:
        return sum(
            (
                self.direct_match,
                self.derived,
                self.word_form,
                self.vocabulary,
                self.fixed_phrase,
                self.grammar,
                self.translation,
                self.spelling,
                self.parent_fill,
            )
        )


DEFAULT_CONVERSION_T1_QUOTAS = ConversionTreeT1Quotas()
DEFAULT_CONVERSION_BOUNDARIES: Mapping[str, tuple[str, ...]] = {
    "known_same_form": (
        "3479221260516872215",  # wonder v./n.
        "3251687827408007179",  # matter v./n.
        "3373617985462779904",  # graduate v./n.
        "3251687827408007188",  # cover v./n.
        "3251687827408007176",  # text n./v.
        "2959157925843865600",  # tie n./v.
        "2728710837203480579",  # like 的多词性边界
        "3479221260516872198",  # fit adj./v.
        "3479221260516872195",  # gold adj./n.
    ),
    "known_derived_or_spelling": (
        "2992442148149280780",  # warmth -> warm
        "2737410379129155585",  # Britain -> British
        "2825476033785401356",  # weigh -> weight
    ),
}

_CONVERSION_STRATA = (
    ("derived", "知识点@词汇@构词法@派生法"),
    ("word_form", "知识点@词汇@词汇（音/形/义）"),
    ("vocabulary", "知识点@词汇@词汇辨析"),
    ("fixed_phrase", "知识点@词汇@固定搭配/句型"),
)
_HOW_LABEL = "知识点@语法句法@句子种类@疑问句@特殊疑问句@how类特殊疑问句"
_FIXED_LABEL = "知识点@词汇@固定搭配/句型"
_SAME_POS_LABEL = "知识点@词汇@词汇辨析@词汇辨析（同词性）"
_CONNECTOR_LABEL = "知识点@词汇@词汇辨析@词汇辨析（连词）"
_MIXED_FALSE_STRATA = (
    ("false_how", _HOW_LABEL),
    ("false_fixed_phrase", _FIXED_LABEL),
    ("false_same_pos", _SAME_POS_LABEL),
    ("false_connector", _CONNECTOR_LABEL),
)


def _nonempty(value: object, *, field: str, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: {field} must be a non-empty string")
    return value.strip()


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _rank(seed: str, identifier: str) -> str:
    return hashlib.sha256(f"{seed}\0{identifier}".encode("utf-8")).hexdigest()


def _read_jsonl(path: Path, *, source_name: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{source_name} line {line_number}: invalid JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"{source_name} line {line_number}: JSONL row must be an object")
            rows.append(row)
    return rows


def _require_distinct_outputs(*paths: Path) -> None:
    if len(set(paths)) != len(paths):
        raise ValueError("all output paths must differ")
    existing = [str(path) for path in paths if path.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite existing output: {existing[0]}")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _task_id(row: Mapping[str, object], *, source: str) -> str:
    return _nonempty(row.get("task_id"), field="task_id", source=source)


def _question_id(row: Mapping[str, object]) -> str | None:
    return _optional_text(row.get("question_id"))


def _task_trigger(row: Mapping[str, object], *, source: str) -> str:
    kinds = row.get("trigger_kinds")
    if not isinstance(kinds, list) or len(kinds) != 1 or not isinstance(kinds[0], str):
        raise ValueError(f"{source}: trigger_kinds must contain exactly one string")
    if kinds[0] not in {"direct_match_recheck", "direct_mismatch"}:
        raise ValueError(f"{source}: unsupported direct trigger {kinds[0]!r}")
    return kinds[0]


def _task_route(row: Mapping[str, object], *, source: str) -> tuple[str, str, str]:
    payload = row.get("route_key")
    if not isinstance(payload, Mapping):
        raise ValueError(f"{source}: route_key must be an object")
    return (
        _nonempty(payload.get("scope"), field="route_key.scope", source=source),
        _nonempty(
            payload.get("declared_type_structure"),
            field="route_key.declared_type_structure",
            source=source,
        ),
        _nonempty(payload.get("declared_type_name"), field="route_key.declared_type_name", source=source),
    )


def _select(
    pool: list[dict[str, object]],
    *,
    count: int,
    seed: str,
    selected_ids: set[str],
    label: str,
) -> list[dict[str, object]]:
    available = [row for row in pool if _task_id(row, source=label) not in selected_ids]
    ranked = sorted(available, key=lambda row: _rank(seed, _task_id(row, source=label)))
    if len(ranked) < count:
        raise ValueError(f"{label}: requires {count} rows but only {len(ranked)} are available")
    selected = ranked[:count]
    selected_ids.update(_task_id(row, source=label) for row in selected)
    return selected


def build_conversion_tree_t1_packet(
    tasks_path: Path,
    *,
    output_path: Path,
    audit_index_path: Path,
    seed: str,
    quotas: ConversionTreeT1Quotas = DEFAULT_CONVERSION_T1_QUOTAS,
    boundary_question_ids: Mapping[str, tuple[str, ...]] = DEFAULT_CONVERSION_BOUNDARIES,
) -> dict[str, object]:
    """Create a 60-task, stratified DS input packet for conversion tree T1."""
    if not isinstance(seed, str) or not seed.strip():
        raise ValueError("seed must be non-empty")
    if any(value <= 0 for value in vars(quotas).values()):
        raise ValueError("all conversion T1 quotas must be positive")
    _require_distinct_outputs(output_path, audit_index_path)
    rows = _read_jsonl(tasks_path, source_name="conversion tree task")
    by_task_id: dict[str, dict[str, object]] = {}
    by_question_id: dict[str, dict[str, object]] = {}
    for position, row in enumerate(rows, 1):
        source = f"conversion tree task {position}"
        task_id = _task_id(row, source=source)
        if task_id in by_task_id:
            raise ValueError(f"{source}: duplicate task_id {task_id!r}")
        _task_trigger(row, source=source)
        _task_route(row, source=source)
        by_task_id[task_id] = row
        question_id = _question_id(row)
        if question_id is not None:
            if question_id in by_question_id:
                raise ValueError(f"{source}: duplicate question_id {question_id!r}")
            by_question_id[question_id] = row

    selected: list[tuple[str, dict[str, object]]] = []
    selected_ids: set[str] = set()
    for stratum in ("known_same_form", "known_derived_or_spelling"):
        for question_id in boundary_question_ids.get(stratum, ()):
            row = by_question_id.get(question_id)
            if row is None:
                raise ValueError(f"{stratum}: boundary question_id is absent: {question_id}")
            if _task_trigger(row, source=stratum) != "direct_match_recheck":
                raise ValueError(f"{stratum}: boundary question_id is not a direct true recheck: {question_id}")
            task_id = _task_id(row, source=stratum)
            if task_id not in selected_ids:
                selected.append((stratum, row))
                selected_ids.add(task_id)
    if len(selected) > quotas.direct_match:
        raise ValueError("direct_match quota is smaller than required known conversion boundaries")
    for row in _select(
        [row for row in rows if _task_trigger(row, source="direct true") == "direct_match_recheck"],
        count=quotas.direct_match - len(selected),
        seed=seed,
        selected_ids=selected_ids,
        label="direct_match_fallback",
    ):
        selected.append(("direct_match_fallback", row))

    direct_false = [row for row in rows if _task_trigger(row, source="direct false") == "direct_mismatch"]
    quota_by_stratum = {
        "derived": quotas.derived,
        "word_form": quotas.word_form,
        "vocabulary": quotas.vocabulary,
        "fixed_phrase": quotas.fixed_phrase,
    }
    for stratum, prefix in _CONVERSION_STRATA:
        for row in _select(
            [row for row in direct_false if (_optional_text(row.get("direct_should_be")) or "").startswith(prefix)],
            count=quota_by_stratum[stratum],
            seed=seed,
            selected_ids=selected_ids,
            label=stratum,
        ):
            selected.append((stratum, row))
    for row in _select(
        [
            row
            for row in direct_false
            if (_optional_text(row.get("direct_should_be")) or "").startswith("知识点@语法")
        ],
        count=quotas.grammar,
        seed=seed,
        selected_ids=selected_ids,
        label="grammar",
    ):
        selected.append(("grammar", row))

    route_quotas = (
        ("route_translation", ("child", "复合题", "翻译题"), quotas.translation),
        ("route_spelling", ("child", "复合题", "单词拼写"), quotas.spelling),
        ("route_parent_fill", ("parent", "填空题"), quotas.parent_fill),
    )
    for stratum, route_prefix, count in route_quotas:
        for row in _select(
            [row for row in direct_false if _task_route(row, source=stratum)[: len(route_prefix)] == route_prefix],
            count=count,
            seed=seed,
            selected_ids=selected_ids,
            label=stratum,
        ):
            selected.append((stratum, row))

    if len(selected) != quotas.total:
        raise AssertionError("conversion T1 selection total does not match quotas")
    ordered = sorted(selected, key=lambda item: _rank(seed, _task_id(item[1], source="selected task")))
    task_rows = [dict(row) for _, row in ordered]
    audit_rows = [
        {
            "schema_version": "low-quality-label-experiment-index-v1",
            "experiment": "conversion-tree-t1",
            "task_id": _task_id(row, source="selected task"),
            "question_id": _question_id(row),
            "route_key": row.get("route_key"),
            "trigger_kinds": row.get("trigger_kinds"),
            "direct_should_be": row.get("direct_should_be"),
            "selection_stratum": stratum,
        }
        for stratum, row in ordered
    ]
    _write_jsonl(output_path, task_rows)
    _write_jsonl(audit_index_path, audit_rows)
    return {
        "schema_version": "conversion-tree-t1-packet-report-v1",
        "tasks_path": str(tasks_path),
        "output_path": str(output_path),
        "audit_index_path": str(audit_index_path),
        "seed": seed,
        "requested_records": quotas.total,
        "selected_records": len(task_rows),
        "selected_by_stratum": dict(Counter(stratum for stratum, _ in ordered)),
    }


def _mentor_route(row: Mapping[str, object], *, source: str) -> tuple[str, str, str]:
    input_text = _nonempty(row.get("input"), field="input", source=source)
    metadata = {match.group(1): match.group(2).strip() for match in _TYPE_METADATA.finditer(input_text)}
    scope = "child" if row.get("is_sub_question") is True else "parent" if row.get("is_sub_question") is False else "unknown"
    return (scope, metadata.get("结构") or "缺失", metadata.get("名称") or "缺失")


def _canonical_path(rendered_label: str) -> str:
    return "知识点->" + rendered_label.removeprefix("知识点@").replace("@", "->")


def _mixed_review_id(source_line: int, question_id: str | None) -> str:
    return f"mixed-pos-m1:{question_id or 'line'}:{source_line}"


def build_mixed_pos_m1_review_packet(
    verification_path: Path,
    *,
    verify_label: str,
    teacher_definition: str,
    blind_output_path: Path,
    audit_index_path: Path,
    seed: str,
) -> dict[str, object]:
    """Create a blind M1 packet from legal-route mixed-POS direct verdicts."""
    target = _nonempty(verify_label, field="verify_label", source="mixed POS M1")
    definition = _nonempty(teacher_definition, field="teacher_definition", source="mixed POS M1")
    if not isinstance(seed, str) or not seed.strip():
        raise ValueError("seed must be non-empty")
    _require_distinct_outputs(blind_output_path, audit_index_path)
    rows = _read_jsonl(verification_path, source_name="mixed POS mentor verification")
    legal_true: list[tuple[int, dict[str, object]]] = []
    false_by_suggestion: dict[str, list[tuple[int, dict[str, object]]]] = {
        stratum: [] for stratum, _ in _MIXED_FALSE_STRATA
    }
    excluded_route_records = 0
    for source_line, row in enumerate(rows, 1):
        source = f"mixed POS mentor verification {source_line}"
        if _nonempty(row.get("verify_label"), field="verify_label", source=source) != target:
            raise ValueError(f"{source}: verify_label differs from requested label")
        direct_match = row.get("llm_match")
        if not isinstance(direct_match, bool):
            raise ValueError(f"{source}: llm_match must be boolean")
        route = _mentor_route(row, source=source)
        if route != MIXED_POS_LEGAL_ROUTE:
            excluded_route_records += 1
            continue
        if direct_match:
            legal_true.append((source_line, row))
            continue
        suggestion = _optional_text(row.get("llm_should_be")) or ""
        for stratum, expected in _MIXED_FALSE_STRATA:
            if suggestion == expected:
                false_by_suggestion[stratum].append((source_line, row))
                break

    selected: list[tuple[str, int, dict[str, object]]] = [
        ("legal_true", source_line, row) for source_line, row in legal_true
    ]
    for stratum, _ in _MIXED_FALSE_STRATA:
        pool = false_by_suggestion[stratum]
        if len(pool) < 12:
            raise ValueError(f"{stratum}: requires 12 legal-route false rows but only {len(pool)} are available")
        ranked = sorted(
            pool,
            key=lambda item: _rank(seed, _mixed_review_id(item[0], _question_id(item[1]))),
        )
        selected.extend((stratum, source_line, row) for source_line, row in ranked[:12])

    ordered = sorted(
        selected,
        key=lambda item: _rank(seed, _mixed_review_id(item[1], _question_id(item[2]))),
    )
    blind_rows: list[dict[str, object]] = []
    audit_rows: list[dict[str, object]] = []
    for stratum, source_line, row in ordered:
        question_id = _question_id(row)
        review_id = _mixed_review_id(source_line, question_id)
        route = _mentor_route(row, source=review_id)
        blind_rows.append(
            {
                "schema_version": "low-quality-label-blind-review-v1",
                "review_id": review_id,
                "review_target_label": _canonical_path(target),
                "teacher_definition": definition,
                "source_line": source_line,
                "question_id": question_id,
                "parent_id": _optional_text(row.get("parent_id")),
                "route_key": {
                    "scope": route[0],
                    "declared_type_structure": route[1],
                    "declared_type_name": route[2],
                },
                "question_context": _nonempty(row.get("input"), field="input", source=review_id),
            }
        )
        audit_rows.append(
            {
                "schema_version": "low-quality-label-experiment-index-v1",
                "experiment": "mixed-pos-m1",
                "review_id": review_id,
                "source_line": source_line,
                "question_id": question_id,
                "selection_stratum": stratum,
                "direct_match": row.get("llm_match"),
                "direct_should_be": _optional_text(row.get("llm_should_be")),
                "direct_reason": _optional_text(row.get("llm_reason")),
                "source_output_all": _optional_text(row.get("output_all")),
            }
        )
    _write_jsonl(blind_output_path, blind_rows)
    _write_jsonl(audit_index_path, audit_rows)
    return {
        "schema_version": "mixed-pos-m1-review-packet-report-v1",
        "verification_path": str(verification_path),
        "verify_label": target,
        "blind_output_path": str(blind_output_path),
        "audit_index_path": str(audit_index_path),
        "seed": seed,
        "legal_true_records": len(legal_true),
        "selected_false_records": len(ordered) - len(legal_true),
        "selected_records": len(ordered),
        "excluded_route_records": excluded_route_records,
        "selected_by_stratum": dict(Counter(stratum for stratum, _, _ in ordered)),
    }
