"""Compare paired knowledge-tree runs with and without a definition overlay."""

from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path
from statistics import fmean
from typing import Mapping


SCHEMA_VERSION = "knowledge-definition-ablation-analysis-v1"


def _load_rows(path: Path, *, name: str) -> dict[str, Mapping[str, object]]:
    rows: dict[str, Mapping[str, object]] = {}
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{name} line {line_number} is not valid JSON") from error
            if not isinstance(row, Mapping):
                raise ValueError(f"{name} line {line_number} must be an object")
            task_id = row.get("task_id")
            if not isinstance(task_id, str) or not task_id.strip():
                raise ValueError(f"{name} line {line_number} needs a non-empty task_id")
            task_id = task_id.strip()
            if task_id in rows:
                raise ValueError(f"{name} has duplicate task_id: {task_id}")
            rows[task_id] = row
    return rows


def _decision(row: Mapping[str, object]) -> tuple[object, object]:
    return row.get("status"), row.get("candidate_label")


def _status_counts(rows: Mapping[str, Mapping[str, object]]) -> dict[str, int]:
    return dict(
        sorted(
            Counter(
                str(row.get("status")) if row.get("status") is not None else "missing"
                for row in rows.values()
            ).items()
        )
    )


def _timing_stats(rows: Mapping[str, Mapping[str, object]]) -> dict[str, object]:
    values: list[float] = []
    for row in rows.values():
        value = row.get("task_elapsed_ms")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            values.append(float(value))
    values.sort()
    if not values:
        return {"count": 0, "mean": None, "p50": None, "p95": None, "max": None}

    def percentile(rank: float) -> float:
        index = min(len(values) - 1, max(0, math.ceil(rank * len(values)) - 1))
        return values[index]

    return {
        "count": len(values),
        "mean": fmean(values),
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "max": values[-1],
    }


def summarize_definition_ablation(baseline_path: Path, override_path: Path) -> dict[str, object]:
    """Summarize two runs made from the exact same frozen task packet."""
    baseline = _load_rows(baseline_path, name="baseline")
    override = _load_rows(override_path, name="override")
    baseline_ids = set(baseline)
    override_ids = set(override)
    if baseline_ids != override_ids:
        missing_in_override = sorted(baseline_ids - override_ids)
        missing_in_baseline = sorted(override_ids - baseline_ids)
        raise ValueError(
            "baseline and override task sets differ: "
            f"missing_in_override={missing_in_override[:3]}, "
            f"missing_in_baseline={missing_in_baseline[:3]}"
        )

    task_ids = sorted(baseline_ids)
    status_changes = [task_id for task_id in task_ids if baseline[task_id].get("status") != override[task_id].get("status")]
    candidate_changes = [
        task_id
        for task_id in task_ids
        if baseline[task_id].get("candidate_label") != override[task_id].get("candidate_label")
    ]
    decision_changes = [
        task_id for task_id in task_ids if _decision(baseline[task_id]) != _decision(override[task_id])
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "baseline_path": str(baseline_path),
        "override_path": str(override_path),
        "common_tasks": len(task_ids),
        "baseline_status_counts": _status_counts(baseline),
        "override_status_counts": _status_counts(override),
        "status_changes": len(status_changes),
        "status_change_task_ids": status_changes,
        "candidate_changes": len(candidate_changes),
        "candidate_change_task_ids": candidate_changes,
        "decision_changes": len(decision_changes),
        "decision_change_task_ids": decision_changes,
        "timing_ms": {
            "baseline": _timing_stats(baseline),
            "override": _timing_stats(override),
        },
    }
