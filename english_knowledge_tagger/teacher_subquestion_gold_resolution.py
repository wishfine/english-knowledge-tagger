"""Resolve teacher numbered small-question gold to exact rendered source children."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from .knowledge_rulebook import KnowledgeRulebook
from .knowledge_taxonomy_migration import KnowledgeTaxonomyMigration
from .sft_labels import parse_sft_output_labels


SCHEMA_VERSION = "teacher-subquestion-gold-resolution-v1"
CORRECTION_SCHEMA_VERSION = "teacher-subquestion-gold-correction-v1"
_TYPE_METADATA = re.compile(r"(?m)^\s*题型(结构|名称)为：([^\r\n]*)")


def _nonempty_string(value: object, *, field: str, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: {field} must be a non-empty string")
    return value.strip()


def _positive_int(value: object, *, field: str, source: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{source}: {field} must be a positive integer")
    return value


def _labels(value: object, *, field: str, source: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{source}: {field} must be a list")
    parsed = tuple(_nonempty_string(item, field=f"{field}[]", source=source) for item in value)
    if len(set(parsed)) != len(parsed):
        raise ValueError(f"{source}: {field} must not contain duplicates")
    if not all(label.startswith("知识点->") for label in parsed):
        raise ValueError(f"{source}: {field} labels must use canonical '知识点->' paths")
    return parsed


def _expected_child_id(parent_question_id: str, subquestion_index: int) -> str:
    if not parent_question_id.isdecimal():
        raise ValueError(
            "teacher subquestion resolver requires decimal numeric parent_question_id for "
            "the verified parent_id + subquestion_index mapping"
        )
    return str(int(parent_question_id) + subquestion_index)


def _canonical_history(record: Mapping[str, Any], *, migration: KnowledgeTaxonomyMigration) -> tuple[str, ...] | None:
    parsed = parse_sft_output_labels(record.get("output"))
    if parsed is None:
        return None
    knowledge_labels, _ = parsed
    return tuple(
        sorted(
            migration.canonicalize("知识点->" + label.removeprefix("知识点@").replace("@", "->")).canonical_path
            for label in knowledge_labels
        )
    )


def _route_key(value: object) -> dict[str, str] | None:
    if not isinstance(value, str):
        return None
    found = {match.group(1): match.group(2).strip() for match in _TYPE_METADATA.finditer(value)}
    if not found.get("结构") or not found.get("名称"):
        return None
    return {
        "scope": "child",
        "declared_type_structure": found["结构"],
        "declared_type_name": found["名称"],
    }


def _read_imported_gold(path: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    order: list[dict[str, Any]] = []
    by_expected_child_id: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            label = f"imported teacher gold line {line_number}"
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{label}: invalid JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"{label}: JSONL row must be an object")
            parent_question_id = _nonempty_string(
                row.get("parent_question_id"), field="parent_question_id", source=label
            )
            subquestion_index = _positive_int(
                row.get("subquestion_index"), field="subquestion_index", source=label
            )
            gold_labels = _labels(row.get("gold_labels"), field="gold_labels", source=label)
            expected_child_id = _expected_child_id(parent_question_id, subquestion_index)
            if expected_child_id in by_expected_child_id:
                raise ValueError(
                    f"{label}: parent_id + subquestion_index collides with another teacher gold row: "
                    f"{expected_child_id}"
                )
            normalized = {
                "source_gold_line": line_number,
                "parent_question_id": parent_question_id,
                "subquestion_index": subquestion_index,
                "expected_child_id": expected_child_id,
                "gold_labels": gold_labels,
                "taxonomy_resolved": row.get("taxonomy_resolved") is True,
                "source_gold": row,
            }
            order.append(normalized)
            by_expected_child_id[expected_child_id] = normalized
    return order, by_expected_child_id


def resolve_teacher_subquestion_gold(
    imported_gold_path: Path,
    *,
    source_path: Path,
    rulebook: KnowledgeRulebook,
    migration: KnowledgeTaxonomyMigration,
    output_path: Path,
    corrections_output_path: Path,
) -> dict[str, object]:
    """Resolve verified parent/index gold through the validated numeric child-ID convention."""
    if output_path.exists() or corrections_output_path.exists():
        raise FileExistsError("teacher gold resolved output or corrections output already exists")
    ordered_gold, gold_by_expected_child_id = _read_imported_gold(imported_gold_path)
    found: dict[str, tuple[int, dict[str, Any]]] = {}
    source_hasher = hashlib.sha256()
    with source_path.open("rb") as source:
        for source_line, raw_line in enumerate(source, 1):
            source_hasher.update(raw_line)
            if not raw_line.strip():
                continue
            try:
                line = raw_line.decode("utf-8")
                row = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError(f"source line {source_line}: invalid UTF-8 JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"source line {source_line}: JSONL row must be an object")
            question_id = row.get("question_id")
            if not isinstance(question_id, str) or question_id not in gold_by_expected_child_id:
                continue
            if question_id in found:
                raise ValueError(f"source has duplicate expected child question_id: {question_id}")
            found[question_id] = (source_line, row)

    resolved_rows: list[dict[str, object]] = []
    correction_rows: list[dict[str, object]] = []
    report_counts: Counter[str] = Counter()
    route_counts: Counter[str] = Counter()
    for gold in ordered_gold:
        expected_child_id = gold["expected_child_id"]
        source_match = found.get(expected_child_id)
        base: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "source_gold_line": gold["source_gold_line"],
            "parent_question_id": gold["parent_question_id"],
            "parent_id": gold["parent_question_id"],
            "child_rank": gold["subquestion_index"],
            "expected_child_question_id": expected_child_id,
            "gold_labels": list(gold["gold_labels"]),
            "teacher_taxonomy_resolved": gold["taxonomy_resolved"],
            "source_gold": gold["source_gold"],
        }
        if source_match is None:
            resolved_rows.append({**base, "adjudication_status": "unresolved_child_not_found"})
            report_counts["unresolved_child_not_found"] += 1
            continue
        source_line, source_record = source_match
        source_parent_id = source_record.get("parent_id")
        is_sub_question = source_record.get("is_sub_question")
        if source_parent_id != gold["parent_question_id"] or is_sub_question is not True:
            resolved_rows.append(
                {
                    **base,
                    "source_line": source_line,
                    "question_id": source_record.get("question_id"),
                    "source_parent_id": source_parent_id,
                    "is_sub_question": is_sub_question,
                    "adjudication_status": "unresolved_child_identity_mismatch",
                }
            )
            report_counts["unresolved_child_identity_mismatch"] += 1
            continue
        historical_labels = _canonical_history(source_record, migration=migration)
        route_key = _route_key(source_record.get("input"))
        if route_key is not None:
            route_counts[" × ".join(route_key.values())] += 1
        if historical_labels is None:
            resolved_rows.append(
                {
                    **base,
                    "source_line": source_line,
                    "question_id": expected_child_id,
                    "route_key": route_key,
                    "adjudication_status": "unresolved_source_output_not_labels",
                }
            )
            report_counts["unresolved_source_output_not_labels"] += 1
            continue
        historical_active = all(
            path in rulebook.records and rulebook.records[path].status == "active"
            for path in historical_labels
        )
        if not gold["taxonomy_resolved"] or not historical_active:
            status = "unresolved_taxonomy"
        else:
            status = "approved"
        gold_set = frozenset(gold["gold_labels"])
        historical_set = frozenset(historical_labels)
        missing_gold_labels = tuple(sorted(gold_set - historical_set))
        spurious_historical_labels = tuple(sorted(historical_set - gold_set))
        resolved = {
            **base,
            "source_line": source_line,
            "question_id": expected_child_id,
            "is_sub_question": True,
            "route_key": route_key,
            "historical_labels": list(historical_labels),
            "missing_gold_labels": list(missing_gold_labels),
            "spurious_historical_labels": list(spurious_historical_labels),
            "adjudication_status": status,
        }
        resolved_rows.append(resolved)
        report_counts[status] += 1
        if status != "approved":
            continue
        if not missing_gold_labels or not spurious_historical_labels:
            report_counts["approved_without_replace_pair"] += 1
            continue
        for historical_label in spurious_historical_labels:
            correction_rows.append(
                {
                    "schema_version": CORRECTION_SCHEMA_VERSION,
                    "source_gold_line": gold["source_gold_line"],
                    "source_line": source_line,
                    "question_id": expected_child_id,
                    "parent_id": gold["parent_question_id"],
                    "child_rank": gold["subquestion_index"],
                    "route_key": route_key,
                    "historical_label": historical_label,
                    "historical_labels": list(historical_labels),
                    "gold_labels": list(missing_gold_labels),
                    "all_teacher_gold_labels": list(gold["gold_labels"]),
                    "adjudication_status": "approved",
                    "adjudication_basis": "teacher_verified_parent_plus_subquestion_index",
                }
            )
            report_counts["correction_records"] += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    corrections_output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as output:
        for row in resolved_rows:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    with corrections_output_path.open("x", encoding="utf-8") as output:
        for row in correction_rows:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {
        "schema_version": SCHEMA_VERSION,
        "imported_gold_path": str(imported_gold_path),
        "source_path": str(source_path),
        "output_path": str(output_path),
        "corrections_output_path": str(corrections_output_path),
        "teacher_gold_records": len(ordered_gold),
        "source_children_found": len(found),
        "approved_gold_records": report_counts["approved"],
        "correction_records": report_counts["correction_records"],
        "status_counts": {
            key: value
            for key, value in sorted(report_counts.items())
            if key != "correction_records"
        },
        "routes": dict(sorted(route_counts.items())),
        "source_sha256": source_hasher.hexdigest(),
    }
