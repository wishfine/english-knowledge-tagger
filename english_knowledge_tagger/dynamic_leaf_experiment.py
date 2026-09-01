"""Prepare and analyze dynamic-leaf correction experiments without releasing patches."""

from __future__ import annotations

from collections import Counter
from statistics import fmean
from typing import Mapping, Sequence

from .candidate_route_guidance import CandidateRouteGuidance
from .knowledge_rulebook import KnowledgeRulebook
from .terminal_label_stability import PACKET_SCHEMA_VERSION


SCHEMA_VERSION = "dynamic-leaf-task-v1"
ANALYSIS_SCHEMA_VERSION = "dynamic-leaf-experiment-analysis-v1"


def _id(row: Mapping[str, object], *, field: str, origin: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{origin}: {field} must be non-empty")
    return value.strip()


def _index(rows: Sequence[Mapping[str, object]], *, field: str, origin: str):
    indexed = {}
    for row in rows:
        identity = _id(row, field=field, origin=origin)
        if identity in indexed:
            raise ValueError(f"{origin}: duplicate {field} {identity}")
        indexed[identity] = row
    return indexed


def _confusion_profiles(
    ambiguity_manifest: Mapping[str, object],
) -> dict[str, dict[str, int]]:
    rows = ambiguity_manifest.get("labels")
    if not isinstance(rows, list):
        raise ValueError("ambiguity manifest labels must be a list")
    profiles = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("ambiguity label row must be an object")
        label = _id(row, field="canonical_label", origin="ambiguity label")
        raw_neighbors = row.get("confusion_neighbors")
        if not isinstance(raw_neighbors, list):
            raise ValueError("ambiguity confusion_neighbors must be a list")
        neighbors = {}
        for item in raw_neighbors:
            if not isinstance(item, Mapping):
                raise ValueError("ambiguity confusion neighbor must be an object")
            candidate = _id(item, field="canonical_label", origin="ambiguity neighbor")
            count = item.get("count")
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise ValueError("ambiguity neighbor count must be a non-negative integer")
            neighbors[candidate] = count
        profiles[label] = neighbors
    return profiles


def build_dynamic_leaf_tasks(
    packet_rows: Sequence[Mapping[str, object]],
    *,
    direct_runs: Sequence[tuple[str, Sequence[Mapping[str, object]]]],
    ambiguity_manifest: Mapping[str, object],
    selected_variant_by_label: Mapping[str, str],
    teacher_gold_by_question: Mapping[str, Sequence[str]] | None = None,
    route_guidance: CandidateRouteGuidance | None = None,
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...], dict[str, object]]:
    """Select only records with three identical non-target direct decisions."""
    if len(direct_runs) != 3:
        raise ValueError("dynamic leaf task builder requires exactly three direct runs")
    run_indexes = tuple(
        _index(rows, field="review_id", origin=f"direct run {name}")
        for name, rows in direct_runs
    )
    profiles = _confusion_profiles(ambiguity_manifest)
    selected_rows = []
    seen_questions = set()
    for row in packet_rows:
        label = row.get("canonical_label")
        if not isinstance(label, str):
            continue
        if row.get("definition_variant") != selected_variant_by_label.get(label):
            continue
        question_id = _id(row, field="question_id", origin="stability packet")
        if question_id in seen_questions:
            raise ValueError("selected stability packet contains duplicate question_id")
        seen_questions.add(question_id)
        selected_rows.append(row)
    tasks = []
    holds = []
    reason_counts = Counter()
    for row in selected_rows:
        review_id = _id(row, field="review_id", origin="stability packet")
        missing = [index for index in run_indexes if review_id not in index]
        if missing:
            raise ValueError(f"direct run is missing review_id {review_id}")
        decisions = tuple(index[review_id].get("decision") for index in run_indexes)
        question_id = _id(row, field="question_id", origin="stability packet")
        if decisions != ("non_target", "non_target", "non_target"):
            reason = "direct_not_unanimous_non_target"
            reason_counts[reason] += 1
            holds.append(
                {
                    "question_id": question_id,
                    "canonical_label": row.get("canonical_label"),
                    "status": "hold",
                    "reason": reason,
                    "direct_decisions": list(decisions),
                }
            )
            continue
        canonical = str(row["canonical_label"])
        gold_labels = list((teacher_gold_by_question or {}).get(question_id, ()))
        soft_route_compatible: list[str] = []
        hard_excluded: list[str] = []
        if route_guidance is not None:
            route_key = row.get("route_key")
            route_text = None
            if isinstance(route_key, Mapping):
                values = tuple(
                    route_key.get(key)
                    for key in ("scope", "declared_type_structure", "declared_type_name")
                )
                if all(isinstance(value, str) and value.strip() for value in values):
                    route_text = " × ".join(str(value).strip() for value in values)
            for guidance in route_guidance.labels.values():
                if guidance.mode != "hard_exclusive":
                    continue
                if route_text is not None and route_text in guidance.allowed_routes:
                    soft_route_compatible.append(guidance.canonical_label)
                else:
                    hard_excluded.append(guidance.canonical_label)
        tasks.append(
            {
                "schema_version": SCHEMA_VERSION,
                "review_id": f"dynamic-leaf:{canonical}:{question_id}",
                "question_id": question_id,
                "parent_id": row.get("parent_id"),
                "historical_label": canonical,
                "legacy_label": row.get("legacy_label"),
                "question_text": row.get("question_text"),
                "route_key": row.get("route_key"),
                "pseudo_gold_decision": row.get("pseudo_gold_decision"),
                "teacher_gold_labels": gold_labels,
                "confusion_counts": profiles.get(canonical, {}),
                "soft_route_compatible": sorted(set(soft_route_compatible)),
                "hard_excluded": sorted(set(hard_excluded)),
                "definition_variant": row.get("definition_variant"),
                "release_eligible": row.get("pseudo_gold_decision") == "remove",
            }
        )
    report = {
        "schema_version": "dynamic-leaf-task-report-v1",
        "selected_stability_records": len(selected_rows),
        "eligible_tasks": len(tasks),
        "hold_records": len(holds),
        "hold_reason_counts": dict(sorted(reason_counts.items())),
    }
    return tuple(tasks), tuple(holds), report


def build_dynamic_candidate_verifier_packet(
    tasks: Sequence[Mapping[str, object]],
    *,
    resolver_runs: Sequence[tuple[str, Sequence[Mapping[str, object]]]],
    rulebook: KnowledgeRulebook,
) -> tuple[dict[str, object], ...]:
    """Build one candidate-verification row only for unanimous resolver outputs."""
    task_index = _index(tasks, field="review_id", origin="dynamic tasks")
    resolvers = _run_indexes(
        resolver_runs,
        field="review_id",
        expected_ids=set(task_index),
        kind="resolver",
    )
    packet = []
    for source_review_id, task in sorted(task_index.items()):
        outcomes = tuple(
            (index[source_review_id].get("status"), index[source_review_id].get("candidate_label"))
            for index in resolvers
        )
        if len(set(outcomes)) != 1 or outcomes[0][0] != "candidate":
            continue
        candidate = outcomes[0][1]
        if not isinstance(candidate, str):
            continue
        record = rulebook.records.get(candidate)
        if record is None or record.status != "active":
            raise ValueError(f"resolver candidate is not an active teacher label: {candidate}")
        question_id = _id(task, field="question_id", origin="dynamic task")
        packet.append(
            {
                "schema_version": PACKET_SCHEMA_VERSION,
                "review_id": f"dynamic-candidate-verifier:{candidate}:{question_id}",
                "source_review_id": source_review_id,
                "question_id": question_id,
                "parent_id": task.get("parent_id"),
                "source_line": task.get("source_line", 1),
                "legacy_label": candidate.replace("->", "@"),
                "canonical_label": candidate,
                "definition_variant": "dynamic_candidate",
                "definition_text": record.alternative_definition,
                "question_text": task.get("question_text"),
                "route_key": task.get("route_key"),
                "pseudo_gold_decision": task.get("pseudo_gold_decision", "remove"),
                "split": "dynamic_verification",
                "split_seed": "dynamic-leaf-v1",
            }
        )
    return tuple(packet)


def _run_indexes(
    runs: Sequence[tuple[str, Sequence[Mapping[str, object]]]],
    *,
    field: str,
    expected_ids: set[str],
    kind: str,
):
    if len(runs) != 3:
        raise ValueError(f"{kind} requires exactly three runs")
    indexes = tuple(
        _index(rows, field=field, origin=f"{kind} run {name}") for name, rows in runs
    )
    for (name, _), index in zip(runs, indexes):
        if set(index) != expected_ids:
            raise ValueError(f"{kind} run {name} identity set does not match tasks")
    return indexes


def summarize_dynamic_leaf_experiment(
    tasks: Sequence[Mapping[str, object]],
    *,
    resolver_runs: Sequence[tuple[str, Sequence[Mapping[str, object]]]],
    verifier_runs: Sequence[tuple[str, Sequence[Mapping[str, object]]]],
    root_baseline_mean_calls: float | None = None,
) -> dict[str, object]:
    """Apply the unanimous resolver + unanimous high-keep non-releasing gate."""
    task_index = _index(tasks, field="review_id", origin="dynamic tasks")
    expected = set(task_index)
    resolvers = _run_indexes(
        resolver_runs,
        field="review_id",
        expected_ids=expected,
        kind="resolver",
    )
    unanimous_candidate_ids = {
        review_id
        for review_id in expected
        if len(
            {
                (
                    index[review_id].get("status"),
                    index[review_id].get("candidate_label"),
                )
                for index in resolvers
            }
        )
        == 1
        and resolvers[0][review_id].get("status") == "candidate"
        and isinstance(resolvers[0][review_id].get("candidate_label"), str)
    }
    verifiers = _run_indexes(
        verifier_runs,
        field="source_review_id",
        expected_ids=unanimous_candidate_ids,
        kind="verifier",
    )
    decisions = []
    agreement_count = 0
    unanimous_candidates = 0
    gold_evaluable = 0
    gold_correct = 0
    verified_candidates = 0
    verified_correct = 0
    forced_uncertain = 0
    calls = []
    for review_id, task in task_index.items():
        outcomes = tuple(
            (row.get("status"), row.get("candidate_label"))
            for row in (index[review_id] for index in resolvers)
        )
        resolver_unanimous = len(set(outcomes)) == 1
        if resolver_unanimous:
            agreement_count += 1
        candidate = (
            str(outcomes[0][1])
            if resolver_unanimous
            and outcomes[0][0] == "candidate"
            and isinstance(outcomes[0][1], str)
            else None
        )
        if candidate is not None:
            unanimous_candidates += 1
            if task.get("pseudo_gold_decision") == "uncertain":
                forced_uncertain += 1
        verifier_outcomes = (
            tuple(
                (row.get("decision"), row.get("confidence"))
                for row in (index[review_id] for index in verifiers)
            )
            if review_id in unanimous_candidate_ids
            else ()
        )
        verifier_high_keep = verifier_outcomes == (
            ("keep", "high"),
            ("keep", "high"),
            ("keep", "high"),
        )
        raw_gold = task.get("teacher_gold_labels")
        teacher_gold = set(raw_gold) if isinstance(raw_gold, list) else set()
        teacher_gold_match = None
        if candidate is not None and teacher_gold:
            gold_evaluable += 1
            teacher_gold_match = candidate in teacher_gold
            if teacher_gold_match:
                gold_correct += 1
        if candidate is not None and verifier_high_keep:
            verified_candidates += 1
            if not teacher_gold or teacher_gold_match is True:
                verified_correct += 1
        release_eligible = task.get("pseudo_gold_decision") != "uncertain"
        disposition = (
            "stable_relabel_candidate"
            if candidate is not None
            and verifier_high_keep
            and release_eligible
            and (teacher_gold_match is not False)
            else "hold"
        )
        for index in resolvers:
            value = index[review_id].get("call_count")
            if isinstance(value, (int, float)):
                calls.append(float(value))
        decisions.append(
            {
                "review_id": review_id,
                "question_id": task.get("question_id"),
                "candidate_label": candidate,
                "resolver_unanimous": resolver_unanimous,
                "verifier_unanimous_high_keep": verifier_high_keep,
                "teacher_gold_match": teacher_gold_match,
                "disposition": disposition,
            }
        )
    mean_calls = fmean(calls) if calls else None
    call_reduction = (
        1 - mean_calls / root_baseline_mean_calls
        if mean_calls is not None
        and root_baseline_mean_calls is not None
        and root_baseline_mean_calls > 0
        else None
    )
    teacher_gold_accuracy = gold_correct / gold_evaluable if gold_evaluable else None
    verifier_precision = (
        verified_correct / verified_candidates if verified_candidates else None
    )
    metrics = {
        "tasks": len(task_index),
        "three_run_candidate_agreement": (
            agreement_count / len(task_index) if task_index else None
        ),
        "unanimous_candidates": unanimous_candidates,
        "teacher_gold_evaluable_candidates": gold_evaluable,
        "unanimous_candidate_precision": verifier_precision,
        "teacher_gold_candidate_accuracy": teacher_gold_accuracy,
        "verifier_high_keep_candidates": verified_candidates,
        "forced_candidate_on_uncertain": forced_uncertain,
        "mean_dynamic_calls": mean_calls,
        "root_baseline_mean_calls": root_baseline_mean_calls,
        "mean_call_reduction": call_reduction,
    }
    metrics["passes_dynamic_gate"] = bool(
        metrics["three_run_candidate_agreement"] is not None
        and metrics["three_run_candidate_agreement"] >= 0.90
        and verifier_precision is not None
        and verifier_precision >= 0.95
        and (teacher_gold_accuracy is None or teacher_gold_accuracy >= 0.95)
        and forced_uncertain / len(task_index) <= 0.01
        and call_reduction is not None
        and call_reduction >= 0.30
    )
    return {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "metrics": metrics,
        "decisions": decisions,
    }
