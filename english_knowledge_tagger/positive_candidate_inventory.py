"""One-pass route inventory for a non-releasing positive-candidate work queue."""

from __future__ import annotations

from collections import Counter
import hashlib
import heapq
import json
from pathlib import Path
import re
from typing import Any, Mapping

from .final_label_discriminator import clean_final_label_question
from .knowledge_rulebook import KnowledgeRulebook
from .knowledge_taxonomy_migration import KnowledgeTaxonomyMigration
from .sft_labels import parse_sft_output_labels


INVENTORY_SCHEMA_VERSION = "positive-candidate-batch-inventory-v1"
ROUTE_SAMPLE_SCHEMA_VERSION = "positive-candidate-route-review-v1"
_TYPE_METADATA = re.compile(r"(?m)^\s*题型(结构|名称)为：([^\r\n]*)")


def _string(value: object, *, field: str, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: {field} must be a non-empty string")
    return value.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_manifest(path: Path) -> tuple[dict[str, str], frozenset[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"candidate manifest is not valid JSON: {path}") from error
    if not isinstance(payload, Mapping) or payload.get("schema_version") != "positive-candidate-manifest-v1":
        raise ValueError("candidate manifest has unexpected schema_version")
    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise ValueError("candidate manifest candidates must be a non-empty list")
    by_legacy: dict[str, str] = {}
    canonical_paths: set[str] = set()
    for index, item in enumerate(raw_candidates, 1):
        if not isinstance(item, Mapping):
            raise ValueError(f"candidate manifest candidates[{index}] must be an object")
        legacy_label = _string(
            item.get("legacy_label"), field="legacy_label", source=f"manifest candidate {index}"
        )
        canonical_label = _string(
            item.get("canonical_label"), field="canonical_label", source=f"manifest candidate {index}"
        )
        if not legacy_label.startswith("知识点@") or not canonical_label.startswith("知识点->"):
            raise ValueError(f"manifest candidate {index}: invalid rendered or canonical label path")
        if legacy_label in by_legacy:
            raise ValueError(f"candidate manifest duplicate legacy_label: {legacy_label}")
        if canonical_label in canonical_paths:
            raise ValueError(f"candidate manifest duplicate canonical_label: {canonical_label}")
        by_legacy[legacy_label] = canonical_label
        canonical_paths.add(canonical_label)
    return by_legacy, frozenset(canonical_paths)


def _route_key(record: Mapping[str, Any], *, source: str) -> dict[str, str | None]:
    input_text = record.get("input")
    if input_text is not None and not isinstance(input_text, str):
        raise ValueError(f"{source}: input must be a string or null")
    parsed = {
        match.group(1): match.group(2).strip()
        for match in _TYPE_METADATA.finditer(input_text or "")
    }
    is_sub_question = record.get("is_sub_question")
    if not isinstance(is_sub_question, bool):
        raise ValueError(f"{source}: is_sub_question must be boolean")
    return {
        "scope": "child" if is_sub_question else "parent",
        "declared_type_structure": parsed.get("结构") or None,
        "declared_type_name": parsed.get("名称") or None,
    }


def _route_name(route_key: Mapping[str, str | None]) -> str:
    return " × ".join(
        (
            route_key["scope"] or "<missing>",
            route_key["declared_type_structure"] or "<missing>",
            route_key["declared_type_name"] or "<missing>",
        )
    )


def _active_historical_labels(
    rendered_labels: frozenset[str],
    *,
    rulebook: KnowledgeRulebook,
    migration: KnowledgeTaxonomyMigration,
) -> frozenset[str]:
    active: set[str] = set()
    for rendered in rendered_labels:
        legacy_path = "知识点->" + rendered.removeprefix("知识点@").replace("@", "->")
        canonical = migration.canonicalize(legacy_path).canonical_path
        record = rulebook.records.get(canonical)
        if record is not None and record.status == "active":
            active.add(canonical)
    return frozenset(active)


def _initial_label_inventory(canonical_label: str) -> dict[str, Any]:
    return {
        "canonical_label": canonical_label,
        "matching_source_records": 0,
        "scope_counts": Counter(),
        "route_counts": Counter(),
        "coverage": {
            "all_active_labels_in_candidate_queue": 0,
            "has_active_labels_outside_candidate_queue": 0,
            "missing_active_label_counts": Counter(),
        },
        "question_text_unavailable_for_route_review": 0,
    }


def _sample_rank(*, seed: str, label: str, route: str, source_line: int) -> int:
    raw = f"{seed}\0{label}\0{route}\0{source_line}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest(), "big")


def _consider_sample(
    samples: dict[tuple[str, str], list[tuple[int, int, dict[str, Any]]]],
    *,
    label: str,
    route: str,
    source_line: int,
    row: dict[str, Any],
    sample_size: int,
    seed: str,
) -> None:
    key = (label, route)
    rank = _sample_rank(seed=seed, label=label, route=route, source_line=source_line)
    entry = (-rank, -source_line, row)
    bucket = samples.setdefault(key, [])
    if len(bucket) < sample_size:
        heapq.heappush(bucket, entry)
    elif entry > bucket[0]:
        heapq.heapreplace(bucket, entry)


def inventory_positive_candidate_batch(
    source_path: Path,
    *,
    manifest_path: Path,
    rulebook: KnowledgeRulebook,
    migration: KnowledgeTaxonomyMigration,
    inventory_output_path: Path,
    route_samples_output_path: Path,
    sample_size_per_route: int,
    seed: str,
) -> dict[str, object]:
    """Scan source exactly once; route eligibility stays deliberately unresolved."""
    if inventory_output_path.exists() or route_samples_output_path.exists():
        raise FileExistsError("refusing to overwrite existing candidate inventory or route samples")
    if sample_size_per_route <= 0:
        raise ValueError("sample_size_per_route must be positive")
    if not seed:
        raise ValueError("seed must be non-empty")
    candidates, candidate_canonical_labels = _load_manifest(manifest_path)
    candidate_legacy_labels = frozenset(candidates)
    inventory = {
        legacy_label: _initial_label_inventory(canonical_label)
        for legacy_label, canonical_label in candidates.items()
    }
    samples: dict[tuple[str, str], list[tuple[int, int, dict[str, Any]]]] = {}
    source_records = 0
    source_hasher = hashlib.sha256()
    with source_path.open("rb") as source:
        for source_line, raw_line in enumerate(source, 1):
            source_hasher.update(raw_line)
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError as error:
                raise ValueError(f"source line {source_line}: invalid JSON") from error
            if not isinstance(record, Mapping):
                raise ValueError(f"source line {source_line}: JSONL row must be an object")
            source_records += 1
            parsed_labels = parse_sft_output_labels(record.get("output"))
            if parsed_labels is None:
                continue
            historical_rendered, _ = parsed_labels
            matching_labels = tuple(sorted(historical_rendered & candidate_legacy_labels))
            if not matching_labels:
                continue
            origin = f"source line {source_line}"
            route_key = _route_key(record, source=origin)
            route = _route_name(route_key)
            active_historical = _active_historical_labels(
                historical_rendered, rulebook=rulebook, migration=migration
            )
            missing_active = active_historical - candidate_canonical_labels
            question_text: str | None
            try:
                question_text = clean_final_label_question(record.get("input"))
            except ValueError:
                question_text = None
            for label in matching_labels:
                label_inventory = inventory[label]
                label_inventory["matching_source_records"] += 1
                label_inventory["scope_counts"][route_key["scope"]] += 1
                label_inventory["route_counts"][route] += 1
                coverage = label_inventory["coverage"]
                if missing_active:
                    coverage["has_active_labels_outside_candidate_queue"] += 1
                    coverage["missing_active_label_counts"].update(missing_active)
                else:
                    coverage["all_active_labels_in_candidate_queue"] += 1
                if question_text is None:
                    label_inventory["question_text_unavailable_for_route_review"] += 1
                    continue
                review_row = {
                    "schema_version": ROUTE_SAMPLE_SCHEMA_VERSION,
                    "legacy_label": label,
                    "canonical_label": candidates[label],
                    "source_line": source_line,
                    "question_id": record.get("question_id"),
                    "parent_id": record.get("parent_id"),
                    "is_sub_question": record.get("is_sub_question"),
                    "route_key": route_key,
                    "route": route,
                    "question_text": question_text,
                    "all_active_labels_in_candidate_queue": not bool(missing_active),
                }
                _consider_sample(
                    samples,
                    label=label,
                    route=route,
                    source_line=source_line,
                    row=review_row,
                    sample_size=sample_size_per_route,
                    seed=seed,
                )
    serialised_labels: dict[str, dict[str, object]] = {}
    for label, details in inventory.items():
        coverage = details["coverage"]
        serialised_labels[label] = {
            "canonical_label": details["canonical_label"],
            "matching_source_records": details["matching_source_records"],
            "scope_counts": dict(sorted(details["scope_counts"].items())),
            "route_counts": dict(sorted(details["route_counts"].items())),
            "coverage": {
                "all_active_labels_in_candidate_queue": coverage[
                    "all_active_labels_in_candidate_queue"
                ],
                "has_active_labels_outside_candidate_queue": coverage[
                    "has_active_labels_outside_candidate_queue"
                ],
                "missing_active_label_counts": dict(
                    sorted(coverage["missing_active_label_counts"].items())
                ),
            },
            "question_text_unavailable_for_route_review": details[
                "question_text_unavailable_for_route_review"
            ],
        }
    inventory_payload = {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "purpose": "route_inventory_and_queue_coverage_forecast_only",
        "inputs": {
            "source_path": str(source_path),
            "source_sha256": source_hasher.hexdigest(),
            "manifest_path": str(manifest_path),
            "manifest_sha256": _sha256(manifest_path),
        },
        "sample_size_per_route": sample_size_per_route,
        "sample_seed": seed,
        "source_records": source_records,
        "labels": serialised_labels,
    }
    inventory_output_path.parent.mkdir(parents=True, exist_ok=True)
    route_samples_output_path.parent.mkdir(parents=True, exist_ok=True)
    inventory_output_path.write_text(
        json.dumps(inventory_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    route_sample_count = 0
    with route_samples_output_path.open("x", encoding="utf-8") as output:
        for _, bucket in sorted(samples.items()):
            for rank, source_line, row in sorted(
                ((-item[0], -item[1], item[2]) for item in bucket), key=lambda item: (item[0], item[1])
            ):
                del rank, source_line
                output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                route_sample_count += 1
    return {
        "schema_version": "positive-candidate-batch-inventory-report-v1",
        "source_records": source_records,
        "candidate_labels": len(candidates),
        "inventory_output_path": str(inventory_output_path),
        "route_samples_output_path": str(route_samples_output_path),
        "route_sample_records": route_sample_count,
    }
