"""Create compact, blind review packets for exact question-type route groups."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .type_inventory import _TYPE_NAME_PATTERN, _TYPE_STRUCTURE_PATTERN, _declared_value
from .type_routing import _identifier, _legacy_type_paths, _scope_from_record


def _route_key(scope: str, structure: str, name: str) -> tuple[str, str, str]:
    return (scope, structure, name)


def _route_key_text(key: tuple[str, str, str]) -> str:
    return "|".join(key)


def _scope_sort_key(scope: str) -> int:
    return {"parent": 0, "child": 1, "unknown": 2}[scope]


def _sample_score(key: tuple[str, str, str], question_id: str | None, source_line: int) -> bytes:
    stable_identifier = question_id or f"source-line:{source_line}"
    payload = "\0".join((*key, stable_identifier)).encode("utf-8")
    return hashlib.sha256(payload).digest()


def _review_record(
    record: Mapping[str, Any],
    *,
    source_line: int,
    key: tuple[str, str, str],
    include_legacy_labels: bool,
) -> dict[str, Any]:
    scope, structure, name = key
    question_id = _identifier(record.get("question_id"))
    item: dict[str, Any] = {
        "schema_version": "type-review-packet-v1",
        "review_id": f"type-review:{scope}:{structure}:{name}:{question_id or source_line}",
        "source_line": source_line,
        "question_id": question_id,
        "parent_id": _identifier(record.get("parent_id")),
        "route_key": {"scope": scope, "declared_type_structure": structure, "declared_type_name": name},
        "question_context": record.get("input") if isinstance(record.get("input"), str) else "",
    }
    if include_legacy_labels:
        item["legacy_type_labels"] = _legacy_type_paths(record)
    return item


def build_type_review_packet(
    input_path: Path,
    *,
    output_path: Path,
    per_route: int = 5,
    include_legacy_labels: bool = False,
) -> dict[str, Any]:
    """Stratify source records by exact declared-type route using stable sampling.

    The default output intentionally hides historical labels so independent model
    or human reviewers are not anchored to legacy data. Memory is bounded by the
    number of observed route keys times ``per_route``.
    """
    if output_path.exists():
        raise FileExistsError(f"type review packet already exists: {output_path}")
    if per_route <= 0:
        raise ValueError("per_route must be positive")

    route_counts: Counter[str] = Counter()
    processed = Counter[str]()
    samples: dict[tuple[str, str, str], list[tuple[bytes, int, dict[str, Any]]]] = {}
    with input_path.open("r", encoding="utf-8") as source:
        for source_line, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                processed["invalid_json_lines"] += 1
                continue
            if not isinstance(record, dict):
                processed["non_object_records"] += 1
                continue

            scope = _scope_from_record(record)
            structure = _declared_value(_TYPE_STRUCTURE_PATTERN, record.get("input"))
            name = _declared_value(_TYPE_NAME_PATTERN, record.get("input"))
            key = _route_key(scope, structure, name)
            route_counts[_route_key_text(key)] += 1
            item = _review_record(
                record,
                source_line=source_line,
                key=key,
                include_legacy_labels=include_legacy_labels,
            )
            candidate = (_sample_score(key, item["question_id"], source_line), source_line, item)
            bucket = samples.setdefault(key, [])
            bucket.append(candidate)
            bucket.sort(key=lambda value: (value[0], value[1]))
            del bucket[per_route:]
            processed["valid"] += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    emitted = 0
    with output_path.open("x", encoding="utf-8") as output:
        for key in sorted(samples, key=lambda item: (_scope_sort_key(item[0]), item[1], item[2])):
            for _, _, item in samples[key]:
                output.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
                emitted += 1

    return {
        "schema_version": "type-review-packet-report-v1",
        "input_path": str(input_path),
        "input_bytes": input_path.stat().st_size,
        "output_path": str(output_path),
        "per_route": per_route,
        "include_legacy_labels": include_legacy_labels,
        "processed_records": {
            "valid": processed["valid"],
            "invalid_json_lines": processed["invalid_json_lines"],
            "non_object_records": processed["non_object_records"],
        },
        "route_counts": {key: route_counts[key] for key in sorted(route_counts)},
        "route_groups": len(samples),
        "records": emitted,
    }
