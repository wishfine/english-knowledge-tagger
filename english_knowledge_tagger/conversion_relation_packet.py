"""Create auditable, label-blind packets for conversion relation checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from .mentor_direct_rollout import clean_mentor_v1_input
from .p0_direct_diagnosis import _route_key


SCHEMA_VERSION = "conversion-relation-packet-v1"


def _text(value: object, *, field: str, origin: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{origin}: {field} must be a non-empty string")
    return value.strip()


def build_conversion_relation_packet(source_path: Path, *, output_path: Path) -> dict[str, object]:
    """Convert materialized mentor rows into DS-safe relation-classification tasks.

    Historical label and direct-verifier fields deliberately do not enter the
    task output; they remain in the source materialization for later joins.
    """
    if output_path.exists():
        raise FileExistsError(f"conversion relation packet already exists: {output_path}")

    tasks: list[dict[str, object]] = []
    seen_question_ids: set[str] = set()
    with source_path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"source line {line_number}: invalid JSON") from error
            if not isinstance(row, Mapping):
                raise ValueError(f"source line {line_number}: row must be an object")
            origin = f"source line {line_number}"
            question_id = _text(row.get("question_id"), field="question_id", origin=origin)
            if question_id in seen_question_ids:
                raise ValueError(f"{origin}: duplicate question_id {question_id!r}")
            seen_question_ids.add(question_id)
            parent_id = _text(row.get("parent_id"), field="parent_id", origin=origin)
            input_text = _text(row.get("input"), field="input", origin=origin)
            context = clean_mentor_v1_input(input_text).strip()
            if not context:
                raise ValueError(f"{origin}: cleaned question context is empty")
            tasks.append({
                "schema_version": SCHEMA_VERSION,
                "task_id": f"conversion-relation:{question_id}",
                "source_line": line_number,
                "question_id": question_id,
                "parent_id": parent_id,
                "route_key": _route_key(input_text, row.get("is_sub_question")),
                "question_context": context,
            })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as output:
        for task in tasks:
            output.write(json.dumps(task, ensure_ascii=False, sort_keys=True) + "\n")
    return {
        "schema_version": "conversion-relation-packet-report-v1",
        "source_path": str(source_path),
        "output_path": str(output_path),
        "packet_records": len(tasks),
    }
