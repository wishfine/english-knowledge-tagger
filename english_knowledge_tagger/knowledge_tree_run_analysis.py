"""Deterministic summaries for three-repeat knowledge-tree prompt ablations."""

from __future__ import annotations

from collections import Counter
from statistics import fmean
from typing import Mapping, Sequence

from .knowledge_taxonomy_tree import NO_MATCH


Run = tuple[str, tuple[Mapping[str, object], ...]]


def _task_id(row: Mapping[str, object], *, run_name: str) -> str:
    value = row.get("task_id")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"run {run_name}: every row needs a non-empty task_id")
    return value.strip()


def _rows_by_task_id(rows: Sequence[Mapping[str, object]], *, run_name: str) -> dict[str, Mapping[str, object]]:
    indexed: dict[str, Mapping[str, object]] = {}
    for row in rows:
        task_id = _task_id(row, run_name=run_name)
        if task_id in indexed:
            raise ValueError(f"run {run_name}: duplicate task_id {task_id}")
        indexed[task_id] = row
    return indexed


def _trace_length(row: Mapping[str, object]) -> int:
    trace = row.get("trace")
    return len(trace) if isinstance(trace, list) else 0


def _no_match_count(row: Mapping[str, object]) -> int:
    trace = row.get("trace")
    if not isinstance(trace, list):
        return 0
    return sum(1 for step in trace if isinstance(step, Mapping) and step.get("choice") == NO_MATCH)


def _run_summary(name: str, rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    statuses = Counter(
        str(row.get("status")) if row.get("status") is not None else "missing" for row in rows
    )
    lengths = [_trace_length(row) for row in rows]
    no_matches = [_no_match_count(row) for row in rows]
    return {
        "name": name,
        "tasks": len(rows),
        "status_counts": dict(sorted(statuses.items())),
        "mean_trace_steps": fmean(lengths) if lengths else None,
        "mean_no_match_steps": fmean(no_matches) if no_matches else None,
    }


def _decision(row: Mapping[str, object]) -> tuple[str, str | None]:
    status = row.get("status")
    label = row.get("candidate_label")
    return (str(status) if status is not None else "missing", label if isinstance(label, str) else None)


def _agreement(
    indexed_runs: Sequence[Mapping[str, Mapping[str, object]]], task_ids: Sequence[str]
) -> dict[str, object]:
    if not task_ids:
        return {
            "tasks": 0,
            "all_three_decision_agreement": None,
            "all_three_candidate_agreement": None,
            "decision_disagreement_task_ids": [],
            "candidate_disagreement_task_ids": [],
        }
    same_decisions = 0
    same_candidates = 0
    decision_disagreements: list[str] = []
    candidate_disagreements: list[str] = []
    for task_id in task_ids:
        decisions = tuple(_decision(run[task_id]) for run in indexed_runs)
        if len(set(decisions)) == 1:
            same_decisions += 1
        else:
            decision_disagreements.append(task_id)
        if all(status == "tree_candidate" and label is not None for status, label in decisions) and len(
            {label for _, label in decisions}
        ) == 1:
            same_candidates += 1
        else:
            candidate_disagreements.append(task_id)
    count = len(task_ids)
    return {
        "tasks": count,
        "all_three_decision_agreement": same_decisions / count,
        "all_three_candidate_agreement": same_candidates / count,
        "decision_disagreement_task_ids": decision_disagreements,
        "candidate_disagreement_task_ids": candidate_disagreements,
    }


def _group_summary(
    group_name: str, runs: Sequence[Run]
) -> tuple[dict[str, object], tuple[dict[str, Mapping[str, object]], ...]]:
    if len(runs) != 3:
        raise ValueError(f"group {group_name} must contain exactly three runs")
    names = [name for name, _ in runs]
    if len(set(names)) != len(names):
        raise ValueError(f"group {group_name} has duplicate run names")
    indexed_runs = [_rows_by_task_id(rows, run_name=name) for name, rows in runs]
    modes = {
        row.get("terminal_definition_mode")
        for indexed in indexed_runs
        for row in indexed.values()
    }
    if len(modes) != 1 or not isinstance(next(iter(modes), None), str):
        raise ValueError(f"group {group_name} must contain exactly one terminal_definition_mode")
    mode = next(iter(modes))
    common_task_ids = sorted(set.intersection(*(set(indexed) for indexed in indexed_runs)))
    replace_task_ids = [
        task_id
        for task_id in common_task_ids
        if isinstance(indexed_runs[0][task_id].get("trigger_kinds"), list)
        and "replace" in indexed_runs[0][task_id]["trigger_kinds"]
    ]
    summary = {
        "mode": mode,
        "runs": [_run_summary(name, rows) for name, rows in runs],
        "common_tasks": len(common_task_ids),
        "all_tasks": _agreement(indexed_runs, common_task_ids),
        "replace": _agreement(indexed_runs, replace_task_ids),
    }
    return summary, tuple(indexed_runs)


def summarize_run_groups(groups: Mapping[str, tuple[Run, ...]]) -> dict[str, object]:
    """Summarize exact three-repeat agreement without making a prompt choice automatically."""
    if not groups:
        raise ValueError("at least one run group is required")
    summaries: dict[str, dict[str, object]] = {}
    indexed_groups: dict[str, tuple[dict[str, Mapping[str, object]], ...]] = {}
    for name, runs in sorted(groups.items()):
        summary, indexed_runs = _group_summary(name, runs)
        summaries[name] = summary
        indexed_groups[name] = indexed_runs

    comparison: dict[str, object] = {
        "common_tasks_all_six": None,
        "unanimous_candidate_disagreements": None,
        "unanimous_candidate_disagreement_task_ids": [],
    }
    if {"compressed", "none"}.issubset(indexed_groups):
        compressed_indexes = indexed_groups["compressed"]
        none_indexes = indexed_groups["none"]
        common = sorted(
            set.intersection(*(set(indexed) for indexed in (*compressed_indexes, *none_indexes)))
        )
        disagreements = 0
        disagreement_task_ids: list[str] = []
        for task_id in common:
            # A cross-mode comparison is valid only for individually unanimous candidates.
            compressed_labels = {_decision(indexed[task_id]) for indexed in compressed_indexes}
            none_labels = {_decision(indexed[task_id]) for indexed in none_indexes}
            if (
                len(compressed_labels) == 1
                and len(none_labels) == 1
                and next(iter(compressed_labels))[0] == "tree_candidate"
                and next(iter(none_labels))[0] == "tree_candidate"
                and next(iter(compressed_labels))[1] != next(iter(none_labels))[1]
            ):
                disagreements += 1
                disagreement_task_ids.append(task_id)
        comparison = {
            "common_tasks_all_six": len(common),
            "unanimous_candidate_disagreements": disagreements,
            "unanimous_candidate_disagreement_task_ids": disagreement_task_ids,
        }
    return {
        "schema_version": "knowledge-tree-run-analysis-v1",
        "groups": summaries,
        "comparison": comparison,
    }
