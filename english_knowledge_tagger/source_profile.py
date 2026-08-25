"""Streaming, schema-aware profiling for the English question JSONL sources."""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Any


KNOWLEDGE_LABEL_FIELDS = ("solve_func_ids",)
TYPE_LABEL_FIELDS = ("question_type_ids", "questjon_type_ids")


def _as_sorted_dict(counter: Counter[str] | Counter[int]) -> dict[str, int]:
    return {str(key): counter[key] for key in sorted(counter, key=lambda item: str(item))}


def _label_values(record: dict[str, Any], fields: tuple[str, ...]) -> list[Any]:
    """Return the first present label field, treating empty values as missing supervision."""
    for field in fields:
        if field not in record:
            continue
        value = record[field]
        if isinstance(value, list):
            return value
        if value is None or value == "":
            return []
        return [value]
    return []


def _parent_child_bucket(record: dict[str, Any]) -> str:
    question_id = record.get("question_id")
    parent_id = record.get("parent_id")
    if question_id is None or parent_id is None or question_id == "" or parent_id == "":
        return "missing_ids"
    return "root" if str(question_id) == str(parent_id) else "child"


def _standalone_bucket(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "missing"
    return "other"


def profile_jsonl(path: Path, *, max_records: int | None = None) -> dict[str, Any]:
    """Profile a JSONL source in one pass without loading it into memory.

    Empty label arrays are reported as absent supervision, never as a negative class.
    ``max_records`` bounds valid object records for fast development sampling.
    """
    if max_records is not None and max_records <= 0:
        raise ValueError("max_records must be positive when provided")

    field_presence: Counter[str] = Counter()
    field_types: dict[str, Counter[str]] = defaultdict(Counter)
    parent_child: Counter[str] = Counter()
    standalone: Counter[str] = Counter()
    supervision: Counter[str] = Counter()
    knowledge_cardinality: Counter[int] = Counter()
    type_cardinality: Counter[int] = Counter()
    knowledge_label_counts: Counter[str] = Counter()
    type_label_counts: Counter[str] = Counter()
    image_field_presence: Counter[str] = Counter()
    cleaned_content: Counter[str] = Counter()

    nonempty_lines = 0
    valid_records = 0
    invalid_json_lines = 0
    non_object_lines = 0

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            nonempty_lines += 1
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                invalid_json_lines += 1
                continue
            if not isinstance(record, dict):
                non_object_lines += 1
                continue

            valid_records += 1
            for field, value in record.items():
                field_presence[field] += 1
                field_types[field][type(value).__name__] += 1
                if "image" in field.lower():
                    image_field_presence[field] += 1

            parent_child[_parent_child_bucket(record)] += 1
            standalone[_standalone_bucket(record.get("is_standalone"))] += 1

            knowledge_labels = _label_values(record, KNOWLEDGE_LABEL_FIELDS)
            type_labels = _label_values(record, TYPE_LABEL_FIELDS)
            knowledge_cardinality[len(knowledge_labels)] += 1
            type_cardinality[len(type_labels)] += 1
            knowledge_label_counts.update(str(label) for label in knowledge_labels)
            type_label_counts.update(str(label) for label in type_labels)

            if knowledge_labels and type_labels:
                supervision["both"] += 1
            elif knowledge_labels:
                supervision["knowledge_only"] += 1
            elif type_labels:
                supervision["type_only"] += 1
            else:
                supervision["neither"] += 1

            cleaned = record.get("question_info_cleaned")
            if isinstance(cleaned, dict):
                cleaned_content["dict"] += 1
                if cleaned.get("current_sub_question_stem"):
                    cleaned_content["sub_question_stem_present"] += 1
                if cleaned.get("parent_analysis_and_answer"):
                    cleaned_content["parent_answer_present"] += 1
            elif cleaned is None:
                cleaned_content["missing"] += 1
            else:
                cleaned_content["non_dict"] += 1

            if max_records is not None and valid_records >= max_records:
                break

    for key in ("root", "child", "missing_ids"):
        parent_child.setdefault(key, 0)
    for key in ("both", "knowledge_only", "type_only", "neither"):
        supervision.setdefault(key, 0)
    for key in ("dict", "missing", "sub_question_stem_present", "parent_answer_present"):
        cleaned_content.setdefault(key, 0)

    return {
        "schema_version": "source-profile-v2",
        "source_path": str(path),
        "source_bytes": path.stat().st_size,
        "max_records": max_records,
        "nonempty_lines": nonempty_lines,
        "valid_records": valid_records,
        "invalid_json_lines": invalid_json_lines,
        "non_object_lines": non_object_lines,
        "field_presence": _as_sorted_dict(field_presence),
        "field_types": {
            field: _as_sorted_dict(types) for field, types in sorted(field_types.items())
        },
        "parent_child": _as_sorted_dict(parent_child),
        "is_standalone": _as_sorted_dict(standalone),
        "supervision": _as_sorted_dict(supervision),
        "label_cardinality": {
            "knowledge": _as_sorted_dict(knowledge_cardinality),
            "type": _as_sorted_dict(type_cardinality),
        },
        "knowledge_label_counts": _as_sorted_dict(knowledge_label_counts),
        "type_label_counts": _as_sorted_dict(type_label_counts),
        "image_field_presence": _as_sorted_dict(image_field_presence),
        "cleaned_content": _as_sorted_dict(cleaned_content),
    }
