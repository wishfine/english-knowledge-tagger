"""Build non-anchored reviewer packets from tree tasks and outcomes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from .knowledge_rulebook import load_knowledge_rulebook


_STATUSES = frozenset({"tree_candidate", "uncovered", "budget_exhausted", "unparsed"})


def _rows(path: Path, *, source: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{source} line {number}: invalid JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"{source} line {number}: row must be an object")
            rows.append(row)
    return rows


def _task_id(row: Mapping[str, object], *, source: str) -> str:
    value = row.get("task_id")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: task_id must be a non-empty string")
    return value.strip()


def _unique_index(rows: list[dict[str, object]], *, source: str) -> dict[str, dict[str, object]]:
    indexed: dict[str, dict[str, object]] = {}
    for position, row in enumerate(rows, 1):
        task_id = _task_id(row, source=f"{source} record {position}")
        if task_id in indexed:
            raise ValueError(f"{source}: duplicate task_id {task_id!r}")
        indexed[task_id] = row
    return indexed


def build_tree_candidate_review_packet(
    tasks_path: Path,
    *,
    audit_index_path: Path,
    results_path: Path,
    teacher_csv_path: Path,
    output_path: Path,
) -> dict[str, object]:
    """Join complete task context to candidate labels without leaking DS traces."""
    if output_path.exists():
        raise FileExistsError(f"tree candidate review output already exists: {output_path}")
    tasks = _rows(tasks_path, source="tree tasks")
    audit_by_task = _unique_index(_rows(audit_index_path, source="tree audit index"), source="tree audit index")
    results_by_task = _unique_index(_rows(results_path, source="tree results"), source="tree results")
    task_ids = [_task_id(row, source="tree task") for row in tasks]
    if set(task_ids) != set(audit_by_task):
        raise ValueError("tree audit index task IDs do not exactly match tree tasks")
    if set(task_ids) != set(results_by_task):
        raise ValueError("tree result task IDs do not exactly match tree tasks")
    rulebook = load_knowledge_rulebook(teacher_csv_path)

    packet: list[dict[str, object]] = []
    for task in tasks:
        task_id = _task_id(task, source="tree task")
        result = results_by_task[task_id]
        status = result.get("status")
        if status not in _STATUSES:
            raise ValueError(f"tree result {task_id!r}: unsupported review status {status!r}")
        candidate = result.get("candidate_label")
        if status == "tree_candidate":
            if not isinstance(candidate, str) or candidate not in rulebook.records or rulebook.records[candidate].status != "active":
                raise ValueError(f"tree result {task_id!r}: candidate_label must be an active terminal")
            definition = rulebook.records[candidate].target_definition
        else:
            if candidate is not None:
                raise ValueError(f"tree result {task_id!r}: non-candidate status cannot contain candidate_label")
            definition = ""
        context = task.get("question_context")
        if not isinstance(context, str) or not context.strip():
            raise ValueError(f"tree task {task_id!r}: question_context must be non-empty")
        stratum = audit_by_task[task_id].get("selection_stratum")
        if not isinstance(stratum, str) or not stratum.strip():
            raise ValueError(f"tree audit index {task_id!r}: selection_stratum must be non-empty")
        packet.append({
            "schema_version": "tree-candidate-review-packet-v1",
            "review_id": f"tree-candidate:{task_id}",
            "experiment": audit_by_task[task_id].get("experiment") or "tree-followup",
            "selection_stratum": stratum,
            "question_id": task.get("question_id"),
            "parent_id": task.get("parent_id"),
            "route_key": task.get("route_key"),
            "historical_label": task.get("historical_label"),
            "question_context": context,
            "tree_status": status,
            "tree_candidate_label": candidate,
            "tree_candidate_definition": definition,
        })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as handle:
        for row in packet:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {"schema_version": "tree-candidate-review-packet-report-v1", "tasks_path": str(tasks_path), "results_path": str(results_path), "audit_index_path": str(audit_index_path), "output_path": str(output_path), "review_records": len(packet)}
