"""Summarise bounded knowledge-tree routing latency without retaining question text."""

from __future__ import annotations

from collections import Counter, defaultdict
from math import ceil, isfinite
from statistics import fmean
from typing import Iterable, Mapping

from .knowledge_taxonomy_tree import NO_MATCH


TIMING_REPORT_SCHEMA_VERSION = "knowledge-tree-timing-report-v1"


def _number(value: object) -> float | None:
    """Return finite numeric measurements while rejecting bools and malformed data."""
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


def summarize_tree_timing(
    rows: Iterable[Mapping[str, object]], *, wall_elapsed_ms: float, concurrency: int
) -> dict[str, object]:
    """Aggregate latency by task and decision node from completed JSONL result rows.

    The result deliberately omits question text, answers, raw completions, and evidence.
    It can therefore be retained next to a run manifest without duplicating sensitive data.
    """
    if concurrency <= 0:
        raise ValueError("concurrency must be positive")
    valid_wall_elapsed_ms = _number(wall_elapsed_ms)
    if valid_wall_elapsed_ms is None:
        raise ValueError("wall_elapsed_ms must be a finite non-negative number")

    task_values: list[float] = []
    queue_values: list[float] = []
    choice_values: list[float] = []
    model_values: list[float] = []
    status_counts: Counter[str] = Counter()
    node_values: defaultdict[str, dict[str, object]] = defaultdict(
        lambda: {
            "choice_elapsed_ms": [],
            "model_call_elapsed_ms": [],
            "candidate_counts": [],
            "prompt_chars": [],
            "no_match_calls": 0,
        }
    )
    slow_tasks: list[dict[str, object]] = []
    processed = 0

    for row in rows:
        processed += 1
        status_counts[str(row.get("status", "missing"))] += 1
        task_elapsed_ms = _number(row.get("task_elapsed_ms"))
        queue_elapsed_ms = _number(row.get("queue_elapsed_ms"))
        if task_elapsed_ms is not None:
            task_values.append(task_elapsed_ms)
        if queue_elapsed_ms is not None:
            queue_values.append(queue_elapsed_ms)

        trace_steps = 0
        choice_total = 0.0
        no_match_steps = 0
        raw_trace = row.get("trace")
        if isinstance(raw_trace, list):
            for step in raw_trace:
                if not isinstance(step, Mapping):
                    continue
                trace_steps += 1
                parent_path = step.get("parent_path")
                if not isinstance(parent_path, str) or not parent_path:
                    continue
                node = node_values[parent_path]
                choice_elapsed_ms = _number(step.get("choice_elapsed_ms"))
                if choice_elapsed_ms is not None:
                    choice_values.append(choice_elapsed_ms)
                    node["choice_elapsed_ms"].append(choice_elapsed_ms)  # type: ignore[index]
                    choice_total += choice_elapsed_ms
                model_call_elapsed_ms = _number(step.get("model_call_elapsed_ms"))
                if model_call_elapsed_ms is not None:
                    model_values.append(model_call_elapsed_ms)
                    node["model_call_elapsed_ms"].append(model_call_elapsed_ms)  # type: ignore[index]
                candidate_count = _number(step.get("candidate_count"))
                if candidate_count is not None:
                    node["candidate_counts"].append(candidate_count)  # type: ignore[index]
                prompt_chars = _number(step.get("prompt_chars"))
                if prompt_chars is not None:
                    node["prompt_chars"].append(prompt_chars)  # type: ignore[index]
                if step.get("choice") == NO_MATCH:
                    node["no_match_calls"] += 1  # type: ignore[operator]
                    no_match_steps += 1

        slow_tasks.append(
            {
                "task_id": row.get("task_id"),
                "status": row.get("status"),
                "task_elapsed_ms": task_elapsed_ms,
                "queue_elapsed_ms": queue_elapsed_ms,
                "trace_steps": trace_steps,
                "choice_elapsed_ms_total": choice_total,
                "no_match_steps": no_match_steps,
            }
        )

    nodes: list[dict[str, object]] = []
    for parent_path, values in node_values.items():
        choice_elapsed = values["choice_elapsed_ms"]  # type: ignore[assignment]
        nodes.append(
            {
                "parent_path": parent_path,
                "calls": len(choice_elapsed),
                "total_choice_elapsed_ms": sum(choice_elapsed),
                "choice_elapsed_ms": _stats(choice_elapsed),
                "model_call_elapsed_ms": _stats(values["model_call_elapsed_ms"]),  # type: ignore[arg-type]
                "mean_candidate_count": _mean(values["candidate_counts"]),  # type: ignore[arg-type]
                "mean_prompt_chars": _mean(values["prompt_chars"]),  # type: ignore[arg-type]
                "no_match_calls": values["no_match_calls"],
            }
        )
    nodes.sort(key=lambda item: (-float(item["total_choice_elapsed_ms"]), str(item["parent_path"])))
    slow_tasks.sort(
        key=lambda item: (-(item["task_elapsed_ms"] or -1.0), str(item["task_id"] or ""))
    )

    return {
        "schema_version": TIMING_REPORT_SCHEMA_VERSION,
        "processed": processed,
        "concurrency": concurrency,
        "wall_elapsed_ms": valid_wall_elapsed_ms,
        "status_counts": dict(sorted(status_counts.items())),
        "task_elapsed_ms": _stats(task_values),
        "queue_elapsed_ms": _stats(queue_values),
        "choice_elapsed_ms": _stats(choice_values),
        "model_call_elapsed_ms": _stats(model_values),
        "nodes": nodes,
        "slow_tasks": slow_tasks[:20],
    }
