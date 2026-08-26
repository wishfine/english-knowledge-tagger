"""Compare frozen knowledge-validation packets without sending model requests."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "knowledge-candidate-pool-comparison-v1"


def _nonempty_string(value: object, *, field: str, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: {field} must be a non-empty string")
    return value.strip()


def _route_key(row: Mapping[str, Any], *, source: str) -> dict[str, str] | None:
    raw_route = row.get("route_key")
    if raw_route is None:
        return None
    if not isinstance(raw_route, Mapping):
        raise ValueError(f"{source}: route_key must be an object")
    return {
        field: _nonempty_string(raw_route.get(field), field=f"route_key.{field}", source=source)
        for field in ("scope", "declared_type_structure", "declared_type_name")
    }


def _sibling_labels(row: Mapping[str, Any], *, source: str) -> list[str]:
    raw_candidates = row.get("alternative_labels")
    if not isinstance(raw_candidates, list):
        raise ValueError(f"{source}: alternative_labels must be a list")
    labels: list[str] = []
    for index, candidate in enumerate(raw_candidates, 1):
        if not isinstance(candidate, Mapping):
            raise ValueError(f"{source}: alternative_labels[{index}] must be an object")
        if candidate.get("source") != "sibling":
            continue
        label = _nonempty_string(
            candidate.get("label"), field=f"alternative_labels[{index}].label", source=source
        )
        if label in labels:
            raise ValueError(f"{source}: duplicate sibling label: {label}")
        labels.append(label)
    return labels


def _packet_rows(path: Path) -> tuple[list[str], dict[str, dict[str, Any]]]:
    ordered_review_ids: list[str] = []
    rows: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            source = f"{path} line {line_number}"
            try:
                raw_row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{source}: invalid JSON") from error
            if not isinstance(raw_row, dict):
                raise ValueError(f"{source}: JSONL row must be an object")
            review_id = _nonempty_string(raw_row.get("review_id"), field="review_id", source=source)
            if review_id in rows:
                raise ValueError(f"{source}: duplicate review_id: {review_id}")
            canonical_label = _nonempty_string(
                raw_row.get("canonical_label"), field="canonical_label", source=source
            )
            parent_path, separator, _ = canonical_label.rpartition("->")
            if not separator:
                raise ValueError(f"{source}: canonical_label must have a taxonomy parent")
            rows[review_id] = {
                "review_id": review_id,
                "source_line": raw_row.get("source_line"),
                "question_id": raw_row.get("question_id"),
                "parent_id": raw_row.get("parent_id"),
                "route_key": _route_key(raw_row, source=source),
                "canonical_label": canonical_label,
                "target_parent_path": parent_path,
                "sibling_labels": _sibling_labels(raw_row, source=source),
                "candidate_pool": raw_row.get("candidate_pool"),
            }
            ordered_review_ids.append(review_id)
    return ordered_review_ids, rows


def _same_identity(baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> bool:
    return all(
        baseline[field] == candidate[field]
        for field in (
            "source_line",
            "question_id",
            "parent_id",
            "route_key",
            "canonical_label",
            "target_parent_path",
        )
    )


def compare_knowledge_candidate_pools(
    baseline_packet: Path, candidate_packet: Path, *, output_path: Path
) -> dict[str, object]:
    """Emit rows where candidate policy exposes additional direct sibling leaves."""
    if output_path.exists():
        raise FileExistsError(f"candidate-pool comparison output already exists: {output_path}")
    ordered_review_ids, baseline_rows = _packet_rows(baseline_packet)
    _, candidate_rows = _packet_rows(candidate_packet)
    baseline_ids = set(baseline_rows)
    candidate_ids = set(candidate_rows)
    if baseline_ids != candidate_ids:
        only_baseline = sorted(baseline_ids - candidate_ids)
        only_candidate = sorted(candidate_ids - baseline_ids)
        raise ValueError(
            "candidate-pool packets do not contain the same review_ids: "
            f"only_baseline={only_baseline[:3]}, only_candidate={only_candidate[:3]}"
        )

    rows: list[dict[str, object]] = []
    expanded_by_parent: Counter[str] = Counter()
    unchanged_rows = 0
    for review_id in ordered_review_ids:
        baseline = baseline_rows[review_id]
        candidate = candidate_rows[review_id]
        if not _same_identity(baseline, candidate):
            raise ValueError(f"candidate-pool packets disagree on immutable identity for review_id: {review_id}")
        baseline_siblings = baseline["sibling_labels"]
        candidate_siblings = candidate["sibling_labels"]
        baseline_paths = set(baseline_siblings)
        candidate_paths = set(candidate_siblings)
        removed = baseline_paths - candidate_paths
        if removed:
            raise ValueError(
                f"candidate packet removes baseline sibling labels for review_id {review_id}: "
                f"{sorted(removed)}"
            )
        newly_exposed = [path for path in candidate_siblings if path not in baseline_paths]
        if not newly_exposed:
            unchanged_rows += 1
            continue
        parent_path = str(baseline["target_parent_path"])
        expanded_by_parent[parent_path] += 1
        rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "review_id": review_id,
                "source_line": baseline["source_line"],
                "question_id": baseline["question_id"],
                "parent_id": baseline["parent_id"],
                "route_key": baseline["route_key"],
                "canonical_label": baseline["canonical_label"],
                "target_parent_path": parent_path,
                "baseline_sibling_labels": baseline_siblings,
                "candidate_sibling_labels": candidate_siblings,
                "newly_exposed_sibling_labels": newly_exposed,
                "baseline_sibling_count": len(baseline_siblings),
                "candidate_sibling_count": len(candidate_siblings),
                "baseline_candidate_pool": baseline["candidate_pool"],
                "candidate_candidate_pool": candidate["candidate_pool"],
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {
        "schema_version": SCHEMA_VERSION,
        "baseline_packet": str(baseline_packet),
        "candidate_packet": str(candidate_packet),
        "output_path": str(output_path),
        "matched_rows": len(ordered_review_ids),
        "expanded_rows": len(rows),
        "unchanged_rows": unchanged_rows,
        "expanded_rows_by_target_parent": dict(sorted(expanded_by_parent.items())),
    }
