"""Assemble conservative training candidates from positive final-label evidence."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable, Mapping

from .knowledge_rulebook import KnowledgeRulebook
from .knowledge_taxonomy_migration import KnowledgeTaxonomyMigration


EVIDENCE_SCHEMA_VERSION = "terminal-label-discriminator-evidence-v1"
TRAINING_SCHEMA_VERSION = "true-label-training-candidate-v1"
HOLD_SCHEMA_VERSION = "true-label-training-hold-v1"
_INELIGIBLE_PRECHECK = frozenset(
    {"insufficient", "parent_context_only", "audio_or_image_missing", "sibling_mapping_ambiguous"}
)


def _identity(row: Mapping[str, object]) -> tuple[str, str, bool] | None:
    question_id = row.get("question_id")
    parent_id = row.get("parent_id")
    is_sub_question = row.get("is_sub_question")
    if not isinstance(question_id, str) or not question_id.strip():
        return None
    if not isinstance(parent_id, str) or not parent_id.strip():
        return None
    if not isinstance(is_sub_question, bool):
        return None
    return question_id.strip(), parent_id.strip(), is_sub_question


def _canonical_legacy(label: str, migration: KnowledgeTaxonomyMigration) -> str:
    return migration.canonicalize(
        "知识点->" + label.removeprefix("知识点@").replace("@", "->")
    ).canonical_path


def _normalize_excluded(
    labels: Iterable[str], migration: KnowledgeTaxonomyMigration
) -> frozenset[str]:
    normalized: set[str] = set()
    for raw in labels:
        value = raw.strip()
        if not value:
            continue
        if value.startswith("知识点@"):
            normalized.add(_canonical_legacy(value, migration))
        elif value.startswith("知识点->"):
            normalized.add(migration.canonicalize(value).canonical_path)
        else:
            raise ValueError(f"excluded label must start with 知识点@ or 知识点->: {value}")
    return frozenset(normalized)


def _render_merged_output(
    output: object,
    *,
    keep_labels: frozenset[str],
    migration: KnowledgeTaxonomyMigration,
) -> str | None:
    if not isinstance(output, str):
        return None
    rendered: list[str] = []
    seen: set[str] = set()
    for fragment in re.split(r"[;；\n]+", output):
        value = fragment.strip()
        if not value:
            continue
        if value.startswith("知识点@"):
            canonical = _canonical_legacy(value, migration)
            if canonical in keep_labels and canonical not in seen:
                rendered.append(value)
                seen.add(canonical)
        elif value.startswith("题型@") and value not in seen:
            rendered.append(value)
            seen.add(value)
    return ";".join(rendered) if rendered else None


def _iter_jsonl(path: Path) -> Iterable[tuple[int, dict[str, object]]]:
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path} line {line_number}: row must be an object")
            yield line_number, row


def _write(handle: Any, row: Mapping[str, object]) -> None:
    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _load_evidence(
    snapshot_db: Path, *, excluded: frozenset[str]
) -> tuple[dict[tuple[str, str, bool], dict[str, list[dict[str, object]]]], Counter[str]]:
    if not snapshot_db.is_file():
        raise FileNotFoundError(f"snapshot database not found: {snapshot_db}")
    connection = sqlite3.connect(snapshot_db)
    try:
        try:
            rows = connection.execute(
                "SELECT question_id,parent_id,is_sub_question,canonical_label,legacy_label,status,"
                "llm_match,confidence,input_precheck_status,llm_input_status,review_id "
                "FROM evidence"
            )
        except sqlite3.OperationalError as error:
            raise ValueError(f"snapshot database has no compatible evidence table: {snapshot_db}") from error
        grouped: dict[tuple[str, str, bool], dict[str, list[dict[str, object]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        counts: Counter[str] = Counter()
        for row in rows:
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
            identity = (str(question_id), str(parent_id), bool(is_sub_question))
            label = str(canonical_label)
            counts["evidence_records"] += 1
            if label in excluded:
                counts["excluded_evidence_records"] += 1
                continue
            if status != "candidate":
                counts["non_candidate_evidence"] += 1
            elif llm_match == 1:
                counts["positive_evidence_records"] += 1
            elif llm_match == 0:
                counts["negative_evidence_records"] += 1
            grouped[identity][label].append(
                {
                    "status": status,
                    "llm_match": llm_match,
                    "confidence": confidence,
                    "input_precheck_status": input_precheck_status,
                    "llm_input_status": llm_input_status,
                    "review_id": str(review_id),
                    "legacy_label": str(legacy_label),
                }
            )
        return {identity: dict(labels) for identity, labels in grouped.items()}, counts
    finally:
        connection.close()


def build_true_label_training_data(
    *,
    snapshot_db: Path,
    source_path: Path,
    teacher_csv: Path,
    taxonomy_migration: Path,
    output_path: Path,
    provenance_path: Path,
    hold_output_path: Path,
    excluded_labels: Iterable[str] = (),
) -> dict[str, object]:
    """Write v3 source rows whose remaining historical labels all have true evidence.

    The explicitly excluded labels are removed from the merged output. A row is held when
    any remaining active historical label is missing, non-positive, or input-
    ineligible. The source row is otherwise copied verbatim except for its merged
    ``output`` field; provenance and holds are written separately.
    """
    if any(path.exists() for path in (output_path, provenance_path, hold_output_path)):
        raise FileExistsError("refusing to overwrite training, provenance, or hold output")
    if not source_path.is_file():
        raise FileNotFoundError(f"source file not found: {source_path}")

    from .knowledge_rulebook import load_knowledge_rulebook
    from .knowledge_taxonomy_migration import load_knowledge_taxonomy_migration

    rulebook: KnowledgeRulebook = load_knowledge_rulebook(teacher_csv)
    migration: KnowledgeTaxonomyMigration = load_knowledge_taxonomy_migration(taxonomy_migration)
    excluded = _normalize_excluded(excluded_labels, migration)
    evidence, evidence_counts = _load_evidence(snapshot_db, excluded=excluded)
    evidence_labels = sorted({label for labels in evidence.values() for label in labels})

    output_path.parent.mkdir(parents=True, exist_ok=True)
    provenance_path.parent.mkdir(parents=True, exist_ok=True)
    hold_output_path.parent.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    source_digest = hashlib.sha256()
    seen_identities: set[tuple[str, str, bool]] = set()

    with source_path.open("rb") as raw_source, output_path.open("x", encoding="utf-8") as output, provenance_path.open(
        "x", encoding="utf-8"
    ) as provenance, hold_output_path.open("x", encoding="utf-8") as holds:
        for source_line, raw_line in enumerate(raw_source, 1):
            source_digest.update(raw_line)
            if not raw_line.strip():
                continue
            counts["source_records"] += 1
            source_row = json.loads(raw_line)
            if not isinstance(source_row, dict):
                raise ValueError(f"source line {source_line}: row must be an object")
            identity = _identity(source_row)
            base = {
                "schema_version": HOLD_SCHEMA_VERSION,
                "source_line": source_line,
                "question_id": source_row.get("question_id"),
                "parent_id": source_row.get("parent_id"),
                "is_sub_question": source_row.get("is_sub_question"),
            }
            if identity is None:
                _write(holds, {**base, "hold_reason": "source_identity_missing"})
                counts["holds"] += 1
                counts["hold:source_identity_missing"] += 1
                continue
            if identity in seen_identities:
                _write(holds, {**base, "hold_reason": "source_duplicate_identity"})
                counts["holds"] += 1
                counts["hold:source_duplicate_identity"] += 1
                continue
            seen_identities.add(identity)

            parsed_output = source_row.get("output")
            if not isinstance(parsed_output, str):
                _write(holds, {**base, "hold_reason": "source_output_not_rendered_labels"})
                counts["holds"] += 1
                counts["hold:source_output_not_rendered_labels"] += 1
                continue
            raw_labels = [
                fragment.strip()
                for fragment in re.split(r"[;；\n]+", parsed_output)
                if fragment.strip().startswith("知识点@") and fragment.strip() != "知识点@空"
            ]
            historical_labels = tuple(
                sorted({_canonical_legacy(label, migration) for label in raw_labels})
            )
            if not historical_labels:
                _write(holds, {**base, "hold_reason": "no_historical_knowledge_labels", "historical_labels": []})
                counts["holds"] += 1
                counts["hold:no_historical_knowledge_labels"] += 1
                continue
            excluded_found = tuple(sorted(label for label in historical_labels if label in excluded))
            active_labels = tuple(label for label in historical_labels if label not in excluded)
            inactive = tuple(
                label
                for label in active_labels
                if label not in rulebook.records or rulebook.records[label].status != "active"
            )
            if inactive:
                _write(
                    holds,
                    {
                        **base,
                        "hold_reason": "historical_label_not_active_taxonomy",
                        "historical_labels": list(historical_labels),
                        "inactive_labels": list(inactive),
                    },
                )
                counts["holds"] += 1
                counts["hold:historical_label_not_active_taxonomy"] += 1
                continue
            if not active_labels:
                _write(
                    holds,
                    {
                        **base,
                        "hold_reason": "no_remaining_active_knowledge_labels",
                        "historical_labels": list(historical_labels),
                        "excluded_labels": list(excluded_found),
                    },
                )
                counts["holds"] += 1
                counts["hold:no_remaining_active_knowledge_labels"] += 1
                continue

            missing: list[str] = []
            not_positive: list[str] = []
            input_ineligible: list[str] = []
            evidence_conflicts: list[str] = []
            positive_review_ids: dict[str, list[str]] = {}
            for label in active_labels:
                label_rows = evidence.get(identity, {}).get(label, [])
                if len(label_rows) > 1:
                    # A duplicate or a candidate/error mixture is not an
                    # independently established truth value. Keep the row in
                    # holds rather than silently choosing one verdict.
                    evidence_conflicts.append(label)
                    continue
                positives = [row for row in label_rows if row["llm_match"] == 1]
                eligible = [
                    row
                    for row in positives
                    if row["input_precheck_status"] not in _INELIGIBLE_PRECHECK
                    and row["llm_input_status"] not in {"insufficient", "ambiguous"}
                ]
                if not label_rows:
                    missing.append(label)
                elif not positives:
                    not_positive.append(label)
                elif not eligible:
                    input_ineligible.append(label)
                else:
                    positive_review_ids[label] = sorted({row["review_id"] for row in eligible})
            if missing or not_positive or input_ineligible or evidence_conflicts:
                reasons: list[str] = []
                if missing:
                    reasons.append("missing_label_evidence")
                if not_positive:
                    reasons.append("label_evidence_not_positive")
                if input_ineligible:
                    reasons.append("input_insufficient")
                if evidence_conflicts:
                    reasons.append("evidence_identity_conflict")
                _write(
                    holds,
                    {
                        **base,
                        "hold_reason": reasons[0],
                        "hold_reasons": reasons,
                        "historical_labels": list(historical_labels),
                        "excluded_labels": list(excluded_found),
                        "missing_labels": sorted(missing),
                        "not_positive_labels": sorted(not_positive),
                        "input_ineligible_labels": sorted(input_ineligible),
                        "conflict_labels": sorted(evidence_conflicts),
                    },
                )
                counts["holds"] += 1
                for reason in reasons:
                    counts[f"hold:{reason}"] += 1
                continue

            merged_output = _render_merged_output(
                parsed_output, keep_labels=frozenset(active_labels), migration=migration
            )
            if merged_output is None:
                _write(holds, {**base, "hold_reason": "merged_output_empty"})
                counts["holds"] += 1
                counts["hold:merged_output_empty"] += 1
                continue

            training_row = dict(source_row)
            training_row["output"] = merged_output
            _write(output, training_row)
            _write(
                provenance,
                {
                    "schema_version": "true-label-training-provenance-v1",
                    "source_line": source_line,
                    "question_id": identity[0],
                    "parent_id": identity[1],
                    "is_sub_question": identity[2],
                    "positive_labels": list(active_labels),
                    "positive_evidence_review_ids": positive_review_ids,
                    "excluded_labels": list(excluded_found),
                    "original_output": parsed_output,
                    "merged_output": merged_output,
                },
            )
            counts["train_records"] += 1
            counts["positive_labels_used"] += len(active_labels)

    report = {
        "schema_version": TRAINING_SCHEMA_VERSION,
        "snapshot_db": str(snapshot_db),
        "source_path": str(source_path),
        "source_sha256": source_digest.hexdigest(),
        "teacher_csv": str(teacher_csv),
        "taxonomy_migration": str(taxonomy_migration),
        "excluded_labels": sorted(excluded),
        "evidence_label_count": len(evidence_labels),
        "evidence_labels": evidence_labels,
        "evidence_counts": dict(sorted(evidence_counts.items())),
        "counts": dict(sorted(counts.items())),
        # Keep the headline counts at the top level as well as in ``counts`` so
        # that shell checks and downstream manifests do not need to know the
        # internal counter layout.
        "source_records": counts["source_records"],
        "train_records": counts["train_records"],
        "hold_records": counts["holds"],
        "outputs": {
            "training": str(output_path),
            "provenance": str(provenance_path),
            "holds": str(hold_output_path),
        },
    }
    return report
