"""Build a small, deterministic Web-GPT audit set for conversion relations."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from typing import Mapping


_RELATIONS = ("conversion", "derivation", "inflection", "lexical_or_other", "insufficient")
_SCHEMA_VERSION = "conversion-relation-web-review-v1"


def _rank(seed: str, value: str) -> str:
    return hashlib.sha256(f"{seed}\0{value}".encode("utf-8")).hexdigest()


def _load(path: Path, *, source: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{source} line {line_number}: invalid JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"{source} line {line_number}: row must be an object")
            rows.append(row)
    return rows


def _text(value: object, *, field: str, origin: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{origin}: {field} must be non-empty string")
    return value.strip()


def _route_name(value: object, *, origin: str) -> str:
    if not isinstance(value, Mapping):
        raise ValueError(f"{origin}: route_key must be object")
    return " × ".join(_text(value.get(key), field=f"route_key.{key}", origin=origin) for key in ("scope", "declared_type_structure", "declared_type_name"))


def _round_robin(rows: list[dict[str, object]], *, quota: int, seed: str, relation: str) -> list[dict[str, object]]:
    """Sample across routes before taking a second row from any one route."""
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        groups[str(row["route_name"])].append(row)
    queues = [
        sorted(group, key=lambda item: _rank(seed, f"{relation}:{item['question_id']}"))
        for _, group in sorted(groups.items(), key=lambda item: _rank(seed, f"route:{relation}:{item[0]}"))
    ]
    selected: list[dict[str, object]] = []
    while len(selected) < quota:
        progressed = False
        for queue in queues:
            if queue:
                selected.append(queue.pop(0))
                progressed = True
                if len(selected) == quota:
                    break
        if not progressed:
            break
    return selected


def build_conversion_relation_review_packet(
    packet_path: Path,
    evidence_path: Path,
    *,
    output_path: Path,
    non_conversion_quota: int = 12,
    seed: str,
) -> dict[str, object]:
    """Select all predicted conversions plus route-stratified counterexamples.

    The result contains model relation evidence but deliberately excludes the
    historical conversion label and the mentor direct-verifier verdict.
    """
    if output_path.exists():
        raise FileExistsError(f"review packet already exists: {output_path}")
    if non_conversion_quota < 1:
        raise ValueError("non_conversion_quota must be positive")
    packet_rows = _load(packet_path, source="packet")
    evidence_rows = _load(evidence_path, source="evidence")
    packets = {_text(row.get("task_id"), field="task_id", origin="packet"): row for row in packet_rows}
    if len(packets) != len(packet_rows):
        raise ValueError("packet: duplicate task_id")

    candidates: dict[str, list[dict[str, object]]] = {relation: [] for relation in _RELATIONS}
    for position, evidence in enumerate(evidence_rows, 1):
        origin = f"evidence row {position}"
        task_id = _text(evidence.get("task_id"), field="task_id", origin=origin)
        task = packets.get(task_id)
        if task is None:
            raise ValueError(f"{origin}: task_id absent from packet")
        relation = _text(evidence.get("relation"), field="relation", origin=origin)
        if relation not in candidates:
            raise ValueError(f"{origin}: unsupported relation {relation!r}")
        question_id = _text(task.get("question_id"), field="question_id", origin=f"packet {task_id}")
        candidates[relation].append({
            "question_id": question_id,
            "parent_id": _text(task.get("parent_id"), field="parent_id", origin=f"packet {task_id}"),
            "route_key": task.get("route_key"),
            "route_name": _route_name(task.get("route_key"), origin=f"packet {task_id}"),
            "question_context": _text(task.get("question_context"), field="question_context", origin=f"packet {task_id}"),
            "model_relation": relation,
            "model_confidence": _text(evidence.get("confidence"), field="confidence", origin=origin),
            "model_evidence": _text(evidence.get("evidence"), field="evidence", origin=origin),
        })
    if sum(map(len, candidates.values())) != len(evidence_rows):
        raise ValueError("evidence: duplicate relation rows or missing records")

    selected: list[dict[str, object]] = sorted(candidates["conversion"], key=lambda item: _rank(seed, f"conversion:{item['question_id']}"))
    for relation in _RELATIONS[1:]:
        selected.extend(_round_robin(candidates[relation], quota=non_conversion_quota, seed=seed, relation=relation))
    selected_by_relation = Counter(str(row["model_relation"]) for row in selected)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as output:
        for index, row in enumerate(selected, 1):
            review_id = f"conversion-relation-review:{row['question_id']}:{row['model_relation']}"
            review = {
                "schema_version": _SCHEMA_VERSION,
                "review_id": review_id,
                "question_id": row["question_id"],
                "parent_id": row["parent_id"],
                "route_key": row["route_key"],
                "question_context": row["question_context"],
                "model_relation": row["model_relation"],
                "model_confidence": row["model_confidence"],
                "model_evidence": row["model_evidence"],
                "review_instruction": "仅判断 model_relation 是否与题目实际词形关系一致；输出 correct / incorrect / hold，并说明源词、目标词和关系。",
            }
            output.write(json.dumps(review, ensure_ascii=False, sort_keys=True) + "\n")
    return {
        "schema_version": "conversion-relation-web-review-report-v1",
        "packet_path": str(packet_path),
        "evidence_path": str(evidence_path),
        "output_path": str(output_path),
        "non_conversion_quota": non_conversion_quota,
        "selected_records": len(selected),
        "selected_by_relation": dict(sorted(selected_by_relation.items())),
        "source_by_relation": {relation: len(candidates[relation]) for relation in _RELATIONS},
        "seed": seed,
    }
