"""Create and execute auditable single-candidate knowledge-tree tasks."""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import time
from typing import Any, Mapping, Protocol

from .knowledge_candidate_policy import KnowledgeCandidatePolicy
from .knowledge_tree_search import TreeChoice, TreeChoiceRequest, search_one_candidate
from .knowledge_taxonomy_tree import KnowledgeTaxonomyTree
from .knowledge_validation_packet import _model_question_context, _selected_routes
from .sft_labels import parse_sft_output_labels


TASK_SCHEMA_VERSION = "knowledge-tree-task-v1"
RESULT_SCHEMA_VERSION = "knowledge-tree-result-v1"
_TREE_POLICIES = frozenset({"required", "optional"})


class TreeChoiceClient(Protocol):
    def choose(self, request: TreeChoiceRequest) -> TreeChoice: ...


def _identifier(value: object, *, field: str, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: {field} must be a non-empty string")
    return value.strip()


def _source_line(value: object, *, source: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{source}: source_line must be a positive integer")
    return value


def _legacy_knowledge_labels(record: Mapping[str, Any]) -> tuple[str, ...]:
    parsed = parse_sft_output_labels(record.get("output"))
    return parsed[0] if parsed is not None else ()


def _route_key_payload(route: tuple[str, str, str]) -> dict[str, str]:
    return {
        "scope": route[0],
        "declared_type_structure": route[1],
        "declared_type_name": route[2],
    }


def _packet_source_lines(path: Path) -> dict[str, int]:
    review_ids: dict[str, int] = {}
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"validation packet line {line_number} is not valid JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"validation packet line {line_number} must be an object")
            review_id = _identifier(
                row.get("review_id"), field="review_id", source=f"validation packet line {line_number}"
            )
            source_line = _source_line(
                row.get("source_line"), source=f"validation packet line {line_number}"
            )
            if review_id in review_ids and review_ids[review_id] != source_line:
                raise ValueError(f"validation packet has conflicting source_line for review_id {review_id}")
            review_ids[review_id] = source_line
    return review_ids


def _verdict_triggers(
    path: Path, *, packet_source_lines: Mapping[str, int]
) -> tuple[dict[int, list[dict[str, object]]], Counter[str]]:
    triggers: defaultdict[int, list[dict[str, object]]] = defaultdict(list)
    counts: Counter[str] = Counter()
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"validation verdict line {line_number} is not valid JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"validation verdict line {line_number} must be an object")
            review_id = _identifier(
                row.get("review_id"), field="review_id", source=f"validation verdict line {line_number}"
            )
            if review_id not in packet_source_lines:
                raise ValueError(f"validation verdict review_id is absent from validation packet: {review_id}")
            source_line = _source_line(
                row.get("source_line"), source=f"validation verdict line {line_number}"
            )
            if source_line != packet_source_lines[review_id]:
                raise ValueError(f"validation verdict source_line differs from packet for review_id {review_id}")
            if row.get("status") != "candidate":
                continue
            validation = row.get("validation")
            if not isinstance(validation, dict):
                raise ValueError(f"validation verdict line {line_number} candidate row needs validation object")
            verdict = validation.get("verdict")
            coverage = validation.get("candidate_coverage")
            if verdict == "replace":
                triggers[source_line].append(
                    {
                        "kind": "replace",
                        "review_id": review_id,
                        "flat_best_label": validation.get("best_label"),
                    }
                )
                counts["replace_triggers"] += 1
            elif verdict == "uncertain" and coverage == "insufficient":
                triggers[source_line].append(
                    {
                        "kind": "uncertain_insufficient",
                        "review_id": review_id,
                        "flat_best_label": validation.get("best_label"),
                    }
                )
                counts["uncertain_insufficient_triggers"] += 1
    return dict(triggers), counts


def build_knowledge_tree_tasks(
    source_path: Path,
    *,
    review_packet_path: Path,
    validation_packet_path: Path,
    validation_verdict_path: Path,
    candidate_policy: KnowledgeCandidatePolicy,
    output_path: Path,
) -> dict[str, object]:
    """Build one tree task per selected source record without mutating source data."""
    if output_path.exists():
        raise FileExistsError(f"knowledge tree task output already exists: {output_path}")
    selected_routes = _selected_routes(review_packet_path)
    packet_source_lines = _packet_source_lines(validation_packet_path)
    triggers_by_line, counts = _verdict_triggers(
        validation_verdict_path, packet_source_lines=packet_source_lines
    )
    rows: list[dict[str, object]] = []
    found_lines: set[int] = set()
    with source_path.open("r", encoding="utf-8") as source:
        for source_line, line in enumerate(source, 1):
            if source_line not in selected_routes:
                continue
            found_lines.add(source_line)
            if not line.strip():
                counts["selected_blank_lines"] += 1
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                counts["selected_invalid_json_lines"] += 1
                continue
            if not isinstance(record, dict):
                counts["selected_non_object_records"] += 1
                continue
            route = selected_routes[source_line]
            rule = candidate_policy.match(*route) if route is not None else None
            if rule is None or rule.knowledge_policy not in _TREE_POLICIES:
                counts["selected_non_tree_policy_records"] += 1
                continue
            triggers = list(triggers_by_line.get(source_line, ()))
            if rule.knowledge_policy == "required" and not _legacy_knowledge_labels(record):
                triggers.append({"kind": "add_missing_required"})
                counts["add_missing_required_triggers"] += 1
            if not triggers:
                continue
            question_context = _model_question_context(record)
            if not question_context:
                counts["selected_records_without_question_context"] += 1
                continue
            question_id = record.get("question_id")
            task_identifier = question_id.strip() if isinstance(question_id, str) and question_id.strip() else str(source_line)
            ordered_triggers = sorted(
                triggers, key=lambda item: (str(item["kind"]), str(item.get("review_id", "")))
            )
            rows.append(
                {
                    "schema_version": TASK_SCHEMA_VERSION,
                    "task_id": f"kp-tree:{task_identifier}",
                    "source_line": source_line,
                    "question_id": question_id.strip() if isinstance(question_id, str) and question_id.strip() else None,
                    "parent_id": record.get("parent_id") if isinstance(record.get("parent_id"), str) else None,
                    "is_sub_question": record.get("is_sub_question"),
                    "route_key": _route_key_payload(route),
                    "knowledge_policy": rule.knowledge_policy,
                    "allowed_knowledge_prefixes": list(rule.allowed_knowledge_prefixes),
                    "max_output_labels": rule.max_output_labels,
                    "question_context": question_context,
                    "trigger_kinds": sorted({str(trigger["kind"]) for trigger in ordered_triggers}),
                    "triggers": ordered_triggers,
                }
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {
        "schema_version": "knowledge-tree-task-report-v1",
        "source_path": str(source_path),
        "review_packet_path": str(review_packet_path),
        "validation_packet_path": str(validation_packet_path),
        "validation_verdict_path": str(validation_verdict_path),
        "output_path": str(output_path),
        "selected_source_lines": len(selected_routes),
        "found_selected_source_lines": len(found_lines),
        "missing_selected_source_lines": len(set(selected_routes) - found_lines),
        "tasks": len(rows),
        "replace_triggers": counts["replace_triggers"],
        "uncertain_insufficient_triggers": counts["uncertain_insufficient_triggers"],
        "add_missing_required_triggers": counts["add_missing_required_triggers"],
        "selected_non_tree_policy_records": counts["selected_non_tree_policy_records"],
    }


def route_knowledge_tree_task(
    task: Mapping[str, object],
    *,
    client: TreeChoiceClient,
    tree: KnowledgeTaxonomyTree,
    max_steps: int = 8,
    max_backtracks: int = 2,
) -> dict[str, object]:
    """Route one task and retain every decision; callers handle HTTP errors separately."""
    task_id = _identifier(task.get("task_id"), field="task_id", source="knowledge tree task")
    question_context = _identifier(
        task.get("question_context"), field="question_context", source="knowledge tree task"
    )
    raw_prefixes = task.get("allowed_knowledge_prefixes")
    if not isinstance(raw_prefixes, list) or not raw_prefixes:
        raise ValueError("knowledge tree task: allowed_knowledge_prefixes must be a non-empty list")
    prefixes = tuple(
        _identifier(prefix, field="allowed_knowledge_prefixes", source="knowledge tree task")
        for prefix in raw_prefixes
    )
    task_started_ns = time.perf_counter_ns()
    result = search_one_candidate(
        tree,
        question_context=question_context,
        allowed_prefixes=prefixes,
        choose=client.choose,
        max_steps=max_steps,
        max_backtracks=max_backtracks,
    )
    task_elapsed_ms = (time.perf_counter_ns() - task_started_ns) / 1_000_000
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "task_id": task_id,
        "source_line": task.get("source_line"),
        "question_id": task.get("question_id"),
        "parent_id": task.get("parent_id"),
        "is_sub_question": task.get("is_sub_question"),
        "route_key": task.get("route_key"),
        "knowledge_policy": task.get("knowledge_policy"),
        "allowed_knowledge_prefixes": list(prefixes),
        "trigger_kinds": task.get("trigger_kinds"),
        "triggers": task.get("triggers"),
        "status": result.status,
        "candidate_label": result.candidate_label,
        "trace": list(result.trace),
        "max_steps": max_steps,
        "max_backtracks": max_backtracks,
        "task_elapsed_ms": task_elapsed_ms,
    }
