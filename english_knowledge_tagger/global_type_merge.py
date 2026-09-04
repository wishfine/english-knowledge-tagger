"""Prepare and materialize label-blind global type-cluster decisions."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


class GlobalTypeMergeError(ValueError):
    """Raised when global merge inputs or decisions violate the data contract."""


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise GlobalTypeMergeError(f"{path}: invalid JSON") from error
    if not isinstance(payload, Mapping):
        raise GlobalTypeMergeError(f"{path}: expected a JSON object")
    return payload


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _decision_paths(stage2_root: Path, progress_path: Path | None) -> list[tuple[int | None, Path]]:
    """Find decision files, using progress only for discovery/provenance."""
    found: list[tuple[int | None, Path]] = []
    seen: set[Path] = set()
    if progress_path and progress_path.exists():
        progress = _read_json(progress_path)
        completed = progress.get("completed_labels", [])
        if not isinstance(completed, list):
            raise GlobalTypeMergeError("progress.completed_labels must be an array")
        for item in completed:
            if not isinstance(item, Mapping):
                continue
            raw_path = item.get("decision_path")
            if not isinstance(raw_path, str) or not raw_path:
                continue
            path = Path(raw_path)
            if not path.is_absolute():
                path = stage2_root / path
            path = path.resolve()
            if not path.exists():
                raise GlobalTypeMergeError(f"progress references missing decision file: {path}")
            if path in seen:
                raise GlobalTypeMergeError(f"duplicate decision path in progress: {path}")
            seen.add(path)
            raw_index = item.get("label_index")
            label_index = int(raw_index) if isinstance(raw_index, int) and not isinstance(raw_index, bool) else None
            found.append((label_index, path))
    if not found:
        for path in sorted(stage2_root.rglob("decisions.json")):
            resolved = path.resolve()
            if resolved not in seen:
                found.append((None, resolved))
    if not found:
        raise GlobalTypeMergeError(f"no decisions.json found under {stage2_root}")
    return found


def build_global_merge_packet(
    stage2_root: Path,
    *,
    progress_path: Path | None = None,
) -> dict[str, Any]:
    """Flatten all candidate local clusters without using source labels for grouping."""
    paths = _decision_paths(stage2_root, progress_path)
    records: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for label_index, decision_path in paths:
        decision = _read_json(decision_path)
        source_label = decision.get("source_type_label")
        if not isinstance(source_label, str) or not source_label:
            raise GlobalTypeMergeError(f"{decision_path}: missing source_type_label")
        if label_index is None:
            raw_index = decision.get("source_label_index")
            if isinstance(raw_index, int) and not isinstance(raw_index, bool):
                label_index = raw_index
        clusters = decision.get("clusters")
        if not isinstance(clusters, list):
            raise GlobalTypeMergeError(f"{decision_path}: clusters must be an array")
        for local_index, cluster in enumerate(clusters, 1):
            if not isinstance(cluster, Mapping):
                raise GlobalTypeMergeError(f"{decision_path}: cluster {local_index} must be an object")
            status = cluster.get("decision_status")
            label = cluster.get("canonical_type_label")
            mechanism = cluster.get("canonical_task_mechanism")
            base_ids = cluster.get("base_cluster_ids", [])
            member_count = cluster.get("member_count")
            if not isinstance(label, str) or not label.strip():
                raise GlobalTypeMergeError(f"{decision_path}: cluster {local_index} missing canonical_type_label")
            if not isinstance(mechanism, str) or not mechanism.strip():
                raise GlobalTypeMergeError(f"{decision_path}: cluster {local_index} missing canonical_task_mechanism")
            if not isinstance(base_ids, list) or any(not isinstance(item, str) for item in base_ids):
                raise GlobalTypeMergeError(f"{decision_path}: cluster {local_index} has invalid base_cluster_ids")
            if isinstance(member_count, bool) or not isinstance(member_count, int) or member_count < 0:
                raise GlobalTypeMergeError(f"{decision_path}: cluster {local_index} has invalid member_count")
            record = {
                "canonical_type_label": label.strip(),
                "canonical_task_mechanism": mechanism.strip(),
                "member_count": member_count,
                "source_type_label": source_label,
                "source_label_index": label_index,
                "base_cluster_ids": base_ids,
                "source_decision_path": str(decision_path),
                "source_cluster_index": local_index,
                "decision_status": status,
            }
            if status == "candidate":
                records.append(record)
            elif status == "unresolved":
                unresolved.append(record)
            else:
                raise GlobalTypeMergeError(
                    f"{decision_path}: cluster {local_index} has unsupported decision_status {status!r}"
                )

    # Ordering is deliberately independent of source labels. It makes the packet
    # stable while putting larger, clearer clusters first for anchor-style review.
    records.sort(
        key=lambda item: (
            -int(item["member_count"]),
            item["canonical_type_label"],
            item["canonical_task_mechanism"],
            tuple(item["base_cluster_ids"]),
        )
    )
    unresolved.sort(
        key=lambda item: (
            -int(item["member_count"]),
            item["canonical_type_label"],
            item["canonical_task_mechanism"],
            tuple(item["base_cluster_ids"]),
        )
    )
    for index, record in enumerate(records, 1):
        record["global_input_id"] = f"LOCAL-{index:06d}"
    for index, record in enumerate(unresolved, 1):
        record["unresolved_input_id"] = f"UNRESOLVED-{index:06d}"

    semantic_records = [
        {
            "global_input_id": item["global_input_id"],
            "canonical_type_label": item["canonical_type_label"],
            "canonical_task_mechanism": item["canonical_task_mechanism"],
            "member_count": item["member_count"],
        }
        for item in records
    ]
    provenance = [
        {
            "global_input_id": item["global_input_id"],
            "source_type_label": item["source_type_label"],
            "source_label_index": item["source_label_index"],
            "source_decision_path": item["source_decision_path"],
            "source_cluster_index": item["source_cluster_index"],
            "base_cluster_ids": item["base_cluster_ids"],
        }
        for item in records
    ]
    return {
        "schema_version": "global-type-merge-packet-v1",
        "stage2_root": str(stage2_root),
        "progress_path": str(progress_path) if progress_path else None,
        "candidate_clusters": semantic_records,
        "provenance": provenance,
        "unresolved_clusters": unresolved,
        "report": {
            "decision_file_count": len(paths),
            "candidate_cluster_count": len(records),
            "candidate_member_count": sum(int(item["member_count"]) for item in records),
            "unresolved_cluster_count": len(unresolved),
            "unresolved_member_count": sum(int(item["member_count"]) for item in unresolved),
            "candidate_source_label_count": len({item["source_type_label"] for item in records}),
            "unresolved_source_label_count": len({item["source_type_label"] for item in unresolved}),
        },
    }


def write_global_merge_packet(packet: Mapping[str, Any], output_root: Path) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=False)
    candidates = packet["candidate_clusters"]
    provenance = {item["global_input_id"]: item for item in packet["provenance"]}
    unresolved = packet["unresolved_clusters"]
    _write_json(output_root / "global-merge-packet.json", packet)
    _write_jsonl(
        output_root / "global-candidate-clusters.jsonl",
        [
            {**item, **provenance[item["global_input_id"]]}
            for item in candidates
        ],
    )
    _write_jsonl(output_root / "global-unresolved-clusters.jsonl", unresolved)
    template = {
        "schema_version": "global-type-merge-decisions-v1",
        "groups": [],
        "candidate_cluster_ids": [item["global_input_id"] for item in candidates],
        "instructions": "每个 candidate_clusters.global_input_id 必须恰好归入一个 group；只依据题型名称和作答机制判断，不使用原始标签字段。",
    }
    _write_json(output_root / "global-merge-decisions.template.json", template)
    report = {
        "schema_version": "global-type-merge-input-report-v1",
        **packet["report"],
        "output_root": str(output_root),
        "semantic_input": "candidate_clusters（未包含原始标签；provenance 仅用于回溯）",
        "unresolved_policy": "不进入首轮跨标签归并，单独保留",
    }
    _write_json(output_root / "global-merge-input.report.json", report)
    return report


def materialize_global_merge(
    packet_path: Path,
    decisions_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    """Validate AI/Codex group decisions and materialize global clusters."""
    packet = _read_json(packet_path)
    decisions = _read_json(decisions_path)
    candidates = packet.get("candidate_clusters")
    provenance = packet.get("provenance")
    if not isinstance(candidates, list) or not isinstance(provenance, list):
        raise GlobalTypeMergeError("packet must contain candidate_clusters and provenance arrays")
    candidate_by_id = {item.get("global_input_id"): item for item in candidates if isinstance(item, Mapping)}
    if len(candidate_by_id) != len(candidates) or any(not key for key in candidate_by_id):
        raise GlobalTypeMergeError("candidate_clusters must have unique global_input_id values")
    provenance_by_id = {item.get("global_input_id"): item for item in provenance if isinstance(item, Mapping)}
    groups = decisions.get("groups")
    if not isinstance(groups, list) or not groups:
        raise GlobalTypeMergeError("decisions.groups must be a non-empty array")
    assigned: dict[str, str] = {}
    materialized: list[dict[str, Any]] = []
    input_member_counts: dict[str, int] = {}
    for group_index, group in enumerate(groups, 1):
        if not isinstance(group, Mapping):
            raise GlobalTypeMergeError(f"group {group_index} must be an object")
        group_id = group.get("global_cluster_id") or f"GLOBAL-{group_index:04d}"
        label = group.get("canonical_type_label")
        mechanism = group.get("canonical_task_mechanism")
        member_ids = group.get("member_cluster_ids")
        if group.get("decision_status", "candidate") != "candidate":
            raise GlobalTypeMergeError(f"group {group_index}: decision_status must be candidate")
        if not isinstance(group_id, str) or not group_id:
            raise GlobalTypeMergeError(f"group {group_index}: invalid global_cluster_id")
        if not isinstance(label, str) or not label.strip() or not isinstance(mechanism, str) or not mechanism.strip():
            raise GlobalTypeMergeError(f"group {group_index}: canonical label and mechanism are required")
        if not isinstance(member_ids, list) or not member_ids or any(not isinstance(item, str) for item in member_ids):
            raise GlobalTypeMergeError(f"group {group_index}: member_cluster_ids must be a non-empty string array")
        if group_id in {item["global_cluster_id"] for item in materialized}:
            raise GlobalTypeMergeError(f"duplicate global_cluster_id: {group_id}")
        members: list[dict[str, Any]] = []
        for member_id in member_ids:
            if member_id not in candidate_by_id:
                raise GlobalTypeMergeError(f"group {group_id}: unknown member {member_id}")
            if member_id in assigned:
                raise GlobalTypeMergeError(f"member assigned more than once: {member_id}")
            assigned[member_id] = group_id
            member = candidate_by_id[member_id]
            input_member_counts[member_id] = int(member["member_count"])
            members.append(
                {
                    "global_input_id": member_id,
                    "member_count": int(member["member_count"]),
                    **(provenance_by_id.get(member_id) or {}),
                }
            )
        materialized.append(
            {
                "global_cluster_id": group_id,
                "canonical_type_label": label.strip(),
                "canonical_task_mechanism": mechanism.strip(),
                "decision_status": "candidate",
                "member_cluster_ids": member_ids,
                "member_count": sum(item["member_count"] for item in members),
                "source_type_labels": sorted({item["source_type_label"] for item in members if item.get("source_type_label")}),
                "base_cluster_ids": [base_id for item in members for base_id in item.get("base_cluster_ids", [])],
                "merge_reason": str(group.get("merge_reason", "")).strip(),
            }
        )
    missing = sorted(set(candidate_by_id) - set(assigned))
    if missing:
        raise GlobalTypeMergeError(f"unassigned candidate clusters: {missing[:5]}")
    output_root.mkdir(parents=True, exist_ok=False)
    materialized.sort(key=lambda item: (-int(item["member_count"]), item["canonical_type_label"], item["global_cluster_id"]))
    _write_json(output_root / "global-clusters.json", {
        "schema_version": "global-type-clusters-v1",
        "clusters": materialized,
        "unresolved_clusters": packet.get("unresolved_clusters", []),
    })
    _write_jsonl(
        output_root / "global-cluster-members.jsonl",
        [
            {
                "global_cluster_id": cluster["global_cluster_id"],
                "global_input_id": member_id,
                "member_count": input_member_counts[member_id],
                **(provenance_by_id.get(member_id) or {}),
            }
            for cluster in materialized
            for member_id in cluster["member_cluster_ids"]
        ],
    )
    report = {
        "schema_version": "global-type-merge-report-v1",
        "packet_path": str(packet_path),
        "decisions_path": str(decisions_path),
        "global_cluster_count": len(materialized),
        "candidate_input_cluster_count": len(candidates),
        "candidate_member_count": sum(int(item["member_count"]) for item in candidates),
        "unresolved_cluster_count": len(packet.get("unresolved_clusters", [])),
        "unresolved_member_count": sum(int(item.get("member_count", 0)) for item in packet.get("unresolved_clusters", [])),
        "global_cluster_member_counts": Counter(item["member_count"] for item in materialized),
    }
    _write_json(output_root / "global-merge.report.json", report)
    return report
