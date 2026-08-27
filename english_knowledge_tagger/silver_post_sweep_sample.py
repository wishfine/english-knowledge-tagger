"""Create an independent, reproducible post-sweep audit sample from silver evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


def _nonempty_string(value: object, *, field: str, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: {field} must be a non-empty string")
    return value.strip()


def _read_excluded_question_ids(path: Path, *, verify_label: str) -> set[str]:
    excluded: set[str] = set()
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"exclude JSONL line {line_number}: invalid JSON") from error
            if not isinstance(row, Mapping):
                raise ValueError(f"exclude JSONL line {line_number}: JSONL row must be an object")
            row_label = row.get("verify_label", row.get("legacy_label"))
            if row_label is not None and row_label != verify_label:
                continue
            question_id = row.get("question_id")
            if isinstance(question_id, str) and question_id.strip():
                excluded.add(question_id.strip())
    return excluded


def sample_silver_post_sweep(
    silver_evidence_path: Path,
    *,
    verify_label: str,
    output_path: Path,
    sample_size: int = 60,
    seed: str,
    exclude_jsonl_path: Path | None = None,
) -> dict[str, object]:
    """Sample new positive evidence deterministically, excluding initial audit questions."""
    target = verify_label.strip()
    if not target:
        raise ValueError("verify_label must be non-empty")
    if not isinstance(sample_size, int) or isinstance(sample_size, bool) or sample_size <= 0:
        raise ValueError("sample_size must be a positive integer")
    if not isinstance(seed, str) or not seed:
        raise ValueError("seed must be non-empty")
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite existing post-sweep sample: {output_path}")
    excluded_question_ids = (
        _read_excluded_question_ids(exclude_jsonl_path, verify_label=target)
        if exclude_jsonl_path is not None
        else set()
    )
    eligible: list[dict[str, Any]] = []
    seen_review_ids: set[str] = set()
    available_records = 0
    excluded_records = 0
    with silver_evidence_path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"silver evidence line {line_number}: invalid JSON") from error
            if not isinstance(row, Mapping):
                raise ValueError(f"silver evidence line {line_number}: JSONL row must be an object")
            if row.get("legacy_label") != target:
                continue
            available_records += 1
            source_name = f"silver evidence line {line_number}"
            if row.get("disposition") != "silver_label_candidate":
                raise ValueError(f"{source_name}: target label evidence must be silver_label_candidate")
            if row.get("status") != "candidate" or row.get("llm_match") is not True:
                raise ValueError(f"{source_name}: target label evidence must be a positive candidate result")
            review_id = _nonempty_string(row.get("review_id"), field="review_id", source=source_name)
            question_id = _nonempty_string(row.get("question_id"), field="question_id", source=source_name)
            if review_id in seen_review_ids:
                raise ValueError(f"{source_name}: duplicate review_id {review_id!r}")
            seen_review_ids.add(review_id)
            if question_id in excluded_question_ids:
                excluded_records += 1
                continue
            eligible.append(dict(row))
    ranked = sorted(
        eligible,
        key=lambda row: hashlib.sha256(
            f"{seed}\0{row['review_id']}".encode("utf-8")
        ).hexdigest(),
    )
    selected = ranked[:sample_size]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as output:
        for row in selected:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {
        "schema_version": "silver-post-sweep-sample-report-v1",
        "silver_evidence_path": str(silver_evidence_path),
        "verify_label": target,
        "seed": seed,
        "sample_size_requested": sample_size,
        "available_records": available_records,
        "excluded_records": excluded_records,
        "eligible_records": len(eligible),
        "selected_records": len(selected),
        "output_path": str(output_path),
        "exclude_jsonl_path": str(exclude_jsonl_path) if exclude_jsonl_path is not None else None,
    }
