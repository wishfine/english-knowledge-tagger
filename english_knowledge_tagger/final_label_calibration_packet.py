"""Select already human-reviewed, route-eligible rows for final prompt calibration."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any, Mapping

from .final_label_discriminator import FINAL_PACKET_SCHEMA_VERSION


def _string(value: object, *, field: str, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: {field} must be a non-empty string")
    return value.strip()


def _load_final_packet(path: Path, *, verify_label: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"final packet line {line_number}: invalid JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"final packet line {line_number}: JSONL row must be an object")
            origin = f"final packet line {line_number}"
            if row.get("schema_version") != FINAL_PACKET_SCHEMA_VERSION:
                raise ValueError(f"{origin}: unexpected packet schema_version")
            if _string(row.get("verify_label"), field="verify_label", source=origin) != verify_label:
                continue
            question_id = _string(row.get("question_id"), field="question_id", source=origin)
            if question_id in rows:
                raise ValueError(f"{origin}: duplicate final packet question_id {question_id!r}")
            rows[question_id] = row
    return rows


def build_final_label_calibration_packet(
    final_packet_path: Path,
    *,
    review_sample_path: Path,
    verify_label: str,
    output_path: Path,
) -> dict[str, object]:
    """Intersect a final packet with existing human-review identities.

    The human sample contains the manual stratum and review identity, while the
    final packet guarantees the prompt contains only sanitized question content.
    A missing sample item means it is not eligible for this exact route, not
    that its manual conclusion has been discarded.
    """
    target_label = _string(verify_label, field="verify_label", source="calibration request")
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite existing calibration packet: {output_path}")
    final_rows = _load_final_packet(final_packet_path, verify_label=target_label)
    review_records = 0
    eligible_records = 0
    missing_question_ids: list[str] = []
    seen_review_question_ids: set[str] = set()
    strata: Counter[str] = Counter()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with review_sample_path.open("r", encoding="utf-8") as review_source, output_path.open(
        "x", encoding="utf-8"
    ) as output:
        for line_number, line in enumerate(review_source, 1):
            if not line.strip():
                continue
            try:
                review = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"review sample line {line_number}: invalid JSON") from error
            if not isinstance(review, Mapping):
                raise ValueError(f"review sample line {line_number}: JSONL row must be an object")
            origin = f"review sample line {line_number}"
            label = review.get("verify_label")
            if label != target_label:
                continue
            review_records += 1
            question_id = _string(review.get("question_id"), field="question_id", source=origin)
            if question_id in seen_review_question_ids:
                raise ValueError(f"{origin}: duplicate review sample question_id {question_id!r}")
            seen_review_question_ids.add(question_id)
            packet_row = final_rows.get(question_id)
            if packet_row is None:
                missing_question_ids.append(question_id)
                continue
            review_id = _string(review.get("review_id"), field="review_id", source=origin)
            review_stratum = review.get("review_stratum")
            if review_stratum is not None and not isinstance(review_stratum, str):
                raise ValueError(f"{origin}: review_stratum must be a string or null")
            output_row = {
                **packet_row,
                "calibration_source_review_id": review_id,
                "calibration_review_stratum": review_stratum.strip()
                if isinstance(review_stratum, str) and review_stratum.strip()
                else None,
                "calibration_review_sample_path": str(review_sample_path),
            }
            output.write(json.dumps(output_row, ensure_ascii=False, sort_keys=True) + "\n")
            eligible_records += 1
            strata[output_row["calibration_review_stratum"] or "missing"] += 1
    if review_records == 0:
        raise ValueError("review sample contains no records for the requested verify_label")
    return {
        "schema_version": "final-label-calibration-packet-report-v1",
        "final_packet_path": str(final_packet_path),
        "review_sample_path": str(review_sample_path),
        "verify_label": target_label,
        "output_path": str(output_path),
        "review_sample_records_for_label": review_records,
        "eligible_calibration_records": eligible_records,
        "missing_from_final_packet_question_ids": sorted(missing_question_ids),
        "by_review_stratum": dict(sorted(strata.items())),
    }
