"""Validate and summarize blinded reviewer results for one P0 diagnosis run."""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Mapping


BLIND_SCHEMA_VERSION = "p0-direct-diagnosis-blind-review-v1"
AUDIT_SCHEMA_VERSION = "p0-direct-diagnosis-audit-v1"
_DECISIONS = ("keep", "remove", "uncertain")


def _read_jsonl(path: Path, *, source: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{source} line {line_number}: invalid JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"{source} line {line_number}: JSONL row must be an object")
            rows.append(row)
    return rows


def _string(value: object, *, field: str, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: {field} must be a non-empty string")
    return value.strip()


def _count_decisions(rows: list[dict[str, object]]) -> dict[str, int]:
    counts = Counter(str(row["decision"]) for row in rows)
    return {decision: counts[decision] for decision in _DECISIONS}


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _blind_review_ids(path: Path, *, expected_set: str) -> set[str]:
    ids: set[str] = set()
    for index, row in enumerate(_read_jsonl(path, source=expected_set), 1):
        source = f"{expected_set} row {index}"
        if row.get("schema_version") != BLIND_SCHEMA_VERSION:
            raise ValueError(f"{source}: unexpected schema_version")
        review_id = _string(row.get("review_id"), field="review_id", source=source)
        if review_id in ids:
            raise ValueError(f"{source}: duplicate review_id {review_id!r}")
        ids.add(review_id)
    return ids


def _audit_rows(path: Path, *, expected_ids: set[str]) -> dict[str, dict[str, object]]:
    by_id: dict[str, dict[str, object]] = {}
    for index, row in enumerate(_read_jsonl(path, source="audit index"), 1):
        source = f"audit index row {index}"
        if row.get("schema_version") != AUDIT_SCHEMA_VERSION:
            raise ValueError(f"{source}: unexpected schema_version")
        review_id = _string(row.get("review_id"), field="review_id", source=source)
        review_set = row.get("review_set")
        if review_set not in {"true", "false"}:
            raise ValueError(f"{source}: review_set must be 'true' or 'false'")
        if review_id in by_id:
            raise ValueError(f"{source}: duplicate review_id {review_id!r}")
        by_id[review_id] = row
    missing = expected_ids - set(by_id)
    unexpected = set(by_id) - expected_ids
    if missing or unexpected:
        details = sorted(missing or unexpected)
        raise ValueError(f"audit index review_id mismatch: {details[0]}")
    return by_id


def _review_rows(path: Path, *, expected_ids: set[str]) -> dict[str, dict[str, object]]:
    by_id: dict[str, dict[str, object]] = {}
    for index, row in enumerate(_read_jsonl(path, source="reviewer results"), 1):
        source = f"reviewer results row {index}"
        review_id = _string(row.get("review_id"), field="review_id", source=source)
        decision = row.get("decision")
        if decision not in _DECISIONS:
            raise ValueError(f"{source}: decision must be one of {', '.join(_DECISIONS)}")
        _string(row.get("reason"), field="reason", source=source)
        if review_id in by_id:
            raise ValueError(f"{source}: duplicate review_id {review_id!r}")
        by_id[review_id] = row
    missing = expected_ids - set(by_id)
    unexpected = set(by_id) - expected_ids
    if missing:
        raise ValueError(f"missing review results: {sorted(missing)[0]}")
    if unexpected:
        raise ValueError(f"unexpected review result: {sorted(unexpected)[0]}")
    return by_id


def _route_name(row: Mapping[str, object]) -> str:
    route = row.get("route_key")
    if not isinstance(route, Mapping):
        raise ValueError("audit index route_key must be an object")
    return " × ".join(
        _string(route.get(key), field=f"route_key.{key}", source="audit index")
        for key in ("scope", "declared_type_structure", "declared_type_name")
    )


def _group_decisions(
    rows: list[dict[str, object]], *, grouping: str
) -> dict[str, dict[str, int]]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        if grouping == "route":
            key = _route_name(row)
        elif grouping == "suggestion_family":
            value = row.get("suggestion_family")
            key = value.strip() if isinstance(value, str) and value.strip() else "<none>"
        else:
            raise AssertionError(f"unsupported grouping: {grouping}")
        grouped[key][str(row["decision"])] += 1
    return {
        key: {decision: counts[decision] for decision in _DECISIONS}
        for key, counts in sorted(grouped.items())
    }


def _summarize(review_set: str, rows: list[dict[str, object]]) -> dict[str, object]:
    decisions = _count_decisions(rows)
    decidable = decisions["keep"] + decisions["remove"]
    summary: dict[str, object] = {
        "reviewed_records": len(rows),
        "decisions": decisions,
        "decidable_records": decidable,
        "keep_rate_excluding_uncertain": _rate(decisions["keep"], decidable),
        "by_route": _group_decisions(rows, grouping="route"),
    }
    if review_set == "false":
        summary["conditional_retain_rate_excluding_uncertain"] = _rate(decisions["keep"], decidable)
        summary["by_suggestion_family"] = _group_decisions(rows, grouping="suggestion_family")
    return summary


def analyze_p0_direct_diagnosis_reviews(
    true_packet_path: Path,
    *,
    false_packet_path: Path,
    audit_index_path: Path,
    reviewer_results_path: Path,
) -> dict[str, object]:
    """Join a complete blinded review result with its P0 packet audit index.

    The false packet is deliberately stratified. Its retention rate is therefore
    reported only as a conditional rate within this reviewed packet and must not
    be interpreted as the full-label false-negative rate.
    """
    true_ids = _blind_review_ids(true_packet_path, expected_set="true blind packet")
    false_ids = _blind_review_ids(false_packet_path, expected_set="false blind packet")
    if true_ids & false_ids:
        raise ValueError(f"true and false blind packets overlap: {sorted(true_ids & false_ids)[0]}")
    expected_ids = true_ids | false_ids
    audit = _audit_rows(audit_index_path, expected_ids=expected_ids)
    reviewer = _review_rows(reviewer_results_path, expected_ids=expected_ids)

    joined: dict[str, list[dict[str, object]]] = {"true": [], "false": []}
    for review_id in sorted(expected_ids):
        audit_row = audit[review_id]
        review_set = str(audit_row["review_set"])
        expected_set = "true" if review_id in true_ids else "false"
        if review_set != expected_set:
            raise ValueError(f"audit index review_set mismatch for {review_id}")
        joined[review_set].append({**audit_row, **reviewer[review_id]})

    true_summary = _summarize("true", joined["true"])
    false_summary = _summarize("false", joined["false"])
    release_status = (
        "silver_candidate_true_set_only"
        if true_summary["decisions"]["remove"] == 0 and true_summary["decisions"]["uncertain"] == 0
        else "hold_true_review_has_non_keep"
    )
    return {
        "schema_version": "p0-direct-diagnosis-review-analysis-v1",
        "true_packet_path": str(true_packet_path),
        "false_packet_path": str(false_packet_path),
        "audit_index_path": str(audit_index_path),
        "reviewer_results_path": str(reviewer_results_path),
        "reviewed_records": len(expected_ids),
        "true_set": true_summary,
        "false_set": false_summary,
        "release_status": release_status,
        "note": "false packet is stratified; its conditional retain rate is not a full-label rate",
    }
