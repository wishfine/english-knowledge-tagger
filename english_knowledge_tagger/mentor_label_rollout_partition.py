"""Partition a frozen mentor label packet by a human-approved exact route policy."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


POLICY_SCHEMA_VERSION = "terminal-label-rollout-route-policy-v1"


@dataclass(frozen=True)
class MentorLabelRolloutRoutePolicy:
    verify_label: str
    prompt_version: str
    eligible_routes: frozenset[tuple[str, str, str]]
    quarantine_reason: str


def _string(value: object, *, field: str, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: {field} must be a non-empty string")
    return value.strip()


def _load_policy(path: Path) -> MentorLabelRolloutRoutePolicy:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"rollout route policy is not valid JSON: {path}") from error
    if not isinstance(payload, Mapping) or payload.get("schema_version") != POLICY_SCHEMA_VERSION:
        raise ValueError(f"rollout route policy schema_version must be {POLICY_SCHEMA_VERSION!r}")
    source = "rollout route policy"
    raw_routes = payload.get("eligible_routes")
    if not isinstance(raw_routes, list) or not raw_routes:
        raise ValueError(f"{source}: eligible_routes must be a non-empty list")
    routes: set[tuple[str, str, str]] = set()
    for index, raw_route in enumerate(raw_routes, 1):
        if not isinstance(raw_route, Mapping):
            raise ValueError(f"{source}: eligible_routes[{index}] must be an object")
        route = (
            _string(raw_route.get("scope"), field="scope", source=f"{source} route {index}"),
            _string(
                raw_route.get("declared_type_structure"),
                field="declared_type_structure",
                source=f"{source} route {index}",
            ),
            _string(
                raw_route.get("declared_type_name"),
                field="declared_type_name",
                source=f"{source} route {index}",
            ),
        )
        if route in routes:
            raise ValueError(f"{source}: duplicate eligible route {route}")
        routes.add(route)
    return MentorLabelRolloutRoutePolicy(
        verify_label=_string(payload.get("verify_label"), field="verify_label", source=source),
        prompt_version=_string(payload.get("prompt_version"), field="prompt_version", source=source),
        eligible_routes=frozenset(routes),
        quarantine_reason=_string(payload.get("quarantine_reason"), field="quarantine_reason", source=source),
    )


def _route(row: Mapping[str, Any], *, source: str) -> tuple[str, str, str]:
    route_key = row.get("route_key")
    if not isinstance(route_key, Mapping):
        raise ValueError(f"{source}: route_key must be an object")
    return (
        _string(route_key.get("scope"), field="route_key.scope", source=source),
        _string(
            route_key.get("declared_type_structure"),
            field="route_key.declared_type_structure",
            source=source,
        ),
        _string(
            route_key.get("declared_type_name"),
            field="route_key.declared_type_name",
            source=source,
        ),
    )


def partition_mentor_label_rollout_packet(
    packet_path: Path,
    *,
    policy_path: Path,
    eligible_output_path: Path,
    quarantine_output_path: Path,
) -> dict[str, object]:
    """Split one frozen packet without mutating its source rows or source JSONL."""
    if eligible_output_path.exists() or quarantine_output_path.exists():
        raise FileExistsError("refusing to overwrite an existing eligible or quarantine packet")
    policy = _load_policy(policy_path)
    eligible_output_path.parent.mkdir(parents=True, exist_ok=True)
    quarantine_output_path.parent.mkdir(parents=True, exist_ok=True)
    route_counts: Counter[str] = Counter()
    eligible_records = 0
    quarantine_records = 0
    packet_records = 0
    with packet_path.open("r", encoding="utf-8") as source, eligible_output_path.open(
        "x", encoding="utf-8"
    ) as eligible_output, quarantine_output_path.open("x", encoding="utf-8") as quarantine_output:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"packet line {line_number}: invalid JSON") from error
            if not isinstance(row, Mapping):
                raise ValueError(f"packet line {line_number}: JSONL row must be an object")
            row_source = f"packet line {line_number}"
            if row.get("verify_label") != policy.verify_label:
                raise ValueError(f"{row_source}: verify_label differs from route policy")
            if row.get("schema_version") != "mentor-label-rollout-packet-v1":
                raise ValueError(f"{row_source}: unexpected packet schema_version")
            if row.get("review_id") is None or row.get("source_line") is None:
                raise ValueError(f"{row_source}: review_id and source_line are required")
            route = _route(row, source=row_source)
            route_counts[" × ".join(route)] += 1
            destination = eligible_output if route in policy.eligible_routes else quarantine_output
            decision = "eligible" if route in policy.eligible_routes else "quarantine"
            output_row = {
                **row,
                "rollout_route_policy": {
                    "schema_version": POLICY_SCHEMA_VERSION,
                    "verify_label": policy.verify_label,
                    "prompt_version": policy.prompt_version,
                },
                "rollout_route_decision": decision,
                "rollout_route_reason": None if decision == "eligible" else policy.quarantine_reason,
            }
            destination.write(json.dumps(output_row, ensure_ascii=False, sort_keys=True) + "\n")
            packet_records += 1
            if decision == "eligible":
                eligible_records += 1
            else:
                quarantine_records += 1
    return {
        "schema_version": "mentor-label-rollout-route-partition-report-v1",
        "packet_path": str(packet_path),
        "policy_path": str(policy_path),
        "verify_label": policy.verify_label,
        "prompt_version": policy.prompt_version,
        "packet_records": packet_records,
        "eligible_records": eligible_records,
        "quarantine_records": quarantine_records,
        "eligible_output_path": str(eligible_output_path),
        "quarantine_output_path": str(quarantine_output_path),
        "route_counts": dict(sorted(route_counts.items())),
    }
