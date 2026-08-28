"""Build blinded, deterministic review packets for low-match P0 labels."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from .mentor_direct_rollout import clean_mentor_v1_input
from .knowledge_taxonomy_migration import KnowledgeTaxonomyMigration


BLIND_SCHEMA_VERSION = "p0-direct-diagnosis-blind-review-v1"
AUDIT_SCHEMA_VERSION = "p0-direct-diagnosis-audit-v1"
_TYPE_METADATA = re.compile(r"(?m)^题型(结构|名称)为：([^\r\n]*)")


def _string(value: object, *, field: str, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: {field} must be a non-empty string")
    return value.strip()


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _legacy_path(rendered_label: str) -> str:
    return "知识点->" + rendered_label.removeprefix("知识点@").replace("@", "->")


def _rank(seed: str, identifier: str) -> str:
    return hashlib.sha256(f"{seed}\0{identifier}".encode("utf-8")).hexdigest()


def _route_key(input_text: str, is_sub_question: object) -> dict[str, str]:
    metadata = {match.group(1): match.group(2).strip() for match in _TYPE_METADATA.finditer(input_text)}
    return {
        "scope": "child" if is_sub_question is True else "parent" if is_sub_question is False else "unknown",
        "declared_type_structure": metadata.get("结构") or "缺失",
        "declared_type_name": metadata.get("名称") or "缺失",
    }


def _route_name(route: Mapping[str, str]) -> str:
    return " × ".join(
        (
            route["scope"],
            route["declared_type_structure"],
            route["declared_type_name"],
        )
    )


def _suggestion_family(suggestion: str) -> str:
    suggestion = suggestion.split(";", 1)[0].strip()
    if not suggestion.startswith("知识点@"):
        return "non_knowledge"
    return "@".join(suggestion.split("@")[:3])


def _review_id(*, label: str, question_id: str | None, source_line: int, review_set: str) -> str:
    label_digest = hashlib.sha256(label.encode("utf-8")).hexdigest()[:12]
    return f"p0-diagnosis:{label_digest}:{question_id or f'line-{source_line}'}:{review_set}"


def _require_fresh_paths(*paths: Path) -> None:
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


def _select_false_rows(
    rows: list[dict[str, object]],
    *,
    seed: str,
    sample_size: int,
    boundary_question_ids: tuple[str, ...],
) -> list[tuple[str, dict[str, object]]]:
    """Round-robin route × suggestion groups for boundary discovery, not estimation."""
    if sample_size <= 0:
        if boundary_question_ids:
            raise ValueError("false_sample_size must cover every false boundary question")
        return []
    if len(set(boundary_question_ids)) != len(boundary_question_ids):
        raise ValueError("false_boundary_question_ids must not contain duplicates")
    if len(boundary_question_ids) > sample_size:
        raise ValueError("false_sample_size must cover every false boundary question")
    by_question_id = {
        question_id: row
        for row in rows
        if isinstance(question_id := row.get("question_id"), str) and question_id
    }
    missing_boundaries = sorted(set(boundary_question_ids) - set(by_question_id))
    if missing_boundaries:
        raise ValueError(f"false boundary question_id is absent or ineligible: {missing_boundaries[0]}")
    boundary = [("known_false_boundary", by_question_id[question_id]) for question_id in boundary_question_ids]
    boundary_ids = set(boundary_question_ids)
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        if row.get("question_id") in boundary_ids:
            continue
        grouped[(str(row["route_name"]), str(row["suggestion_family"]))].append(row)
    queues = [
        sorted(
            group_rows,
            key=lambda row: _rank(seed, f"false-row:{row['source_line']}:{row['question_id'] or ''}"),
        )
        for _, group_rows in sorted(
            grouped.items(),
            key=lambda item: (-len(item[1]), _rank(seed, f"false-group:{item[0][0]}:{item[0][1]}")),
        )
    ]
    selected: list[tuple[str, dict[str, object]]] = list(boundary)
    while len(selected) < sample_size:
        progressed = False
        for queue in queues:
            if not queue:
                continue
            selected.append(("false_route_suggestion", queue.pop(0)))
            progressed = True
            if len(selected) == sample_size:
                break
        if not progressed:
            break
    return selected


def build_p0_direct_diagnosis_packets(
    verification_path: Path,
    *,
    verify_label: str,
    teacher_definition: str,
    migration: KnowledgeTaxonomyMigration,
    true_output_path: Path,
    false_output_path: Path,
    audit_output_path: Path,
    false_sample_size: int,
    false_boundary_question_ids: tuple[str, ...] = (),
    seed: str,
) -> dict[str, object]:
    """Create all-true and stratified-false blind review packets for one P0 label.

    Direct-verifier fields are retained only in ``audit_output_path``.  The
    blind packets intentionally omit legacy labels and all direct model output.
    """
    target = _string(verify_label, field="verify_label", source="P0 diagnosis request")
    definition = _string(teacher_definition, field="teacher_definition", source="P0 diagnosis request")
    if not isinstance(migration, KnowledgeTaxonomyMigration):
        raise ValueError("migration must be a KnowledgeTaxonomyMigration")
    if not isinstance(false_sample_size, int) or isinstance(false_sample_size, bool) or false_sample_size < 0:
        raise ValueError("false_sample_size must be a non-negative integer")
    if not isinstance(seed, str) or not seed.strip():
        raise ValueError("seed must be non-empty")
    _require_fresh_paths(true_output_path, false_output_path, audit_output_path)
    taxonomy = migration.canonicalize(_legacy_path(target))

    direct_true: list[dict[str, object]] = []
    direct_false: list[dict[str, object]] = []
    contract_conflict_records = 0
    insufficient_records = 0
    direct_false_records = 0

    with verification_path.open("r", encoding="utf-8") as source:
        for source_line, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"verification line {source_line}: invalid JSON") from error
            if not isinstance(raw, Mapping):
                raise ValueError(f"verification line {source_line}: JSONL row must be an object")
            origin = f"verification line {source_line}"
            if _string(raw.get("verify_label"), field="verify_label", source=origin) != target:
                raise ValueError(f"{origin}: verify_label differs from requested label")
            direct_match = raw.get("llm_match")
            if not isinstance(direct_match, bool):
                raise ValueError(f"{origin}: llm_match must be boolean")
            input_text = _string(raw.get("input"), field="input", source=origin)
            suggestion = _optional_string(raw.get("llm_should_be")) or ""
            question_id = _optional_string(raw.get("question_id"))
            route = _route_key(input_text, raw.get("is_sub_question"))
            common = {
                "source_line": source_line,
                "question_id": question_id,
                "parent_id": _optional_string(raw.get("parent_id")),
                "route_key": route,
                "route_name": _route_name(route),
                "question_context": clean_mentor_v1_input(input_text).strip(),
                "direct_match": direct_match,
                "direct_should_be": suggestion or None,
                "direct_reason": _optional_string(raw.get("llm_reason")),
                "source_output_all": _optional_string(raw.get("output_all")),
            }
            if direct_match:
                direct_true.append(common)
                continue

            direct_false_records += 1
            if suggestion == "正确":
                contract_conflict_records += 1
                continue
            if not suggestion.startswith("知识点@"):
                insufficient_records += 1
                continue
            direct_false.append({**common, "suggestion_family": _suggestion_family(suggestion)})

    selected_false = _select_false_rows(
        direct_false,
        seed=seed,
        sample_size=false_sample_size,
        boundary_question_ids=false_boundary_question_ids,
    )
    selected = [("true", "direct_true_all", row) for row in direct_true] + [
        ("false", selection_stratum, row) for selection_stratum, row in selected_false
    ]
    selected.sort(
        key=lambda item: _rank(
            seed,
            _review_id(
                label=target,
                question_id=item[2]["question_id"] if isinstance(item[2]["question_id"], str) else None,
                source_line=int(item[2]["source_line"]),
                review_set=item[0],
            ),
        )
    )

    blind_true_rows: list[dict[str, object]] = []
    blind_false_rows: list[dict[str, object]] = []
    audit_rows: list[dict[str, object]] = []
    selected_false_by_route: Counter[str] = Counter()
    selected_false_by_suggestion: Counter[str] = Counter()
    for review_set, selection_stratum, row in selected:
        question_id = row["question_id"] if isinstance(row["question_id"], str) else None
        review_id = _review_id(
            label=target,
            question_id=question_id,
            source_line=int(row["source_line"]),
            review_set=review_set,
        )
        blind = {
            "schema_version": BLIND_SCHEMA_VERSION,
            "review_id": review_id,
            "legacy_label": target,
            "active_taxonomy_label": taxonomy.canonical_path,
            "taxonomy_migration_status": taxonomy.status,
            "taxonomy_migration_rule_id": taxonomy.rule_id,
            "teacher_definition": definition,
            "question_id": question_id,
            "parent_id": row["parent_id"],
            "route_key": row["route_key"],
            "question_context": row["question_context"],
        }
        if review_set == "true":
            blind_true_rows.append(blind)
        else:
            blind_false_rows.append(blind)
            selected_false_by_route[str(row["route_name"])] += 1
            selected_false_by_suggestion[str(row["suggestion_family"])] += 1
        audit_rows.append(
            {
                "schema_version": AUDIT_SCHEMA_VERSION,
                "experiment": "p0-direct-diagnosis",
                "review_id": review_id,
                "review_set": review_set,
                "selection_stratum": selection_stratum,
                "source_line": row["source_line"],
                "question_id": question_id,
                "route_key": row["route_key"],
                "direct_match": row["direct_match"],
                "direct_should_be": row["direct_should_be"],
                "direct_reason": row["direct_reason"],
                "source_output_all": row["source_output_all"],
                "suggestion_family": row.get("suggestion_family"),
            }
        )

    _write_jsonl(true_output_path, blind_true_rows)
    _write_jsonl(false_output_path, blind_false_rows)
    _write_jsonl(audit_output_path, audit_rows)
    return {
        "schema_version": "p0-direct-diagnosis-packet-report-v1",
        "verification_path": str(verification_path),
        "verify_label": target,
        "legacy_taxonomy_label": taxonomy.legacy_path,
        "active_taxonomy_label": taxonomy.canonical_path,
        "taxonomy_migration_status": taxonomy.status,
        "taxonomy_migration_rule_id": taxonomy.rule_id,
        "true_output_path": str(true_output_path),
        "false_output_path": str(false_output_path),
        "audit_output_path": str(audit_output_path),
        "seed": seed,
        "false_sample_size_requested": false_sample_size,
        "false_boundary_question_ids": list(false_boundary_question_ids),
        "direct_true_records": len(direct_true),
        "direct_false_records": direct_false_records,
        "false_candidates": len(direct_false),
        "contract_conflict_records": contract_conflict_records,
        "insufficient_records": insufficient_records,
        "selected_true_records": len(blind_true_rows),
        "selected_false_records": len(blind_false_rows),
        "selected_false_by_route": dict(sorted(selected_false_by_route.items())),
        "selected_false_by_suggestion_family": dict(sorted(selected_false_by_suggestion.items())),
    }
