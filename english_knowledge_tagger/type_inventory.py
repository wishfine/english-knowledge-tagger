"""Inventory declared question types in rendered SFT JSONL, split by parent/child scope."""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import re
from typing import Any

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


def _sorted_counter(counter: Counter[int] | Counter[str]) -> dict[str, int]:
    return {str(key): counter[key] for key in sorted(counter, key=lambda value: str(value))}


def inventory_sft_jsonl(path: Path, *, sample_limit: int = 3) -> dict[str, Any]:
    """Return a scope-separated inventory used to map every observed type to policy."""
    if sample_limit <= 0:
        raise ValueError("sample_limit must be positive")

    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    scope_counts: Counter[str] = Counter()
    valid_records = 0
    invalid_json_lines = 0

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                invalid_json_lines += 1
                continue
            if not isinstance(record, dict):
                continue

            valid_records += 1
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
                    "historical_type_labels": Counter(),
                    "sample_question_ids": [],
                }
            group = groups[key]
            parsed = parse_sft_output_labels(record.get("output"))
            knowledge, question_type = parsed if parsed is not None else (frozenset(), frozenset())
            group["record_count"] += 1
            group["knowledge_label_count_distribution"][len(knowledge)] += 1
            group["historical_type_labels"].update(question_type)
            question_id = record.get("question_id")
            if isinstance(question_id, str) and question_id and len(group["sample_question_ids"]) < sample_limit:
                group["sample_question_ids"].append(question_id)
            scope_counts[scope] += 1

    scope_order = {"parent": 0, "child": 1, "unknown": 2}
    rows = []
    for group in sorted(
        groups.values(),
        key=lambda item: (
            scope_order[item["scope"]],
            item["declared_type_structure"],
            item["declared_type_name"],
        ),
    ):
        rows.append(
            {
                "scope": group["scope"],
                "declared_type_structure": group["declared_type_structure"],
                "declared_type_name": group["declared_type_name"],
                "record_count": group["record_count"],
                "knowledge_label_count_distribution": _sorted_counter(
                    group["knowledge_label_count_distribution"]
                ),
                "historical_type_labels": _sorted_counter(group["historical_type_labels"]),
                "sample_question_ids": group["sample_question_ids"],
            }
        )

    return {
        "schema_version": "type-inventory-v1",
        "source_path": str(path),
        "source_bytes": path.stat().st_size,
        "valid_records": valid_records,
        "invalid_json_lines": invalid_json_lines,
        "scope_counts": {scope: scope_counts[scope] for scope in ("parent", "child", "unknown")},
        "rows": rows,
    }
