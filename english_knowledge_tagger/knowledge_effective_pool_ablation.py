"""Build paired DS validation packets for genuine candidate-pool expansions only."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "knowledge-effective-pool-ablation-packet-v1"
_IDENTITY_FIELDS = ("source_line", "question_id", "parent_id", "canonical_label")


def _nonempty_string(value: object, *, field: str, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: {field} must be a non-empty string")
    return value.strip()


def _read_rows(path: Path) -> tuple[list[str], dict[str, dict[str, Any]]]:
    order: list[str] = []
    rows: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            source_name = f"{path} line {line_number}"
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{source_name}: invalid JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"{source_name}: JSONL row must be an object")
            review_id = _nonempty_string(row.get("review_id"), field="review_id", source=source_name)
            if review_id in rows:
                raise ValueError(f"{source_name}: duplicate review_id {review_id}")
            rows[review_id] = row
            order.append(review_id)
    return order, rows


def _identity(row: Mapping[str, Any], *, source: str) -> tuple[object, ...]:
    return tuple(row.get(field) for field in _IDENTITY_FIELDS) + (
        _context_hash(row, source=source),
    )


def _context_hash(row: Mapping[str, Any], *, source: str) -> str:
    context = _nonempty_string(row.get("question_context"), field="question_context", source=source)
    return hashlib.sha256(context.encode("utf-8")).hexdigest()


def _effective_coverage_rows(path: Path) -> tuple[list[str], dict[str, dict[str, Any]]]:
    order, coverage_rows = _read_rows(path)
    effective_order: list[str] = []
    effective_rows: dict[str, dict[str, Any]] = {}
    for review_id in order:
        row = coverage_rows[review_id]
        labels = row.get("newly_available_alternative_labels")
        if not isinstance(labels, list):
            raise ValueError(
                f"{path}: coverage row {review_id} needs newly_available_alternative_labels list"
            )
        if not labels:
            continue
        normalized_labels = tuple(
            _nonempty_string(label, field="newly_available_alternative_labels", source=f"{path}: {review_id}")
            for label in labels
        )
        if len(set(normalized_labels)) != len(normalized_labels):
            raise ValueError(f"{path}: coverage row {review_id} has duplicate newly available labels")
        target_parent = _nonempty_string(
            row.get("target_parent_path"), field="target_parent_path", source=f"{path}: {review_id}"
        )
        effective_rows[review_id] = {
            **row,
            "newly_available_alternative_labels": list(normalized_labels),
            "target_parent_path": target_parent,
        }
        effective_order.append(review_id)
    return effective_order, effective_rows


def build_effective_pool_ablation_packets(
    baseline_packet: Path,
    candidate_packet: Path,
    coverage_packet: Path,
    *,
    baseline_output_path: Path,
    candidate_output_path: Path,
) -> dict[str, object]:
    """Write same-order v0.1/v0.2 subsets where v0.2 adds actual alternatives."""
    if baseline_output_path.exists() or candidate_output_path.exists():
        raise FileExistsError("effective pool ablation output already exists")
    baseline_order, baseline_rows = _read_rows(baseline_packet)
    _, candidate_rows = _read_rows(candidate_packet)
    if set(baseline_rows) != set(candidate_rows):
        raise ValueError("baseline and candidate packets do not contain the same review_ids")
    effective_order, coverage_rows = _effective_coverage_rows(coverage_packet)
    missing = [review_id for review_id in effective_order if review_id not in baseline_rows]
    if missing:
        raise ValueError(f"coverage review_ids absent from paired packets: {missing[:3]}")

    selected_ids = [review_id for review_id in baseline_order if review_id in coverage_rows]
    if set(selected_ids) != set(effective_order):
        raise ValueError("effective coverage IDs are not represented exactly once in baseline ordering")
    selected_baseline: list[dict[str, Any]] = []
    selected_candidate: list[dict[str, Any]] = []
    by_parent: Counter[str] = Counter()
    labels: list[str] = []
    for review_id in selected_ids:
        baseline = baseline_rows[review_id]
        candidate = candidate_rows[review_id]
        coverage = coverage_rows[review_id]
        baseline_identity = _identity(baseline, source=f"baseline packet {review_id}")
        candidate_identity = _identity(candidate, source=f"candidate packet {review_id}")
        coverage_identity = tuple(coverage.get(field) for field in _IDENTITY_FIELDS)
        if baseline_identity != candidate_identity:
            raise ValueError(f"paired packets disagree on immutable identity for review_id {review_id}")
        if baseline_identity[: len(_IDENTITY_FIELDS)] != coverage_identity:
            raise ValueError(f"coverage packet disagrees on immutable identity for review_id {review_id}")
        baseline_labels = {
            item.get("label")
            for item in baseline.get("alternative_labels", [])
            if isinstance(item, Mapping) and isinstance(item.get("label"), str)
        }
        candidate_labels = {
            item.get("label")
            for item in candidate.get("alternative_labels", [])
            if isinstance(item, Mapping) and isinstance(item.get("label"), str)
        }
        newly_available = coverage["newly_available_alternative_labels"]
        if not all(label not in baseline_labels and label in candidate_labels for label in newly_available):
            raise ValueError(f"coverage labels do not match paired candidate pools for review_id {review_id}")
        selected_baseline.append(baseline)
        selected_candidate.append(candidate)
        by_parent[str(coverage["target_parent_path"])] += 1
        labels.extend(newly_available)

    baseline_output_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_output_path.parent.mkdir(parents=True, exist_ok=True)
    with baseline_output_path.open("x", encoding="utf-8") as output:
        for row in selected_baseline:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    with candidate_output_path.open("x", encoding="utf-8") as output:
        for row in selected_candidate:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {
        "schema_version": SCHEMA_VERSION,
        "baseline_packet": str(baseline_packet),
        "candidate_packet": str(candidate_packet),
        "coverage_packet": str(coverage_packet),
        "baseline_output_path": str(baseline_output_path),
        "candidate_output_path": str(candidate_output_path),
        "selected_rows": len(selected_ids),
        "selected_review_ids": selected_ids,
        "selected_rows_by_target_parent": dict(sorted(by_parent.items())),
        "newly_available_labels": sorted(set(labels)),
    }
