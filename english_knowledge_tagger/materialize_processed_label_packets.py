"""Materialize per-label DS-positive packets from a final evidence snapshot."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable

from .knowledge_taxonomy_migration import KnowledgeTaxonomyMigration


PACKET_SCHEMA_VERSION = "processed-label-packet-v1"
REPORT_SCHEMA_VERSION = "processed-label-packets-report-v1"
INDEX_SCHEMA_VERSION = "processed-label-index-v1"
_INELIGIBLE_PRECHECK = frozenset(
    {"insufficient", "parent_context_only", "audio_or_image_missing", "sibling_mapping_ambiguous"}
)


def _identity(row: dict[str, object]) -> tuple[str, str, bool] | None:
    question_id = row.get("question_id")
    parent_id = row.get("parent_id")
    sub = row.get("is_sub_question")
    if not isinstance(question_id, str) or not question_id.strip():
        return None
    if not isinstance(parent_id, str) or not parent_id.strip():
        return None
    if not isinstance(sub, bool):
        return None
    return question_id.strip(), parent_id.strip(), sub


def _canonical_legacy(label: str, migration: KnowledgeTaxonomyMigration) -> str:
    return migration.canonicalize(
        "知识点->" + label.removeprefix("知识点@").replace("@", "->")
    ).canonical_path


def _normalize_excluded(
    labels: Iterable[str], migration: KnowledgeTaxonomyMigration
) -> frozenset[str]:
    normalized: set[str] = set()
    for value in labels:
        value = value.strip()
        if not value:
            continue
        if value.startswith("知识点@"):
            normalized.add(_canonical_legacy(value, migration))
        elif value.startswith("知识点->"):
            normalized.add(migration.canonicalize(value).canonical_path)
        else:
            raise ValueError(f"excluded label must start with 知识点@ or 知识点->: {value}")
    return frozenset(normalized)


def _write(handle: Any, row: dict[str, object]) -> None:
    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _safe_full_label(legacy_label: str) -> str:
    """Keep the complete rendered label readable and filesystem-safe."""
    replacements = {
        "/": "／",
        "\\": "＼",
        ":": "：",
        "*": "＊",
        "?": "？",
        '"': "＂",
        "<": "＜",
        ">": "＞",
        "|": "｜",
    }
    safe = "".join(replacements.get(char, "_" if ord(char) < 32 else char) for char in legacy_label)
    safe = safe.strip() or "label"
    # Linux allows 255 bytes per component. Leave room for the prefix,
    # sequence number and suffix while preserving the beginning of the label.
    return safe[:180]


def _read_evidence(
    connection: sqlite3.Connection, *, excluded: frozenset[str]
) -> tuple[
    set[str],
    dict[str, str],
    dict[tuple[str, str, bool], dict[str, list[dict[str, object]]]],
    set[tuple[str, str, bool]],
    Counter[str],
]:
    try:
        cursor = connection.execute(
            "SELECT question_id,parent_id,is_sub_question,canonical_label,legacy_label,status,"
            "llm_match,confidence,input_precheck_status,llm_input_status,review_id FROM evidence"
        )
    except sqlite3.OperationalError as error:
        raise ValueError("snapshot database has no compatible evidence table") from error

    labels: set[str] = set()
    label_names: dict[str, str] = {}
    grouped: dict[tuple[str, str, bool], dict[str, list[dict[str, object]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    counts: Counter[str] = Counter()
    for row in cursor:
        (
            question_id,
            parent_id,
            is_sub_question,
            canonical_label,
            legacy_label,
            status,
            llm_match,
            confidence,
            input_precheck_status,
            llm_input_status,
            review_id,
        ) = row
        label = str(canonical_label)
        if label in excluded:
            counts["excluded_evidence_records"] += 1
            continue
        labels.add(label)
        label_names.setdefault(label, str(legacy_label))
        identity = (str(question_id), str(parent_id), bool(is_sub_question))
        evidence = {
            "status": str(status),
            "llm_match": llm_match == 1,
            "confidence": confidence,
            "input_precheck_status": input_precheck_status,
            "llm_input_status": llm_input_status,
            "review_id": str(review_id),
            "legacy_label": str(legacy_label),
        }
        grouped[identity][label].append(evidence)
        counts["evidence_records"] += 1
        if status == "candidate" and llm_match == 1:
            counts["positive_evidence_records"] += 1
        elif status == "candidate" and llm_match == 0:
            counts["negative_evidence_records"] += 1
        elif status != "candidate":
            counts["non_candidate_evidence"] += 1

    duplicate_identities: set[tuple[str, str, bool]] = set()
    try:
        for row in connection.execute(
            "SELECT question_id,parent_id,is_sub_question FROM source_identity WHERE count != 1"
        ):
            duplicate_identities.add((str(row[0]), str(row[1]), bool(row[2])))
    except sqlite3.OperationalError:
        # Older snapshots may not have the source index. The source scan still
        # detects duplicate identities encountered in the selected subset.
        pass
    return labels, label_names, {identity: dict(by_label) for identity, by_label in grouped.items()}, duplicate_identities, counts


def materialize_processed_label_packets(
    *,
    snapshot_db: Path,
    source_path: Path,
    output_dir: Path,
    migration: KnowledgeTaxonomyMigration,
    excluded_labels: Iterable[str] = (),
    expected_label_count: int = 138,
) -> dict[str, object]:
    """Write one readable packet file per processed label.

    A packet contains the v3 source row plus exactly one complete positive
    final-discriminator evidence row. False, error, incomplete, duplicate, or
    contradictory evidence is not materialized. The output is an audit packet,
    not the merged training file; use ``train.jsonl`` for joint SFT examples.
    """
    if not snapshot_db.is_file():
        raise FileNotFoundError(f"snapshot database not found: {snapshot_db}")
    if not source_path.is_file():
        raise FileNotFoundError(f"source file not found: {source_path}")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    excluded = _normalize_excluded(excluded_labels, migration)

    connection = sqlite3.connect(snapshot_db)
    try:
        labels, label_names, evidence_by_identity, duplicate_identities, evidence_counts = _read_evidence(
            connection, excluded=excluded
        )
    finally:
        connection.close()
    if len(labels) != expected_label_count:
        raise ValueError(
            f"expected {expected_label_count} non-excluded evidence labels, found {len(labels)}"
        )

    # Build the selected identity map only after checking each label has one
    # and only one positive, input-eligible evidence record.
    selected: dict[tuple[str, str, bool], list[tuple[str, dict[str, object]]]] = defaultdict(list)
    conflicts = 0
    for identity, by_label in evidence_by_identity.items():
        for label, rows in by_label.items():
            if len(rows) != 1:
                conflicts += 1
                continue
            evidence = rows[0]
            if evidence["status"] != "candidate" or evidence["llm_match"] is not True:
                continue
            if (
                evidence["input_precheck_status"] in _INELIGIBLE_PRECHECK
                or evidence["llm_input_status"] in {"insufficient", "ambiguous"}
            ):
                continue
            selected[identity].append((label, evidence))

    sorted_labels = sorted(labels)
    label_files = {
        label: f"有质-{index:03d}-{_safe_full_label(label_names.get(label, label))}.jsonl"
        for index, label in enumerate(sorted_labels, 1)
    }
    index_payload: dict[str, object] = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "expected_label_count": expected_label_count,
        "labels": {
            label: {
                "filename": label_files[label],
                "canonical_label": label,
                "legacy_label": label_names.get(label),
                "record_count": 0,
            }
            for label in sorted_labels
        },
    }
    handles = {
        label: (output_dir / label_files[label]).open("x", encoding="utf-8")
        for label in sorted_labels
    }
    missing: set[tuple[str, str, bool]] = set(selected)
    seen_source: set[tuple[str, str, bool]] = set()
    source_records = 0
    output_records = 0
    duplicate_source_records = 0
    source_digest = hashlib.sha256()
    try:
        with source_path.open("rb") as raw_source:
            for source_line, raw_line in enumerate(raw_source, 1):
                source_digest.update(raw_line)
                if not raw_line.strip():
                    continue
                source_records += 1
                source_row = json.loads(raw_line)
                if not isinstance(source_row, dict):
                    raise ValueError(f"source line {source_line}: row must be an object")
                identity = _identity(source_row)
                if identity is None or identity not in selected:
                    continue
                if identity in seen_source or identity in duplicate_identities:
                    duplicate_source_records += 1
                    continue
                seen_source.add(identity)
                missing.discard(identity)
                for label, evidence in selected[identity]:
                    row = {
                        "schema_version": PACKET_SCHEMA_VERSION,
                        "status": "llm_match_true_input_eligible",
                        "verify_label": evidence["legacy_label"],
                        "canonical_label": label,
                        "question_id": identity[0],
                        "parent_id": identity[1],
                        "is_sub_question": identity[2],
                        "source_line": source_line,
                        "source_path": str(source_path),
                        "evidence": evidence,
                        "source_record": source_row,
                    }
                    _write(handles[label], row)
                    index_payload["labels"][label]["record_count"] += 1  # type: ignore[index]
                    output_records += 1
    finally:
        for handle in handles.values():
            handle.close()

    holds_path = output_dir / "holds.jsonl"
    with holds_path.open("x", encoding="utf-8") as holds:
        for identity in sorted(missing):
            _write(
                holds,
                {
                    "schema_version": "processed-label-packet-hold-v1",
                    "hold_reason": "selected_evidence_identity_missing_in_source",
                    "question_id": identity[0],
                    "parent_id": identity[1],
                    "is_sub_question": identity[2],
                },
            )
        for identity in sorted(duplicate_identities & set(selected)):
            _write(
                holds,
                {
                    "schema_version": "processed-label-packet-hold-v1",
                    "hold_reason": "source_duplicate_identity",
                    "question_id": identity[0],
                    "parent_id": identity[1],
                    "is_sub_question": identity[2],
                },
            )

    index_path = output_dir / "label_index.json"
    index_path.write_text(
        json.dumps(index_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    per_label_counts = {
        label: int(index_payload["labels"][label]["record_count"])  # type: ignore[index]
        for label in sorted_labels
    }
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "snapshot_db": str(snapshot_db),
        "source_path": str(source_path),
        "source_sha256": source_digest.hexdigest(),
        "output_dir": str(output_dir),
        "index_path": str(index_path),
        "holds_path": str(holds_path),
        "excluded_labels": sorted(excluded),
        "label_count": len(sorted_labels),
        "expected_label_count": expected_label_count,
        "eligible_positive_evidence": sum(len(items) for items in selected.values()),
        "output_records": output_records,
        "source_records": source_records,
        "missing_source_identity_count": len(missing),
        "duplicate_source_record_count": duplicate_source_records,
        "evidence_conflict_count": conflicts,
        "evidence_counts": dict(sorted(evidence_counts.items())),
        "per_label_record_counts": per_label_counts,
    }
