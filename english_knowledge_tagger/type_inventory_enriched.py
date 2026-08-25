"""Enriched, streaming question-type inventory for rendered SFT JSONL."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable

from .sft_labels import parse_sft_output_labels


MISSING = "__MISSING__"
_TYPE_STRUCTURE_PATTERN = re.compile(r"(?:^|\n)题型结构为：([^\n\r]+)")
_TYPE_NAME_PATTERN = re.compile(r"(?:^|\n)题型名称为：([^\n\r]+)")


def _declared_value(pattern: re.Pattern[str], text: object) -> str:
    if not isinstance(text, str):
        return MISSING
    match = pattern.search(text)
    if match is None:
        return MISSING
    value = match.group(1).strip()
    return value or MISSING


def _scope(record: dict[str, Any]) -> str:
    if record.get("is_sub_question") is True:
        return "child"
    if record.get("is_sub_question") is False:
        return "parent"
    return "unknown"


def _question_id(record: dict[str, Any]) -> str | None:
    value = record.get("question_id")
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return None
    normalized = str(value).strip()
    return normalized or None


def _sorted_counter(counter: Counter[int] | Counter[str]) -> dict[str, int]:
    return {str(key): counter[key] for key in sorted(counter, key=lambda value: str(value))}


def inventory_sft_jsonl_enriched(
    path: Path,
    *,
    sample_per_label: int = 10,
    sample_unlabeled: int = 10,
    progress_every: int | None = None,
    progress_callback: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    """Build a type-inventory-v2 report without loading source records into memory."""
    if sample_per_label <= 0:
        raise ValueError("sample_per_label must be positive")
    if sample_unlabeled <= 0:
        raise ValueError("sample_unlabeled must be positive")
    if progress_every is not None and progress_every <= 0:
        raise ValueError("progress_every must be positive when provided")

    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    scope_counts: Counter[str] = Counter()
    valid_records = 0
    invalid_json_lines = 0
    non_object_lines = 0
    source_digest = hashlib.sha256()

    with path.open("rb") as handle:
        for raw_line in handle:
            source_digest.update(raw_line)
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                invalid_json_lines += 1
                continue
            if not isinstance(record, dict):
                non_object_lines += 1
                continue

            valid_records += 1
            if (
                progress_callback is not None
                and progress_every is not None
                and valid_records % progress_every == 0
            ):
                progress_callback(valid_records)
            scope = _scope(record)
            structure = _declared_value(_TYPE_STRUCTURE_PATTERN, record.get("input"))
            name = _declared_value(_TYPE_NAME_PATTERN, record.get("input"))
            key = (scope, structure, name)
            if key not in groups:
                groups[key] = {
                    "scope": scope,
                    "declared_type_structure": structure,
                    "declared_type_name": name,
                    "record_count": 0,
                    "knowledge_label_count_distribution": Counter(),
                    "type_label_count_distribution": Counter(),
                    "historical_type_labels": Counter(),
                    "type_label_combinations": Counter(),
                    "samples_by_historical_label": {},
                    "unlabeled_sample_question_ids": [],
                }

            parsed = parse_sft_output_labels(record.get("output"))
            knowledge, question_types = parsed if parsed is not None else (frozenset(), frozenset())
            group = groups[key]
            group["record_count"] += 1
            group["knowledge_label_count_distribution"][len(knowledge)] += 1
            group["type_label_count_distribution"][len(question_types)] += 1
            group["historical_type_labels"].update(question_types)
            combination = tuple(sorted(question_types))
            group["type_label_combinations"][combination] += 1

            question_id = _question_id(record)
            if question_id is not None:
                if question_types:
                    for label in sorted(question_types):
                        samples = group["samples_by_historical_label"].setdefault(label, [])
                        if len(samples) < sample_per_label:
                            samples.append(question_id)
                elif len(group["unlabeled_sample_question_ids"]) < sample_unlabeled:
                    group["unlabeled_sample_question_ids"].append(question_id)
            scope_counts[scope] += 1

    rows = []
    scope_order = {"parent": 0, "child": 1, "unknown": 2}
    for group in sorted(
        groups.values(),
        key=lambda item: (
            scope_order[item["scope"]],
            item["declared_type_structure"],
            item["declared_type_name"],
        ),
    ):
        type_cardinality = group["type_label_count_distribution"]
        rows.append(
            {
                "scope": group["scope"],
                "declared_type_structure": group["declared_type_structure"],
                "declared_type_name": group["declared_type_name"],
                "record_count": group["record_count"],
                "knowledge_label_count_distribution": _sorted_counter(
                    group["knowledge_label_count_distribution"]
                ),
                "type_label_count_distribution": _sorted_counter(type_cardinality),
                "unlabeled_record_count": type_cardinality[0],
                "type_label_assignment_count": sum(
                    cardinality * count for cardinality, count in type_cardinality.items()
                ),
                "historical_type_labels": _sorted_counter(group["historical_type_labels"]),
                "type_label_combination_counts": [
                    {"labels": list(labels), "record_count": count}
                    for labels, count in sorted(group["type_label_combinations"].items())
                ],
                "samples_by_historical_label": {
                    label: group["samples_by_historical_label"][label]
                    for label in sorted(group["samples_by_historical_label"])
                },
                "unlabeled_sample_question_ids": group["unlabeled_sample_question_ids"],
            }
        )

    return {
        "schema_version": "type-inventory-v2",
        "source_path": str(path),
        "source_bytes": path.stat().st_size,
        "source_sha256": source_digest.hexdigest(),
        "sample_per_label": sample_per_label,
        "sample_unlabeled": sample_unlabeled,
        "valid_records": valid_records,
        "invalid_json_lines": invalid_json_lines,
        "non_object_lines": non_object_lines,
        "scope_counts": {scope: scope_counts[scope] for scope in ("parent", "child", "unknown")},
        "rows": rows,
    }
