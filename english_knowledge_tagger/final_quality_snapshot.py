"""Build an offline quality snapshot from final-label evidence and a repaired source."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Iterable, Mapping

from .knowledge_rulebook import load_knowledge_rulebook
from .knowledge_taxonomy_migration import KnowledgeTaxonomyMigration, load_knowledge_taxonomy_migration
from .input_completeness import INPUT_STATUS_VALUES, LLM_INPUT_STATUS_VALUES
from .sft_labels import parse_sft_output_labels


SNAPSHOT_SCHEMA_VERSION = "final-quality-snapshot-v1"
QUESTION_CANDIDATE_SCHEMA_VERSION = "silver-question-candidate-unreleased-v1"
HOLD_SCHEMA_VERSION = "final-quality-hold-v1"
EVIDENCE_SCHEMA_VERSION = "terminal-label-discriminator-evidence-v1"


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _identity(row: Mapping[str, object]) -> tuple[str, str, int] | None:
    question_id = _text(row.get("question_id"))
    parent_id = _text(row.get("parent_id"))
    is_sub_question = row.get("is_sub_question")
    if question_id is None or parent_id is None or not isinstance(is_sub_question, bool):
        return None
    return question_id, parent_id, int(is_sub_question)


def _canonical_history(
    output: object, *, migration: KnowledgeTaxonomyMigration
) -> tuple[str, ...] | None:
    parsed = parse_sft_output_labels(output)
    if parsed is None:
        return None
    labels, _ = parsed
    canonical: set[str] = set()
    for label in labels:
        if not label.startswith("知识点@"):
            continue
        canonical.add(
            migration.canonicalize(
                "知识点->" + label.removeprefix("知识点@").replace("@", "->")
            ).canonical_path
        )
    return tuple(sorted(canonical))


def _write_jsonl(handle: object, row: Mapping[str, object]) -> None:
    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")  # type: ignore[attr-defined]


def _create_index(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE evidence (
            question_id TEXT NOT NULL,
            parent_id TEXT NOT NULL,
            is_sub_question INTEGER NOT NULL,
            canonical_label TEXT NOT NULL,
            legacy_label TEXT NOT NULL,
            status TEXT NOT NULL,
            llm_match INTEGER,
            confidence TEXT,
            input_precheck_status TEXT,
            llm_input_status TEXT,
            review_id TEXT NOT NULL,
            source_path TEXT NOT NULL
        );
        CREATE INDEX evidence_lookup
            ON evidence(question_id, parent_id, is_sub_question, canonical_label);
        CREATE TABLE source_identity (
            question_id TEXT NOT NULL,
            parent_id TEXT NOT NULL,
            is_sub_question INTEGER NOT NULL,
            count INTEGER NOT NULL,
            PRIMARY KEY(question_id, parent_id, is_sub_question)
        );
        """
    )


def _iter_jsonl(path: Path) -> Iterable[tuple[int, dict[str, object]]]:
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path} line {line_number}: invalid JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"{path} line {line_number}: row must be an object")
            yield line_number, row


def _load_evidence(
    connection: sqlite3.Connection,
    run_dirs: tuple[Path, ...],
    *,
    excluded_labels: frozenset[str],
) -> tuple[Counter[str], set[str], int]:
    counts: Counter[str] = Counter()
    labels: set[str] = set()
    records = 0
    insert_rows: list[tuple[object, ...]] = []
    for run_dir in run_dirs:
        for evidence_path in sorted(run_dir.glob("labels/*/evidence.jsonl")):
            for line_number, row in _iter_jsonl(evidence_path):
                origin = f"{evidence_path} line {line_number}"
                if row.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
                    raise ValueError(f"{origin}: unexpected evidence schema_version")
                identity = _identity(row)
                canonical_label = _text(row.get("canonical_label"))
                legacy_label = _text(row.get("legacy_label"))
                status = _text(row.get("status"))
                review_id = _text(row.get("review_id"))
                if identity is None or canonical_label is None or legacy_label is None or status is None or review_id is None:
                    raise ValueError(f"{origin}: missing evidence identity or label fields")
                if status not in {"candidate", "error"}:
                    raise ValueError(f"{origin}: unsupported evidence status {status!r}")
                llm_match = row.get("llm_match")
                if llm_match is not None and not isinstance(llm_match, bool):
                    raise ValueError(f"{origin}: llm_match must be boolean or null")
                confidence = row.get("confidence")
                if confidence is not None and not isinstance(confidence, str):
                    raise ValueError(f"{origin}: confidence must be a string or null")
                input_precheck = row.get("input_precheck")
                input_precheck_status = None
                if input_precheck is not None:
                    if not isinstance(input_precheck, Mapping):
                        raise ValueError(f"{origin}: input_precheck must be an object or null")
                    input_precheck_status = input_precheck.get("status")
                    if input_precheck_status not in INPUT_STATUS_VALUES:
                        raise ValueError(
                            f"{origin}: unsupported input_precheck status {input_precheck_status!r}"
                        )
                llm_input_status = row.get("llm_input_status")
                if llm_input_status is not None and llm_input_status not in LLM_INPUT_STATUS_VALUES:
                    raise ValueError(f"{origin}: unsupported llm_input_status {llm_input_status!r}")
                labels.add(canonical_label)
                records += 1
                counts["evidence_records"] += 1
                counts[f"evidence_status:{status}"] += 1
                if llm_match is True:
                    counts["positive_evidence"] += 1
                    counts[f"positive_confidence:{confidence or 'missing'}"] += 1
                elif llm_match is False:
                    counts["negative_evidence"] += 1
                if input_precheck_status is not None:
                    counts[f"input_precheck:{input_precheck_status}"] += 1
                if llm_input_status is not None:
                    counts[f"llm_input_status:{llm_input_status}"] += 1
                if canonical_label in excluded_labels:
                    counts["excluded_label_evidence"] += 1
                insert_rows.append(
                    (
                        identity[0],
                        identity[1],
                        identity[2],
                        canonical_label,
                        legacy_label,
                        status,
                        None if llm_match is None else int(llm_match),
                        confidence,
                        input_precheck_status,
                        llm_input_status,
                        review_id,
                        str(evidence_path),
                    )
                )
                if len(insert_rows) >= 10_000:
                    connection.executemany(
                        "INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        insert_rows,
                    )
                    connection.commit()
                    insert_rows.clear()
    if insert_rows:
        connection.executemany(
            "INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            insert_rows,
        )
        connection.commit()
    return counts, labels, records


def _index_source(connection: sqlite3.Connection, source_path: Path) -> tuple[int, str, Counter[str]]:
    total = 0
    digest = hashlib.sha256()
    counts: Counter[str] = Counter()
    pending: list[tuple[str, str, int]] = []
    with source_path.open("rb") as source:
        for source_line, raw_line in enumerate(source, 1):
            digest.update(raw_line)
            if not raw_line.strip():
                continue
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{source_path} line {source_line}: invalid JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"{source_path} line {source_line}: row must be an object")
            total += 1
            identity = _identity(row)
            if identity is None:
                counts["source_identity_missing"] += 1
                continue
            pending.append(identity)
            if len(pending) >= 10_000:
                connection.executemany(
                    "INSERT INTO source_identity VALUES (?, ?, ?, 1) "
                    "ON CONFLICT(question_id, parent_id, is_sub_question) "
                    "DO UPDATE SET count=count+1",
                    pending,
                )
                connection.commit()
                pending.clear()
    if pending:
        connection.executemany(
            "INSERT INTO source_identity VALUES (?, ?, ?, 1) "
            "ON CONFLICT(question_id, parent_id, is_sub_question) "
            "DO UPDATE SET count=count+1",
            pending,
        )
        connection.commit()
    return total, digest.hexdigest(), counts


def build_final_quality_snapshot(
    *,
    run_dir: Path | None = None,
    run_dirs: Iterable[Path] | None = None,
    source_path: Path,
    output_dir: Path,
    excluded_labels: Iterable[str],
    teacher_csv: Path,
    taxonomy_migration: Path,
) -> dict[str, object]:
    """Join completed evidence to a repaired source and emit unreleased candidates/holds."""
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing snapshot directory: {output_dir}")
    selected_run_dirs = tuple(run_dirs or ())
    if run_dir is not None:
        selected_run_dirs = (run_dir,) + selected_run_dirs
    if not selected_run_dirs or any(not path.is_dir() for path in selected_run_dirs):
        raise FileNotFoundError("at least one run_dir must exist and be a directory")
    if not source_path.is_file():
        raise FileNotFoundError("source_path must exist and be a file")
    excluded_raw = frozenset(label.strip() for label in excluded_labels if label.strip())
    rulebook = load_knowledge_rulebook(teacher_csv)
    migration = load_knowledge_taxonomy_migration(taxonomy_migration)
    excluded: set[str] = set(excluded_raw)
    for label in excluded_raw:
        if label.startswith("知识点@"):
            excluded.add(
                migration.canonicalize(
                    "知识点->" + label.removeprefix("知识点@").replace("@", "->")
                ).canonical_path
            )
    excluded = frozenset(excluded)
    output_dir.mkdir(parents=True)
    index_path = output_dir / "snapshot.sqlite3"
    connection = sqlite3.connect(index_path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=OFF")
    _create_index(connection)
    evidence_counts, evidence_labels, evidence_records = _load_evidence(
        connection, selected_run_dirs, excluded_labels=excluded
    )
    source_records, source_sha256, source_counts = _index_source(connection, source_path)

    candidates_path = output_dir / "question_candidates.jsonl"
    holds_path = output_dir / "holds.jsonl"
    candidates = holds = 0
    output_counts: Counter[str] = Counter()
    with candidates_path.open("x", encoding="utf-8") as candidates_file, holds_path.open("x", encoding="utf-8") as holds_file:
        for source_line, row in _iter_jsonl(source_path):
            identity = _identity(row)
            base_hold = {
                "schema_version": HOLD_SCHEMA_VERSION,
                "source_line": source_line,
                "question_id": row.get("question_id"),
                "parent_id": row.get("parent_id"),
                "is_sub_question": row.get("is_sub_question"),
            }
            if identity is None:
                _write_jsonl(holds_file, {**base_hold, "hold_reason": "source_identity_missing"})
                holds += 1
                output_counts["source_identity_missing"] += 1
                continue
            source_count = connection.execute(
                "SELECT count FROM source_identity WHERE question_id=? AND parent_id=? AND is_sub_question=?",
                identity,
            ).fetchone()[0]
            if source_count != 1:
                _write_jsonl(holds_file, {**base_hold, "hold_reason": "source_duplicate_identity", "identity_count": source_count})
                holds += 1
                output_counts["source_duplicate_identity"] += 1
                continue
            historical_labels = _canonical_history(row.get("output"), migration=migration)
            if historical_labels is None:
                _write_jsonl(holds_file, {**base_hold, "hold_reason": "source_output_not_rendered_labels"})
                holds += 1
                output_counts["source_output_not_rendered_labels"] += 1
                continue
            if not historical_labels:
                _write_jsonl(holds_file, {**base_hold, "hold_reason": "no_historical_knowledge_labels", "historical_labels": []})
                holds += 1
                output_counts["no_historical_knowledge_labels"] += 1
                continue

            inactive = tuple(label for label in historical_labels if label not in rulebook.records or rulebook.records[label].status != "active")
            excluded_found = tuple(label for label in historical_labels if label in excluded)
            missing: list[str] = []
            not_positive: list[str] = []
            input_ineligible: list[str] = []
            input_ineligible_reasons: dict[str, str] = {}
            conflicts: list[str] = []
            approved: dict[str, list[str]] = {}
            for label in historical_labels:
                if label in excluded:
                    continue
                rows = connection.execute(
                    "SELECT status,llm_match,confidence,input_precheck_status,llm_input_status,review_id FROM evidence "
                    "WHERE question_id=? AND parent_id=? AND is_sub_question=? AND canonical_label=?",
                    (*identity, label),
                ).fetchall()
                if not rows:
                    missing.append(label)
                    continue
                if len(rows) != 1:
                    conflicts.append(label)
                    continue
                (
                    status,
                    llm_match,
                    confidence,
                    input_precheck_status,
                    llm_input_status,
                    review_id,
                ) = rows[0]
                if status != "candidate" or llm_match != 1:
                    not_positive.append(label)
                    continue
                if input_precheck_status in {
                    "insufficient",
                    "parent_context_only",
                    "audio_or_image_missing",
                    "sibling_mapping_ambiguous",
                }:
                    input_ineligible.append(label)
                    input_ineligible_reasons[label] = (
                        "input_ambiguous"
                        if input_precheck_status == "sibling_mapping_ambiguous"
                        else "input_insufficient"
                    )
                    continue
                if llm_input_status in {"insufficient", "ambiguous"}:
                    input_ineligible.append(label)
                    input_ineligible_reasons[label] = (
                        "input_ambiguous"
                        if llm_input_status == "ambiguous"
                        else "input_insufficient"
                    )
                    continue
                approved[label] = [review_id]

            if inactive or excluded_found or missing or not_positive or input_ineligible or conflicts:
                reasons: list[str] = []
                if inactive:
                    reasons.append("historical_label_not_active_taxonomy")
                if excluded_found:
                    reasons.append("label_excluded")
                if missing:
                    reasons.append("missing_label_evidence")
                if not_positive:
                    reasons.append("label_evidence_not_positive")
                if input_ineligible:
                    reasons.append(input_ineligible_reasons[input_ineligible[0]])
                if conflicts:
                    reasons.append("evidence_identity_conflict")
                _write_jsonl(
                    holds_file,
                    {
                        **base_hold,
                        "hold_reason": reasons[0],
                        "hold_reasons": reasons,
                        "historical_labels": list(historical_labels),
                        "inactive_labels": list(inactive),
                        "excluded_labels": list(excluded_found),
                        "missing_labels": sorted(missing),
                        "not_positive_labels": sorted(not_positive),
                        "input_ineligible_labels": sorted(input_ineligible),
                        "input_ineligible_reasons": {
                            label: input_ineligible_reasons[label]
                            for label in sorted(input_ineligible_reasons)
                        },
                        "conflict_labels": sorted(conflicts),
                    },
                )
                holds += 1
                output_counts[reasons[0]] += 1
                continue

            _write_jsonl(
                candidates_file,
                {
                    "schema_version": QUESTION_CANDIDATE_SCHEMA_VERSION,
                    "status": "silver_question_candidate_unreleased",
                    "source_line": source_line,
                    "question_id": identity[0],
                    "parent_id": identity[1],
                    "is_sub_question": bool(identity[2]),
                    "historical_labels": list(historical_labels),
                    "approved_evidence_review_ids": approved,
                    "source_path": str(source_path),
                    "source_record": row,
                },
            )
            candidates += 1
            output_counts["silver_question_candidate_unreleased"] += 1
    connection.close()

    report = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "run_dir": str(selected_run_dirs[0]),
        "run_dirs": [str(path) for path in selected_run_dirs],
        "source_path": str(source_path),
        "source_sha256": source_sha256,
        "teacher_csv": str(teacher_csv),
        "taxonomy_migration": str(taxonomy_migration),
        "excluded_labels": sorted(excluded_raw),
        "evidence_labels": sorted(evidence_labels),
        "evidence_records": evidence_records,
        "source_records": source_records,
        "question_candidates": candidates,
        "holds": holds,
        "evidence_counts": dict(sorted(evidence_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
        "output_counts": dict(sorted(output_counts.items())),
        "outputs": {
            "index": str(index_path),
            "question_candidates": str(candidates_path),
            "holds": str(holds_path),
        },
    }
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report
