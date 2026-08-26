"""Summarise repeat DS verdicts for genuine knowledge-pool expansions."""

from __future__ import annotations

from collections import Counter
from typing import Mapping, Sequence


Run = tuple[str, tuple[Mapping[str, object], ...]]
Decision = tuple[str, str | None, str | None, str | None]
SCHEMA_VERSION = "knowledge-effective-pool-ablation-analysis-v1"


def _review_id(row: Mapping[str, object], *, run_name: str) -> str:
    value = row.get("review_id")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"run {run_name}: every row needs a non-empty review_id")
    return value.strip()


def _index_rows(rows: Sequence[Mapping[str, object]], *, run_name: str) -> dict[str, Mapping[str, object]]:
    indexed: dict[str, Mapping[str, object]] = {}
    for row in rows:
        review_id = _review_id(row, run_name=run_name)
        if review_id in indexed:
            raise ValueError(f"run {run_name}: duplicate review_id {review_id}")
        indexed[review_id] = row
    return indexed


def _decision(row: Mapping[str, object]) -> Decision:
    status = row.get("status")
    validation = row.get("validation")
    if not isinstance(validation, Mapping):
        validation = {}
    verdict = validation.get("verdict")
    coverage = validation.get("candidate_coverage")
    best_label = validation.get("best_label")
    return (
        str(status) if status is not None else "missing",
        verdict if isinstance(verdict, str) else None,
        coverage if isinstance(coverage, str) else None,
        best_label if isinstance(best_label, str) else None,
    )


def _decision_payload(decision: Decision) -> dict[str, str | None]:
    return {
        "status": decision[0],
        "verdict": decision[1],
        "candidate_coverage": decision[2],
        "best_label": decision[3],
    }


def _run_summary(name: str, rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    statuses: Counter[str] = Counter()
    verdicts: Counter[str] = Counter()
    for row in rows:
        decision = _decision(row)
        statuses[decision[0]] += 1
        verdicts[decision[1] if decision[1] is not None else "null"] += 1
    return {
        "name": name,
        "rows": len(rows),
        "status_counts": dict(sorted(statuses.items())),
        "verdict_counts": dict(sorted(verdicts.items())),
    }


def _validate_runs(runs: Sequence[Run], *, group: str) -> tuple[dict[str, Mapping[str, object]], ...]:
    if len(runs) != 3:
        raise ValueError(f"{group} requires exactly three runs")
    names = [name for name, _ in runs]
    if len(set(names)) != len(names):
        raise ValueError(f"{group} contains duplicate run names")
    indexes = tuple(_index_rows(rows, run_name=name) for name, rows in runs)
    expected_ids = set(indexes[0])
    for name, index in zip(names[1:], indexes[1:]):
        if set(index) != expected_ids:
            raise ValueError(f"{group} run {name} does not contain the same review_ids")
    return indexes


def _agreement(
    indexes: Sequence[Mapping[str, Mapping[str, object]]], review_ids: Sequence[str]
) -> tuple[float | None, list[str]]:
    if not review_ids:
        return None, []
    disagreements: list[str] = []
    for review_id in review_ids:
        decisions = {_decision(index[review_id]) for index in indexes}
        if len(decisions) != 1:
            disagreements.append(review_id)
    return (len(review_ids) - len(disagreements)) / len(review_ids), disagreements


def summarize_effective_pool_ablation(
    baseline_runs: Sequence[Run],
    candidate_runs: Sequence[Run],
    *,
    new_labels_by_review_id: Mapping[str, tuple[str, ...]],
) -> dict[str, object]:
    """Summarise stability and v0.2 effects; correctness remains an external review task."""
    baseline_indexes = _validate_runs(baseline_runs, group="baseline")
    candidate_indexes = _validate_runs(candidate_runs, group="candidate")
    baseline_ids = set(baseline_indexes[0])
    candidate_ids = set(candidate_indexes[0])
    if baseline_ids != candidate_ids:
        raise ValueError("baseline and candidate runs do not contain the same review_ids")
    if set(new_labels_by_review_id) != baseline_ids:
        raise ValueError("coverage effective review_ids do not match the six validation runs")
    if any(not labels for labels in new_labels_by_review_id.values()):
        raise ValueError("every coverage review_id must have at least one newly available label")

    review_ids = list(baseline_indexes[0])
    baseline_agreement, baseline_disagreements = _agreement(baseline_indexes, review_ids)
    candidate_agreement, candidate_disagreements = _agreement(candidate_indexes, review_ids)
    cross_mode_disagreements: list[str] = []
    consistently_selects_new_label: list[str] = []
    review_rows: list[dict[str, object]] = []
    for review_id in review_ids:
        baseline_decisions = tuple(_decision(index[review_id]) for index in baseline_indexes)
        candidate_decisions = tuple(_decision(index[review_id]) for index in candidate_indexes)
        baseline_unanimous = len(set(baseline_decisions)) == 1
        candidate_unanimous = len(set(candidate_decisions)) == 1
        if baseline_unanimous and candidate_unanimous and baseline_decisions[0] != candidate_decisions[0]:
            cross_mode_disagreements.append(review_id)
        candidate_decision = candidate_decisions[0] if candidate_unanimous else None
        if (
            candidate_decision is not None
            and candidate_decision[1] == "replace"
            and candidate_decision[3] in set(new_labels_by_review_id[review_id])
        ):
            consistently_selects_new_label.append(review_id)
        review_rows.append(
            {
                "review_id": review_id,
                "newly_available_alternative_labels": list(new_labels_by_review_id[review_id]),
                "baseline_decisions": [_decision_payload(decision) for decision in baseline_decisions],
                "candidate_decisions": [_decision_payload(decision) for decision in candidate_decisions],
                "baseline_unanimous": baseline_unanimous,
                "candidate_unanimous": candidate_unanimous,
                "correctness_status": "requires_human_review",
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "baseline": {
            "runs": [_run_summary(name, rows) for name, rows in baseline_runs],
            "common_review_ids": len(review_ids),
            "all_three_decision_agreement": baseline_agreement,
            "decision_disagreement_review_ids": baseline_disagreements,
        },
        "candidate": {
            "runs": [_run_summary(name, rows) for name, rows in candidate_runs],
            "common_review_ids": len(review_ids),
            "all_three_decision_agreement": candidate_agreement,
            "decision_disagreement_review_ids": candidate_disagreements,
        },
        "comparison": {
            "common_review_ids_all_six": len(review_ids),
            "unanimous_decision_disagreements": len(cross_mode_disagreements),
            "unanimous_decision_disagreement_review_ids": cross_mode_disagreements,
            "candidate_consistently_selects_new_label": len(consistently_selects_new_label),
            "candidate_consistently_selects_new_label_review_ids": consistently_selects_new_label,
        },
        "review_rows": review_rows,
    }
