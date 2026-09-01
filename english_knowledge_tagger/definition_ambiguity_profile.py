"""Build a read-only ambiguity and yield profile for terminal knowledge labels."""

from __future__ import annotations

from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import re
from typing import Mapping, Sequence

from .knowledge_rulebook import KnowledgeRulebook, KnowledgeRulebookRecord
from .knowledge_taxonomy_migration import KnowledgeTaxonomyMigration


SCHEMA_VERSION = "definition-ambiguity-manifest-v1"
P0_SCHEMA_VERSION = "p0-terminal-label-policy-v1"
_BROAD_TRIGGER_PHRASES = (
    "所有涉及",
    "只要",
    "出现即",
    "都打",
    "均打",
    "无明确说明",
)
_NEGATIVE_BOUNDARY_PHRASES = (
    "不标",
    "不属于",
    "不能",
    "不得",
    "排除",
    "不适用",
    "不再打",
    "不用打",
)
_ROUTE_PHRASES = (
    "题型",
    "适用范围",
    "单选题",
    "填空题",
    "阅读",
    "听力",
    "写作",
    "翻译",
    "补全对话",
    "语法选择",
    "完形",
)
_EXAMPLE_PHRASES = ("例如", "如：", "正例", "示例", "例：")


def _required_path(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip().startswith("知识点->"):
        raise ValueError(f"{field} must be a canonical knowledge path")
    return value.strip()


def _canonicalize_rendered_label(
    value: object, *, migration: KnowledgeTaxonomyMigration
) -> str:
    if not isinstance(value, str) or not value.strip().startswith("知识点@"):
        raise ValueError("mentor verify_label must begin with 知识点@")
    rendered = value.strip()
    legacy_path = "知识点->" + rendered.removeprefix("知识点@").replace("@", "->")
    return migration.canonicalize(legacy_path).canonical_path


def load_p0_label_policy(path: Path) -> frozenset[str]:
    """Load the exact versioned P0 terminal label set."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"P0 label policy is not valid JSON: {path}") from error
    if not isinstance(payload, Mapping) or payload.get("schema_version") != P0_SCHEMA_VERSION:
        raise ValueError(f"P0 label policy schema_version must be {P0_SCHEMA_VERSION!r}")
    raw_labels = payload.get("labels")
    if not isinstance(raw_labels, list):
        raise ValueError("P0 label policy labels must be a list")
    labels = tuple(_required_path(item, field="P0 label") for item in raw_labels)
    if len(labels) != len(set(labels)):
        raise ValueError("P0 label policy contains duplicate labels")
    return frozenset(labels)


def _rendered_candidates(value: object) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ()
    return tuple(
        item.strip()
        for item in re.split(r"[;；\n]+", value)
        if item.strip().startswith("知识点@")
    )


def summarize_mentor_results(
    path: Path,
    *,
    migration: KnowledgeTaxonomyMigration,
    rulebook: KnowledgeRulebook,
    diagnostics: dict[str, object] | None = None,
) -> Mapping[str, Mapping[str, object]]:
    """Aggregate knowledge-label mentor yield and quarantine other scopes."""
    counts: defaultdict[str, Counter[str]] = defaultdict(Counter)
    confusions: defaultdict[str, Counter[str]] = defaultdict(Counter)
    seen: set[tuple[str, str]] = set()
    unknown_labels: Counter[tuple[str, str]] = Counter()
    unknown_first_lines: dict[tuple[str, str], int] = {}
    records_seen = 0
    knowledge_records = 0
    out_of_scope_records = 0
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            records_seen += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"mentor results line {line_number}: invalid JSON") from error
            if not isinstance(row, Mapping):
                raise ValueError(f"mentor results line {line_number}: row must be an object")
            raw_verify_label = row.get("verify_label")
            if not isinstance(raw_verify_label, str) or not raw_verify_label.strip():
                raise ValueError(
                    f"mentor results line {line_number}: verify_label must be non-empty"
                )
            raw_verify_label = raw_verify_label.strip()
            if not raw_verify_label.startswith("知识点@"):
                out_of_scope_records += 1
                continue
            knowledge_records += 1
            canonical = _canonicalize_rendered_label(
                raw_verify_label, migration=migration
            )
            if canonical not in rulebook.records:
                key = (raw_verify_label, canonical)
                unknown_labels[key] += 1
                unknown_first_lines.setdefault(key, line_number)
                continue
            question_id = row.get("question_id")
            if not isinstance(question_id, str) or not question_id.strip():
                raise ValueError(
                    f"mentor results line {line_number}: question_id must be non-empty"
                )
            identity = (canonical, question_id.strip())
            if identity in seen:
                raise ValueError(
                    f"mentor results line {line_number}: duplicate label/question_id pair"
                )
            seen.add(identity)
            match = row.get("llm_match")
            if not isinstance(match, bool):
                raise ValueError(
                    f"mentor results line {line_number}: llm_match must be boolean"
                )
            counts[canonical]["sample_size"] += 1
            counts[canonical]["matches" if match else "mismatches"] += 1
            for rendered in _rendered_candidates(row.get("llm_should_be")):
                candidate = _canonicalize_rendered_label(rendered, migration=migration)
                record = rulebook.records.get(candidate)
                if candidate != canonical and record is not None and record.status == "active":
                    confusions[canonical][candidate] += 1
    if diagnostics is not None:
        diagnostics.clear()
        diagnostics.update(
            {
                "records_seen": records_seen,
                "knowledge_records": knowledge_records,
                "out_of_scope_records": out_of_scope_records,
                "unknown_knowledge_records": sum(unknown_labels.values()),
                "unknown_knowledge_labels": [
                    {
                        "verify_label": raw,
                        "canonical_after_migration": canonical,
                        "count": count,
                        "first_line": unknown_first_lines[(raw, canonical)],
                    }
                    for (raw, canonical), count in unknown_labels.most_common()
                ],
            }
        )
    result: dict[str, Mapping[str, object]] = {}
    for canonical, counter in counts.items():
        sample_size = counter["sample_size"]
        result[canonical] = {
            "matches": counter["matches"],
            "mismatches": counter["mismatches"],
            "sample_size": sample_size,
            "match_rate": counter["matches"] / sample_size,
            "confusion_neighbors": tuple(
                {"canonical_label": label, "count": count}
                for label, count in sorted(
                    confusions[canonical].items(), key=lambda item: (-item[1], item[0])
                )
            ),
        }
    return result


def _canonical_evidence_label(
    value: object,
    *,
    migration: KnowledgeTaxonomyMigration,
    rulebook: KnowledgeRulebook,
) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if normalized.startswith("知识点@"):
        normalized = "知识点->" + normalized.removeprefix("知识点@").replace("@", "->")
    if not normalized.startswith("知识点->"):
        return None
    canonical = migration.canonicalize(normalized).canonical_path
    record = rulebook.records.get(canonical)
    return canonical if record is not None and record.status == "active" else None


def summarize_confusion_evidence(
    paths: Sequence[Path],
    *,
    migration: KnowledgeTaxonomyMigration,
    rulebook: KnowledgeRulebook,
) -> Mapping[str, Mapping[str, int]]:
    """Read flat replace and tree candidate evidence into confusion counts."""
    counts: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for path in paths:
        with path.open("r", encoding="utf-8") as source:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(f"{path} line {line_number}: invalid JSON") from error
                if not isinstance(row, Mapping):
                    raise ValueError(f"{path} line {line_number}: row must be an object")
                historical = next(
                    (
                        _canonical_evidence_label(
                            row.get(field), migration=migration, rulebook=rulebook
                        )
                        for field in ("canonical_label", "historical_label", "target_label")
                        if row.get(field) is not None
                    ),
                    None,
                )
                validation = row.get("validation")
                best_label = (
                    validation.get("best_label")
                    if isinstance(validation, Mapping)
                    and validation.get("verdict") == "replace"
                    else None
                )
                candidate = _canonical_evidence_label(
                    row.get("candidate_label") or best_label,
                    migration=migration,
                    rulebook=rulebook,
                )
                if historical is not None and candidate is not None and historical != candidate:
                    counts[historical][candidate] += 1
    return {
        historical: dict(sorted(neighbors.items()))
        for historical, neighbors in sorted(counts.items())
    }


def _terms(value: str) -> frozenset[str]:
    ascii_words = re.findall(r"[a-z0-9]+", value.lower())
    han = "".join(re.findall(r"[\u4e00-\u9fff]", value))
    bigrams = [han[index : index + 2] for index in range(max(0, len(han) - 1))]
    return frozenset((*ascii_words, *bigrams))


def _definition_overlap(record: KnowledgeRulebookRecord) -> float | None:
    left = _terms(record.marking_interpretation)
    right = _terms(record.compressed_definition)
    if not left or not right:
        return None
    return len(left & right) / len(left | right)


def _audit_families(path: str) -> tuple[str, ...]:
    families: list[str] = []
    if path.startswith("知识点->词汇->构词法"):
        families.append("word_formation_boundary")
    if (
        path.startswith("知识点->词法->动词时态")
        or path.startswith("知识点->词法->动词->实义动词")
        or path.startswith("知识点->句法->句子成分")
        or path.startswith("知识点->句法->简单句")
        or path.startswith("知识点->句法->并列句")
    ):
        families.append("grammar_structure_boundary")
    if path.startswith("知识点->语用->时间"):
        families.append("pragmatic_time_overlap")
    if path.startswith("知识点->语用->社会交往") or path.startswith("知识点->语用->情感"):
        families.append("pragmatic_social_overlap")
    if path.startswith("知识点->语篇主题"):
        families.append("discourse_theme_granularity")
    return tuple(families)


def _flags(record: KnowledgeRulebookRecord) -> dict[str, bool]:
    source_text = f"{record.marking_interpretation}\n{record.compressed_definition}"
    active_text = record.alternative_definition
    overlap = _definition_overlap(record)
    final_segment = record.path.rsplit("->", 1)[-1]
    return {
        "known_definition_override": record.definition_override is not None,
        "broad_trigger_wording": any(item in source_text for item in _BROAD_TRIGGER_PHRASES),
        "missing_negative_boundary": not any(
            item in active_text for item in _NEGATIVE_BOUNDARY_PHRASES
        ),
        "missing_standard_route": not any(item in source_text for item in _ROUTE_PHRASES),
        "missing_examples": not any(item in source_text for item in _EXAMPLE_PHRASES),
        "low_original_compressed_overlap": overlap is not None and overlap < 0.15,
        "fallback_or_comprehensive": bool(
            re.search(r"其他|其它|综合", final_segment)
        ),
    }


def _average_ranks(values: Sequence[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and ordered[end][1] == ordered[start][1]:
            end += 1
        rank = (start + 1 + end) / 2
        for index, _ in ordered[start:end]:
            ranks[index] = rank
        start = end
    return ranks


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum(
        (a - left_mean) * (b - right_mean) for a, b in zip(left, right)
    )
    left_scale = math.sqrt(sum((item - left_mean) ** 2 for item in left))
    right_scale = math.sqrt(sum((item - right_mean) ** 2 for item in right))
    if not left_scale or not right_scale:
        return None
    return numerator / (left_scale * right_scale)


def _fisher_two_sided(a: int, b: int, c: int, d: int) -> float:
    row_one = a + b
    row_two = c + d
    column_one = a + c
    total = row_one + row_two

    def probability(value: int) -> float:
        return (
            math.comb(column_one, value)
            * math.comb(total - column_one, row_one - value)
            / math.comb(total, row_one)
        )

    minimum = max(0, row_one - (total - column_one))
    maximum = min(row_one, column_one)
    observed = probability(a)
    return min(
        1.0,
        sum(
            probability(value)
            for value in range(minimum, maximum + 1)
            if probability(value) <= observed + 1e-15
        ),
    )


def _statistics(records: Sequence[Mapping[str, object]]) -> dict[str, object]:
    def high_risk(row: Mapping[str, object]) -> bool:
        flags = row["flags"]
        assert isinstance(flags, Mapping)
        return bool(row.get("audit_families")) or any(
            bool(flags[name])
            for name in (
                "known_definition_override",
                "broad_trigger_wording",
                "low_original_compressed_overlap",
                "fallback_or_comprehensive",
            )
        )

    a = sum(bool(row["is_p0"]) and high_risk(row) for row in records)
    b = sum(bool(row["is_p0"]) and not high_risk(row) for row in records)
    c = sum(not bool(row["is_p0"]) and high_risk(row) for row in records)
    d = sum(not bool(row["is_p0"]) and not high_risk(row) for row in records)
    odds_ratio: float | str | None
    if b * c:
        odds_ratio = (a * d) / (b * c)
    elif a * d:
        odds_ratio = "inf"
    else:
        odds_ratio = None

    paired = []
    for row in records:
        mentor_yield = row["mentor_yield"]
        assert isinstance(mentor_yield, Mapping)
        match_rate = mentor_yield.get("match_rate")
        if isinstance(match_rate, (int, float)) and mentor_yield.get("sample_size", 0) >= 100:
            paired.append((float(row["ambiguity_score"]), float(match_rate)))
    correlation = (
        _pearson(
            _average_ranks([item[0] for item in paired]),
            _average_ranks([item[1] for item in paired]),
        )
        if paired
        else None
    )
    return {
        "fisher_exact": {
            "table": {
                "p0_high_risk": a,
                "p0_not_high_risk": b,
                "non_p0_high_risk": c,
                "non_p0_not_high_risk": d,
            },
            "odds_ratio": odds_ratio,
            "two_sided_p_value": _fisher_two_sided(a, b, c, d),
        },
        "spearman_ambiguity_score_vs_match_rate": {
            "labels": len(paired),
            "rho": correlation,
            "minimum_sample_size": 100,
        },
    }


def build_definition_ambiguity_manifest(
    rulebook: KnowledgeRulebook,
    *,
    yields: Mapping[str, Mapping[str, object]],
    p0_labels: frozenset[str],
    additional_confusions: Mapping[str, Mapping[str, int]] | None = None,
    mentor_result_diagnostics: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build the complete non-releasing ambiguity profile."""
    missing_p0 = sorted(p0_labels - set(rulebook.records))
    if missing_p0:
        raise ValueError(f"P0 label is absent from teacher rulebook: {missing_p0[0]}")
    unknown_yields = sorted(set(yields) - set(rulebook.records))
    if unknown_yields:
        raise ValueError(f"mentor yield label is absent from teacher rulebook: {unknown_yields[0]}")

    records: list[dict[str, object]] = []
    for path, record in sorted(rulebook.records.items()):
        flags = _flags(record)
        mentor_yield = yields.get(path)
        yield_payload = (
            {
                "matches": int(mentor_yield["matches"]),
                "mismatches": int(mentor_yield["mismatches"]),
                "sample_size": int(mentor_yield["sample_size"]),
                "match_rate": float(mentor_yield["match_rate"]),
            }
            if mentor_yield is not None
            else {"matches": 0, "mismatches": 0, "sample_size": 0, "match_rate": None}
        )
        confusion_counter: Counter[str] = Counter()
        if mentor_yield is not None:
            for item in mentor_yield.get("confusion_neighbors", ()):
                if isinstance(item, Mapping):
                    label = item.get("canonical_label")
                    count = item.get("count")
                    if isinstance(label, str) and isinstance(count, int):
                        confusion_counter[label] += count
        for label, count in (additional_confusions or {}).get(path, {}).items():
            if label not in rulebook.records or rulebook.records[label].status != "active":
                raise ValueError(f"additional confusion label is not active: {label}")
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise ValueError("additional confusion counts must be non-negative integers")
            if label != path:
                confusion_counter[label] += count
        confusion_neighbors = [
            {"canonical_label": label, "count": count}
            for label, count in sorted(
                confusion_counter.items(), key=lambda item: (-item[1], item[0])
            )
        ]
        families = _audit_families(path)
        records.append(
            {
                "canonical_label": path,
                "status": record.status,
                "root_node": path.split("->")[1],
                "is_p0": path in p0_labels,
                "mentor_yield": yield_payload,
                "flags": flags,
                "ambiguity_score": sum(flags.values()),
                "audit_families": list(families),
                "direct_active_leaf_siblings": len(
                    rulebook.direct_active_leaf_siblings(path)
                ),
                "definition_lengths": {
                    "marking_interpretation": len(record.marking_interpretation),
                    "compressed_definition": len(record.compressed_definition),
                    "active_definition": len(record.alternative_definition),
                },
                "original_compressed_overlap": _definition_overlap(record),
                "confusion_neighbors": confusion_neighbors,
            }
        )

    stats = _statistics(records)
    p0_records = [row for row in records if row["is_p0"]]
    summary = {
        "knowledge_labels": len(records),
        "active_labels": sum(row["status"] == "active" for row in records),
        "deprecated_labels": sum(row["status"] == "deprecated" for row in records),
        "mentor_yield_labels": sum(
            row["mentor_yield"]["sample_size"] > 0 for row in records
        ),
        "p0_labels": len(p0_records),
        "p0_direct_override_labels": sum(
            row["flags"]["known_definition_override"] for row in p0_records
        ),
        "p0_audit_family_labels": sum(bool(row["audit_families"]) for row in p0_records),
        "ambiguity_concentration_definition": "audit_family_or_explicit_high_risk_flag",
        **stats,
    }
    if mentor_result_diagnostics is not None:
        summary["mentor_result_diagnostics"] = dict(mentor_result_diagnostics)
    return {
        "schema_version": SCHEMA_VERSION,
        "purpose": "non_releasing_definition_ambiguity_experiment",
        "labels": records,
        "summary": summary,
    }
