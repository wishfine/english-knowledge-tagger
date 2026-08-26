"""Summarise knowledge-label validation latency without retaining question content."""

from __future__ import annotations

from collections import Counter, defaultdict
from math import ceil, isfinite
from statistics import fmean
from typing import Iterable, Mapping


TIMING_REPORT_SCHEMA_VERSION = "knowledge-validation-timing-report-v1"


def _number(value: object) -> float | None:
    """Return finite, non-negative numeric measurements while rejecting booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if isfinite(parsed) and parsed >= 0 else None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, ceil(percentile * len(ordered)) - 1)]


def _stats(values: Iterable[float]) -> dict[str, float | int | None]:
    items = list(values)
    if not items:
        return {"count": 0, "mean": None, "p50": None, "p95": None, "p99": None, "max": None}
    return {
        "count": len(items),
        "mean": fmean(items),
        "p50": _percentile(items, 0.50),
        "p95": _percentile(items, 0.95),
        "p99": _percentile(items, 0.99),
        "max": max(items),
    }


def _mean(values: list[float]) -> float | None:
    return fmean(values) if values else None


def _target_parent_path(row: Mapping[str, object]) -> str | None:
    """Prefer an explicit historical parent and otherwise derive the canonical parent."""
    for field in (
        "historical_target_parent_path",
        "target_parent_path",
        "canonical_parent_path",
    ):
        value = row.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for field in ("canonical_label", "legacy_label"):
        value = row.get(field)
        if not isinstance(value, str):
            continue
        parent, separator, _ = value.strip().rpartition("->")
        if separator and parent:
            return parent
    return None


def summarize_validation_timing(
    rows: Iterable[Mapping[str, object]], *, wall_elapsed_ms: float, concurrency: int
) -> dict[str, object]:
    """Aggregate completed validation rows by historical label parent and latency.

    The report deliberately excludes question context, evidence, reasons, and raw model
    output.  Its slow-row identities are sufficient to locate a source row while leaving
    the potentially large or sensitive content in the JSONL result file.
    """
    if concurrency <= 0:
        raise ValueError("concurrency must be positive")
    valid_wall_elapsed_ms = _number(wall_elapsed_ms)
    if valid_wall_elapsed_ms is None:
        raise ValueError("wall_elapsed_ms must be a finite non-negative number")

    task_values: list[float] = []
    queue_values: list[float] = []
    model_values: list[float] = []
    prompt_values: list[float] = []
    response_values: list[float] = []
    status_counts: Counter[str] = Counter()
    parent_values: defaultdict[str, dict[str, object]] = defaultdict(
        lambda: {
            "task_elapsed_ms": [],
            "queue_elapsed_ms": [],
            "model_call_elapsed_ms": [],
            "prompt_chars": [],
            "response_chars": [],
        }
    )
    slow_rows: list[dict[str, object]] = []
    processed = 0

    for row in rows:
        processed += 1
        status = str(row.get("status", "missing"))
        status_counts[status] += 1
        task_elapsed_ms = _number(row.get("task_elapsed_ms"))
        queue_elapsed_ms = _number(row.get("queue_elapsed_ms"))
        model_call_elapsed_ms = _number(row.get("model_call_elapsed_ms"))
        prompt_chars = _number(row.get("prompt_chars"))
        response_chars = _number(row.get("response_chars"))
        if task_elapsed_ms is not None:
            task_values.append(task_elapsed_ms)
        if queue_elapsed_ms is not None:
            queue_values.append(queue_elapsed_ms)
        if model_call_elapsed_ms is not None:
            model_values.append(model_call_elapsed_ms)
        if prompt_chars is not None:
            prompt_values.append(prompt_chars)
        if response_chars is not None:
            response_values.append(response_chars)

        parent_path = _target_parent_path(row)
        if parent_path is not None:
            values = parent_values[parent_path]
            if task_elapsed_ms is not None:
                values["task_elapsed_ms"].append(task_elapsed_ms)  # type: ignore[index]
            if queue_elapsed_ms is not None:
                values["queue_elapsed_ms"].append(queue_elapsed_ms)  # type: ignore[index]
            if model_call_elapsed_ms is not None:
                values["model_call_elapsed_ms"].append(model_call_elapsed_ms)  # type: ignore[index]
            if prompt_chars is not None:
                values["prompt_chars"].append(prompt_chars)  # type: ignore[index]
            if response_chars is not None:
                values["response_chars"].append(response_chars)  # type: ignore[index]

        slow_rows.append(
            {
                "review_id": row.get("review_id"),
                "canonical_label": row.get("canonical_label"),
                "target_parent_path": parent_path,
                "status": status,
                "task_elapsed_ms": task_elapsed_ms,
                "queue_elapsed_ms": queue_elapsed_ms,
                "model_call_elapsed_ms": model_call_elapsed_ms,
                "prompt_chars": prompt_chars,
                "response_chars": response_chars,
            }
        )

    target_parents: list[dict[str, object]] = []
    for parent_path, values in parent_values.items():
        task_elapsed = values["task_elapsed_ms"]  # type: ignore[assignment]
        target_parents.append(
            {
                "target_parent_path": parent_path,
                "calls": len(task_elapsed),
                "total_task_elapsed_ms": sum(task_elapsed),
                "task_elapsed_ms": _stats(task_elapsed),
                "queue_elapsed_ms": _stats(values["queue_elapsed_ms"]),  # type: ignore[arg-type]
                "model_call_elapsed_ms": _stats(values["model_call_elapsed_ms"]),  # type: ignore[arg-type]
                "mean_prompt_chars": _mean(values["prompt_chars"]),  # type: ignore[arg-type]
                "mean_response_chars": _mean(values["response_chars"]),  # type: ignore[arg-type]
            }
        )
    target_parents.sort(
        key=lambda item: (-float(item["total_task_elapsed_ms"]), str(item["target_parent_path"]))
    )
    slow_rows.sort(
        key=lambda item: (-(item["task_elapsed_ms"] or -1.0), str(item["review_id"] or ""))
    )

    return {
        "schema_version": TIMING_REPORT_SCHEMA_VERSION,
        "processed": processed,
        "concurrency": concurrency,
        "wall_elapsed_ms": valid_wall_elapsed_ms,
        "status_counts": dict(sorted(status_counts.items())),
        "task_elapsed_ms": _stats(task_values),
        "queue_elapsed_ms": _stats(queue_values),
        "model_call_elapsed_ms": _stats(model_values),
        "prompt_chars": _stats(prompt_values),
        "response_chars": _stats(response_values),
        "target_parents": target_parents,
        "slow_rows": slow_rows[:20],
    }
