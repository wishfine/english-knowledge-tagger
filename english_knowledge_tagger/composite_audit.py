"""Disk-backed parent/child audit for large composite-question JSONL datasets."""

from __future__ import annotations

from collections import Counter
import json
from math import ceil, sqrt
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable


KNOWLEDGE_FIELDS = ("solve_func_ids",)
TYPE_FIELDS = ("question_type_ids", "questjon_type_ids")


def _sorted_counter(counter: Counter[int] | Counter[str]) -> dict[str, int]:
    return {str(key): counter[key] for key in sorted(counter, key=lambda value: str(value))}


def _labels(record: dict[str, Any], fields: tuple[str, ...]) -> frozenset[str]:
    for field in fields:
        if field not in record:
            continue
        value = record[field]
        if isinstance(value, list):
            return frozenset(str(item) for item in value if item is not None and item != "")
        if value is None or value == "":
            return frozenset()
        return frozenset({str(value)})
    return frozenset()


def _sft_output_labels(record: dict[str, Any]) -> tuple[frozenset[str], frozenset[str]] | None:
    """Parse legacy ``题型@...;知识点@...`` SFT targets when present."""
    output = record.get("output")
    if not isinstance(output, str):
        return None

    knowledge: set[str] = set()
    question_type: set[str] = set()
    recognized = False
    for fragment in re.split(r"[;；\n]+", output):
        label = fragment.strip()
        if label.startswith("知识点@"):
            recognized = True
            if label != "知识点@空":
                knowledge.add(label)
        elif label.startswith("题型@"):
            recognized = True
            if label != "题型@空":
                question_type.add(label)
    if not recognized:
        return None
    return frozenset(knowledge), frozenset(question_type)


def _knowledge_labels(record: dict[str, Any]) -> frozenset[str]:
    parsed = _sft_output_labels(record)
    return parsed[0] if parsed is not None else _labels(record, KNOWLEDGE_FIELDS)


def _type_labels(record: dict[str, Any]) -> frozenset[str]:
    parsed = _sft_output_labels(record)
    return parsed[1] if parsed is not None else _labels(record, TYPE_FIELDS)


def _scope(record: dict[str, Any], question_id: str, parent_id: str) -> str:
    if record.get("is_sub_question") is True:
        return "child"
    if record.get("is_sub_question") is False:
        return "parent"
    return "parent" if question_id == parent_id else "child"


def _id(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _relation(child: frozenset[str], parent: frozenset[str]) -> str:
    if not child:
        return "child_empty"
    if child == parent:
        return "equal"
    if child <= parent:
        return "subset_not_equal"
    return "child_contains_parent_external"


def _cardinality_template() -> dict[str, Counter[int]]:
    return {"parent": Counter(), "child": Counter()}


def _quantile(values: list[int], quantile: float) -> float:
    return float(values[max(0, ceil(quantile * len(values)) - 1)])


def _child_count_summary(values: list[int]) -> dict[str, float | int | None]:
    if not values:
        return {
            "mean": None,
            "stddev": None,
            "median": None,
            "min": None,
            "max": None,
            "p25": None,
            "p50": None,
            "p75": None,
            "p90": None,
            "p95": None,
            "p99": None,
        }
    values = sorted(values)
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return {
        "mean": mean,
        "stddev": sqrt(variance),
        "median": _quantile(values, 0.50),
        "min": values[0],
        "max": values[-1],
        "p25": _quantile(values, 0.25),
        "p50": _quantile(values, 0.50),
        "p75": _quantile(values, 0.75),
        "p90": _quantile(values, 0.90),
        "p95": _quantile(values, 0.95),
        "p99": _quantile(values, 0.99),
    }


def _create_index(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE parents (
            parent_id TEXT PRIMARY KEY,
            knowledge_json TEXT NOT NULL,
            type_json TEXT NOT NULL
        );
        CREATE TABLE child_counts (
            parent_id TEXT PRIMARY KEY,
            child_count INTEGER NOT NULL
        );
        """
    )


def _load_parent(
    cursor: sqlite3.Cursor, parent_id: str
) -> tuple[frozenset[str], frozenset[str]] | None:
    row = cursor.execute(
        "SELECT knowledge_json, type_json FROM parents WHERE parent_id = ?", (parent_id,)
    ).fetchone()
    if row is None:
        return None
    return frozenset(json.loads(row[0])), frozenset(json.loads(row[1]))


def _iter_records(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                yield record


def audit_jsonl(
    path: Path,
    *,
    index_path: Path,
    discourse_knowledge_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Audit parent/child label relations using a SQLite index instead of RAM.

    ``index_path`` must not exist. Keeping this index is intentional: it gives later
    review-packet generation the same parent lookup without another full scan.
    """
    if index_path.exists():
        raise FileExistsError(f"audit index already exists: {index_path}")
    index_path.parent.mkdir(parents=True, exist_ok=True)
    discourse_ids = frozenset(discourse_knowledge_ids or set())

    records = Counter[str]()
    knowledge_cardinality = _cardinality_template()
    type_cardinality = _cardinality_template()
    duplicate_parent_ids = 0

    connection = sqlite3.connect(index_path)
    try:
        _create_index(connection)
        cursor = connection.cursor()
        for record in _iter_records(path):
            records["valid"] += 1
            question_id = _id(record.get("question_id"))
            parent_id = _id(record.get("parent_id"))
            if question_id is None or parent_id is None:
                records["missing_ids"] += 1
                continue

            knowledge = _knowledge_labels(record)
            question_type = _type_labels(record)
            scope = _scope(record, question_id, parent_id)
            knowledge_cardinality[scope][len(knowledge)] += 1
            type_cardinality[scope][len(question_type)] += 1

            if scope == "parent":
                records["parents"] += 1
                inserted = cursor.execute(
                    "INSERT OR IGNORE INTO parents(parent_id, knowledge_json, type_json) VALUES (?, ?, ?)",
                    (
                        parent_id,
                        json.dumps(sorted(knowledge), ensure_ascii=False),
                        json.dumps(sorted(question_type), ensure_ascii=False),
                    ),
                ).rowcount
                if not inserted:
                    duplicate_parent_ids += 1
            else:
                records["children"] += 1
                cursor.execute(
                    """
                    INSERT INTO child_counts(parent_id, child_count) VALUES (?, 1)
                    ON CONFLICT(parent_id) DO UPDATE SET child_count = child_count + 1
                    """,
                    (parent_id,),
                )
        connection.commit()

        child_count_rows = cursor.execute(
            """
            SELECT c.child_count
            FROM child_counts AS c
            INNER JOIN parents AS p ON p.parent_id = c.parent_id
            """
        ).fetchall()
        child_counts = [int(row[0]) for row in child_count_rows]
        child_count_distribution: Counter[int] = Counter(child_counts)
        parents_with_children = len(child_counts)

        knowledge_relation: Counter[str] = Counter()
        type_relation: Counter[str] = Counter()
        discourse_report: Counter[str] = Counter()
        orphan_children = 0
        for record in _iter_records(path):
            question_id = _id(record.get("question_id"))
            parent_id = _id(record.get("parent_id"))
            if question_id is None or parent_id is None or _scope(record, question_id, parent_id) == "parent":
                continue
            parent = _load_parent(cursor, parent_id)
            if parent is None:
                orphan_children += 1
                knowledge_relation["parent_missing"] += 1
                type_relation["parent_missing"] += 1
                continue

            parent_knowledge, parent_type = parent
            child_knowledge = _knowledge_labels(record)
            child_type = _type_labels(record)
            knowledge_relation[_relation(child_knowledge, parent_knowledge)] += 1
            type_relation[_relation(child_type, parent_type)] += 1
            if discourse_ids:
                residual = child_knowledge - discourse_ids
                if residual:
                    discourse_report["children_with_non_discourse_knowledge"] += 1
                else:
                    discourse_report["children_with_only_discourse_knowledge"] += 1

        for relation in (
            "equal",
            "child_empty",
            "subset_not_equal",
            "child_contains_parent_external",
            "parent_missing",
        ):
            knowledge_relation.setdefault(relation, 0)
            type_relation.setdefault(relation, 0)
        if discourse_ids:
            for key in (
                "children_with_non_discourse_knowledge",
                "children_with_only_discourse_knowledge",
            ):
                discourse_report.setdefault(key, 0)

        return {
            "schema_version": "composite-audit-v1",
            "source_path": str(path),
            "source_bytes": path.stat().st_size,
            "index_path": str(index_path),
            "records": {
                "valid": records["valid"],
                "parents": records["parents"],
                "children": records["children"],
                "missing_ids": records["missing_ids"],
            },
            "integrity": {"duplicate_parent_ids": duplicate_parent_ids},
            "parent_groups": {
                "parents_with_children": parents_with_children,
                "parents_without_children": records["parents"] - parents_with_children,
                "orphan_children": orphan_children,
                "child_count_distribution": _sorted_counter(child_count_distribution),
                "child_count_summary": _child_count_summary(child_counts),
            },
            "knowledge_parent_child": _sorted_counter(knowledge_relation),
            "type_parent_child": _sorted_counter(type_relation),
            "after_discourse_removal": _sorted_counter(discourse_report),
            "label_cardinality": {
                "knowledge": {
                    scope: _sorted_counter(counts)
                    for scope, counts in knowledge_cardinality.items()
                },
                "type": {
                    scope: _sorted_counter(counts) for scope, counts in type_cardinality.items()
                },
            },
        }
    finally:
        connection.close()
