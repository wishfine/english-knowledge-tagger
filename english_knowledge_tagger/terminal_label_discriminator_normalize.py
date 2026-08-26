"""Adapt runner-specific direct-label verdicts to the stable evidence contract.

The field map is deliberately explicit.  It avoids inferring whether a runner's
``match`` field, question ID, or target label means the thing this pipeline needs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from .terminal_label_discriminator_gate import EVIDENCE_SCHEMA_VERSION


FIELD_MAP_SCHEMA_VERSION = "terminal-label-discriminator-field-map-v1"
REQUIRED_EVIDENCE_FIELDS = frozenset(
    {
        "review_id",
        "question_id",
        "parent_id",
        "source_line",
        "is_sub_question",
        "legacy_label",
        "canonical_label",
        "llm_match",
        "status",
        "model",
        "prompt_version",
    }
)


def _path(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(
        isinstance(part, str) and part for part in value
    ):
        raise ValueError(f"field map fields.{field} must be a non-empty list of object keys")
    return tuple(value)


def load_discriminator_field_map(path: Path) -> dict[str, object]:
    """Load source selectors and constants for one specific runner export schema."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"direct discriminator field map is not valid JSON: {path}") from error
    if not isinstance(payload, Mapping) or payload.get("schema_version") != FIELD_MAP_SCHEMA_VERSION:
        raise ValueError(
            f"direct discriminator field map schema_version must be {FIELD_MAP_SCHEMA_VERSION!r}"
        )
    raw_fields = payload.get("fields", {})
    constants = payload.get("constants", {})
    if not isinstance(raw_fields, Mapping) or not isinstance(constants, Mapping):
        raise ValueError("direct discriminator field map fields and constants must be objects")
    supported = REQUIRED_EVIDENCE_FIELDS | {"route_key"}
    unknown = (set(raw_fields) | set(constants)) - supported
    if unknown:
        raise ValueError(f"direct discriminator field map has unsupported fields: {sorted(unknown)}")
    overlap = set(raw_fields) & set(constants)
    if overlap:
        raise ValueError(f"direct discriminator field map cannot map and constant the same field: {sorted(overlap)}")
    missing = REQUIRED_EVIDENCE_FIELDS - (set(raw_fields) | set(constants))
    if missing:
        raise ValueError(f"direct discriminator field map is missing required fields: {sorted(missing)}")
    return {
        "fields": {field: _path(value, field=field) for field, value in raw_fields.items()},
        "constants": dict(constants),
    }


def _get_path(raw_row: object, path: tuple[str, ...], *, line_number: int, field: str) -> object:
    value = raw_row
    for segment in path:
        if not isinstance(value, Mapping) or segment not in value:
            raise ValueError(
                f"raw discriminator line {line_number}: cannot resolve fields.{field} at {'.'.join(path)}"
            )
        value = value[segment]
    return value


def normalise_terminal_label_discriminator_row(
    raw_row: object,
    *,
    line_number: int,
    field_map: Mapping[str, object],
) -> dict[str, object]:
    """Map one raw row without deciding whether its label is high quality."""
    if not isinstance(raw_row, Mapping):
        raise ValueError(f"raw discriminator line {line_number}: JSONL row must be an object")
    fields = field_map.get("fields")
    constants = field_map.get("constants")
    if not isinstance(fields, Mapping) or not isinstance(constants, Mapping):
        raise ValueError("field_map must be returned by load_discriminator_field_map")
    evidence: dict[str, object] = {"schema_version": EVIDENCE_SCHEMA_VERSION}
    field_names = REQUIRED_EVIDENCE_FIELDS | ({"route_key"} & (set(fields) | set(constants)))
    for field in field_names:
        if field in constants:
            evidence[field] = constants[field]
            continue
        source_path = fields.get(field)
        if not isinstance(source_path, tuple):
            raise ValueError(f"field_map missing compiled selector for {field}")
        evidence[field] = _get_path(raw_row, source_path, line_number=line_number, field=field)
    evidence["raw_discriminator_record"] = dict(raw_row)
    return evidence
