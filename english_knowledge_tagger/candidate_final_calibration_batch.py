"""Build per-label final-prompt calibration packets from a packet batch index."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .final_label_discriminator import FINAL_PACKET_SCHEMA_VERSION


PACKET_BATCH_SCHEMA_VERSION = "candidate-final-packet-batch-v1"
CALIBRATION_BATCH_SCHEMA_VERSION = "candidate-final-calibration-batch-v1"
_FORBIDDEN_PACKET_FIELDS = frozenset({"input", "instruction", "output", "output_all"})


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _string(value: object, *, field: str, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: {field} must be a non-empty string")
    return value.strip()


def _load_packet_batch_index(path: Path) -> dict[str, dict[str, str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"packet batch index is not valid JSON: {path}") from error
    if not isinstance(payload, Mapping) or payload.get("schema_version") != PACKET_BATCH_SCHEMA_VERSION:
        raise ValueError("packet batch index has unexpected schema_version")
    raw_labels = payload.get("labels")
    if not isinstance(raw_labels, Mapping) or not raw_labels:
        raise ValueError("packet batch index labels must be a non-empty object")
    labels: dict[str, dict[str, str]] = {}
    relative_paths: set[str] = set()
    for label, item in raw_labels.items():
        if not isinstance(label, str) or not label.strip() or not isinstance(item, Mapping):
            raise ValueError("packet batch index labels must map strings to objects")
        source = f"packet batch index label {label!r}"
        canonical_label = _string(item.get("canonical_label"), field="canonical_label", source=source)
        relative_path = _string(
            item.get("packet_relative_path"), field="packet_relative_path", source=source
        )
        path_parts = Path(relative_path).parts
        if Path(relative_path).is_absolute() or ".." in path_parts:
            raise ValueError(f"{source}: packet_relative_path must stay under the index directory")
        if relative_path in relative_paths:
            raise ValueError(f"packet batch index has duplicate packet_relative_path: {relative_path}")
        relative_paths.add(relative_path)
        labels[label] = {
            "canonical_label": canonical_label,
            "packet_relative_path": relative_path,
        }
    return labels


def _load_review_sample(
    path: Path, *, batch_labels: frozenset[str]
) -> tuple[dict[str, dict[str, dict[str, str | None]]], int, int]:
    reviews: dict[str, dict[str, dict[str, str | None]]] = {}
    review_records = 0
    outside_batch = 0
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"review sample line {line_number}: invalid JSON") from error
            if not isinstance(row, Mapping):
                raise ValueError(f"review sample line {line_number}: JSONL row must be an object")
            origin = f"review sample line {line_number}"
            label = _string(row.get("verify_label"), field="verify_label", source=origin)
            question_id = _string(row.get("question_id"), field="question_id", source=origin)
            review_id = _string(row.get("review_id"), field="review_id", source=origin)
            stratum = row.get("review_stratum")
            if stratum is not None and not isinstance(stratum, str):
                raise ValueError(f"{origin}: review_stratum must be a string or null")
            review_records += 1
            if label not in batch_labels:
                outside_batch += 1
                continue
            bucket = reviews.setdefault(label, {})
            if question_id in bucket:
                raise ValueError(f"{origin}: duplicate review question_id for label {label!r}")
            bucket[question_id] = {
                "review_id": review_id,
                "review_stratum": stratum.strip() if isinstance(stratum, str) and stratum.strip() else None,
            }
    return reviews, review_records, outside_batch


def _final_packet_rows(
    path: Path, *, verify_label: str
) -> tuple[dict[str, dict[str, Any]], int]:
    rows: dict[str, dict[str, Any]] = {}
    packet_records = 0
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"final packet {path} line {line_number}: invalid JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"final packet {path} line {line_number}: JSONL row must be an object")
            origin = f"final packet {path} line {line_number}"
            if row.get("schema_version") != FINAL_PACKET_SCHEMA_VERSION:
                raise ValueError(f"{origin}: unexpected packet schema_version")
            if row.get("verify_label") != verify_label:
                raise ValueError(f"{origin}: verify_label differs from packet batch index")
            forbidden = sorted(_FORBIDDEN_PACKET_FIELDS & set(row))
            if forbidden:
                raise ValueError(f"{origin}: forbidden source fields in final packet: {forbidden}")
            question_id = _string(row.get("question_id"), field="question_id", source=origin)
            if question_id in rows:
                raise ValueError(f"{origin}: duplicate question_id in final packet: {question_id!r}")
            rows[question_id] = row
            packet_records += 1
    return rows, packet_records


def _packet_filename(source_relative_path: str) -> str:
    filename = Path(source_relative_path).name
    suffix = ".final.packet.jsonl"
    if filename.endswith(suffix):
        return filename.removesuffix(suffix) + ".calibration.packet.jsonl"
    return filename + ".calibration.packet.jsonl"


def build_candidate_final_calibration_batch(
    *,
    packet_batch_index_path: Path,
    review_sample_path: Path,
    output_dir: Path,
) -> dict[str, object]:
    """Create auditable per-label calibration packets without calling a model."""
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing output directory: {output_dir}")
    labels = _load_packet_batch_index(packet_batch_index_path)
    reviews, review_records, outside_batch = _load_review_sample(
        review_sample_path, batch_labels=frozenset(labels)
    )
    if not reviews:
        raise ValueError("review sample contains no records for labels in the packet batch")

    output_dir.mkdir(parents=True)
    packets_dir = output_dir / "packets"
    packets_dir.mkdir()
    output_labels: dict[str, dict[str, object]] = {}
    total_eligible = 0
    total_missing = 0
    for label, details in labels.items():
        review_bucket = reviews.get(label, {})
        source_packet_path = packet_batch_index_path.parent / details["packet_relative_path"]
        final_rows, final_packet_records = _final_packet_rows(source_packet_path, verify_label=label)
        eligible_rows: list[dict[str, Any]] = []
        strata: Counter[str] = Counter()
        for question_id, packet_row in final_rows.items():
            review = review_bucket.get(question_id)
            if review is None:
                continue
            output_row = {
                **packet_row,
                "calibration_source_review_id": review["review_id"],
                "calibration_review_stratum": review["review_stratum"],
                "calibration_review_sample_path": str(review_sample_path),
            }
            eligible_rows.append(output_row)
            strata[review["review_stratum"] or "missing"] += 1
        missing_question_ids = sorted(set(review_bucket) - set(final_rows))
        relative_path: str | None = None
        if review_bucket:
            relative_path = str(Path("packets") / _packet_filename(details["packet_relative_path"]))
            with (output_dir / relative_path).open("x", encoding="utf-8") as output:
                for row in eligible_rows:
                    output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        total_eligible += len(eligible_rows)
        total_missing += len(missing_question_ids)
        output_labels[label] = {
            "canonical_label": details["canonical_label"],
            "source_final_packet_relative_path": details["packet_relative_path"],
            "source_final_packet_records": final_packet_records,
            "packet_relative_path": relative_path,
            "review_sample_records_for_label": len(review_bucket),
            "eligible_calibration_records": len(eligible_rows),
            "missing_from_final_packet_question_ids": missing_question_ids,
            "eligible_by_review_stratum": dict(sorted(strata.items())),
        }

    index = {
        "schema_version": CALIBRATION_BATCH_SCHEMA_VERSION,
        "purpose": "non_releasing_final_prompt_calibration_packet_materialization",
        "packet_batch_index_path": str(packet_batch_index_path),
        "packet_batch_index_sha256": _sha256(packet_batch_index_path),
        "review_sample_path": str(review_sample_path),
        "review_sample_sha256": _sha256(review_sample_path),
        "candidate_labels": len(labels),
        "review_records": review_records,
        "review_records_outside_packet_batch": outside_batch,
        "eligible_calibration_records": total_eligible,
        "missing_from_final_packet_records": total_missing,
        "labels": output_labels,
    }
    index_path = output_dir / "calibration.index.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "schema_version": "candidate-final-calibration-batch-report-v1",
        "output_dir": str(output_dir),
        "index_path": str(index_path),
        "candidate_labels": len(labels),
        "review_records": review_records,
        "review_records_outside_packet_batch": outside_batch,
        "eligible_calibration_records": total_eligible,
        "missing_from_final_packet_records": total_missing,
    }
