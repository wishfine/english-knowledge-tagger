"""Join mentor verifier outputs back to their full sampled question records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping


SCHEMA_VERSION = "mentor-direct-materialized-v1"


def _string(value: object, *, field: str, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: {field} must be a non-empty string")
    return value.strip()


def _read_target_rows(path: Path, *, verify_label: str, source_name: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen_question_ids: set[str] = set()
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{source_name} line {line_number}: invalid JSON") from error
            if not isinstance(row, Mapping):
                raise ValueError(f"{source_name} line {line_number}: row must be an object")
            origin = f"{source_name} line {line_number}"
            if _string(row.get("verify_label"), field="verify_label", source=origin) != verify_label:
                continue
            question_id = _string(row.get("question_id"), field="question_id", source=origin)
            if question_id in seen_question_ids:
                raise ValueError(f"{source_name}: duplicate target question_id {question_id!r}")
            seen_question_ids.add(question_id)
            rows.append(dict(row))
    return rows


def materialize_mentor_direct_verdicts(
    samples_path: Path,
    *,
    results_path: Path,
    verify_label: str,
    output_path: Path,
) -> dict[str, object]:
    """Write complete source records for one label without changing either input."""
    target = _string(verify_label, field="verify_label", source="materialization request")
    if output_path.exists():
        raise FileExistsError(f"materialized verifier output already exists: {output_path}")

    results = _read_target_rows(results_path, verify_label=target, source_name="mentor results")
    samples = _read_target_rows(samples_path, verify_label=target, source_name="mentor samples")
    results_by_question_id = {str(row["question_id"]): row for row in results}
    samples_by_question_id = {str(row["question_id"]): row for row in samples}

    missing_samples = set(results_by_question_id) - set(samples_by_question_id)
    if missing_samples:
        raise ValueError(f"missing sample for result question_id {sorted(missing_samples)[0]!r}")
    missing_results = set(samples_by_question_id) - set(results_by_question_id)
    if missing_results:
        raise ValueError(f"missing result for sample question_id {sorted(missing_results)[0]!r}")

    required_sample_fields = ("parent_id", "is_sub_question", "input", "output_all")
    required_result_fields = ("llm_match", "llm_reason", "llm_should_be")
    materialized: list[dict[str, object]] = []
    for position, sample in enumerate(samples, 1):
        origin = f"mentor sample target record {position}"
        for field in required_sample_fields:
            if field not in sample:
                raise ValueError(f"{origin}: missing required sample field {field!r}")
        result = results_by_question_id[str(sample["question_id"])]
        for field in required_result_fields:
            if field not in result:
                raise ValueError(f"mentor result for {sample['question_id']!r}: missing required result field {field!r}")
        if not isinstance(result["llm_match"], bool):
            raise ValueError(f"mentor result for {sample['question_id']!r}: llm_match must be boolean")
        materialized.append(
            {
                **sample,
                "llm_match": result["llm_match"],
                "llm_reason": result["llm_reason"],
                "llm_should_be": result["llm_should_be"],
                "materialization_schema_version": SCHEMA_VERSION,
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as output:
        for row in materialized:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {
        "schema_version": "mentor-direct-materialization-report-v1",
        "samples_path": str(samples_path),
        "results_path": str(results_path),
        "verify_label": target,
        "output_path": str(output_path),
        "sample_records": len(samples),
        "result_records": len(results),
        "materialized_records": len(materialized),
    }
