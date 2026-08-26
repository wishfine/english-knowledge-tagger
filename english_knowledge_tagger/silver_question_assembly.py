"""Assemble conservative silver question candidates from released label evidence."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .knowledge_rulebook import KnowledgeRulebook
from .knowledge_taxonomy_migration import KnowledgeTaxonomyMigration
from .sft_labels import parse_sft_output_labels
from .terminal_label_discriminator_gate import EVIDENCE_SCHEMA_VERSION


SILVER_QUESTION_SCHEMA_VERSION = "silver-question-candidate-v1"
SILVER_HOLD_SCHEMA_VERSION = "silver-question-hold-v1"


@dataclass(frozen=True)
class _ReleasedEvidence:
    review_id: str
    question_id: str
    parent_id: str
    source_line: int
    is_sub_question: bool
    canonical_label: str


def _string(value: object, *, field: str, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: {field} must be a non-empty string")
    return value.strip()


def _positive_int(value: object, *, field: str, source: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{source}: {field} must be a positive integer")
    return value


def _load_released_evidence(
    path: Path, *, rulebook: KnowledgeRulebook
) -> tuple[dict[str, dict[str, tuple[_ReleasedEvidence, ...]]], int]:
    grouped: dict[str, dict[str, list[_ReleasedEvidence]]] = {}
    review_ids: set[str] = set()
    records = 0
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            records += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"silver evidence line {line_number}: invalid JSON") from error
            if not isinstance(row, Mapping):
                raise ValueError(f"silver evidence line {line_number}: JSONL row must be an object")
            origin = f"silver evidence line {line_number}"
            if row.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
                raise ValueError(f"{origin}: unexpected evidence schema_version")
            if row.get("disposition") != "silver_label_candidate":
                raise ValueError(f"{origin}: disposition must be silver_label_candidate")
            if row.get("status") != "candidate" or row.get("llm_match") is not True:
                raise ValueError(f"{origin}: silver evidence must be a positive candidate verdict")
            canonical_label = _string(row.get("canonical_label"), field="canonical_label", source=origin)
            taxonomy = rulebook.records.get(canonical_label)
            if taxonomy is None or taxonomy.status != "active":
                raise ValueError(f"{origin}: canonical_label must be an active teacher terminal label")
            evidence = _ReleasedEvidence(
                review_id=_string(row.get("review_id"), field="review_id", source=origin),
                question_id=_string(row.get("question_id"), field="question_id", source=origin),
                parent_id=_string(row.get("parent_id"), field="parent_id", source=origin),
                source_line=_positive_int(row.get("source_line"), field="source_line", source=origin),
                is_sub_question=row.get("is_sub_question"),
                canonical_label=canonical_label,
            )
            if not isinstance(evidence.is_sub_question, bool):
                raise ValueError(f"{origin}: is_sub_question must be a boolean")
            if evidence.review_id in review_ids:
                raise ValueError(f"{origin}: duplicate review_id {evidence.review_id!r}")
            review_ids.add(evidence.review_id)
            grouped.setdefault(evidence.question_id, {}).setdefault(canonical_label, []).append(evidence)
    return (
        {
            question_id: {
                label: tuple(sorted(items, key=lambda item: item.review_id))
                for label, items in labels.items()
            }
            for question_id, labels in grouped.items()
        },
        records,
    )


def _canonical_history(
    output: object, *, migration: KnowledgeTaxonomyMigration
) -> tuple[str, ...] | None:
    parsed = parse_sft_output_labels(output)
    if parsed is None:
        return None
    raw_knowledge_labels, _ = parsed
    return tuple(
        sorted(
            {
                migration.canonicalize(
                    "知识点->" + label.removeprefix("知识点@").replace("@", "->")
                ).canonical_path
                for label in raw_knowledge_labels
            }
        )
    )


def _write_jsonl_row(target: Any, row: Mapping[str, Any]) -> None:
    target.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _compact_hold(
    *,
    source_line: int,
    source_row: Mapping[str, Any],
    reason: str,
    historical_labels: tuple[str, ...] | None = None,
    missing_labels: tuple[str, ...] = (),
    identity_mismatch_labels: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "schema_version": SILVER_HOLD_SCHEMA_VERSION,
        "source_line": source_line,
        "question_id": source_row.get("question_id"),
        "parent_id": source_row.get("parent_id"),
        "is_sub_question": source_row.get("is_sub_question"),
        "hold_reason": reason,
        "historical_knowledge_labels": list(historical_labels or ()),
        "missing_positive_evidence_labels": list(missing_labels),
        "identity_mismatch_evidence_labels": list(identity_mismatch_labels),
    }


def assemble_silver_questions(
    *,
    source_path: Path,
    silver_evidence_path: Path,
    rulebook: KnowledgeRulebook,
    migration: KnowledgeTaxonomyMigration,
    output_path: Path,
    hold_output_path: Path,
) -> dict[str, object]:
    """Stream source rows and promote only completely verified legacy label sets.

    A promoted record remains *silver*: a positive check for all historical labels
    cannot prove that a required knowledge point was absent from the historical
    label set.  Source labels are preserved; no replacement occurs here.
    """
    if output_path.exists() or hold_output_path.exists():
        raise FileExistsError("silver candidate output or hold output already exists")
    evidence_by_question, evidence_records = _load_released_evidence(
        silver_evidence_path, rulebook=rulebook
    )
    used_evidence_review_ids: set[str] = set()
    found_evidence_questions: set[str] = set()
    seen_evidence_question_ids: set[str] = set()
    counts: Counter[str] = Counter()
    source_hasher = hashlib.sha256()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    hold_output_path.parent.mkdir(parents=True, exist_ok=True)
    with source_path.open("rb") as source, output_path.open("x", encoding="utf-8") as output, hold_output_path.open(
        "x", encoding="utf-8"
    ) as holds:
        for source_line, raw_line in enumerate(source, 1):
            source_hasher.update(raw_line)
            if not raw_line.strip():
                continue
            try:
                source_row = json.loads(raw_line)
            except json.JSONDecodeError as error:
                raise ValueError(f"source line {source_line}: invalid JSON") from error
            if not isinstance(source_row, Mapping):
                raise ValueError(f"source line {source_line}: JSONL row must be an object")
            counts["source_records"] += 1
            question_id = source_row.get("question_id")
            if not isinstance(question_id, str) or not question_id.strip():
                _write_jsonl_row(
                    holds,
                    _compact_hold(
                        source_line=source_line,
                        source_row=source_row,
                        reason="source_question_id_missing",
                    ),
                )
                counts["hold"] += 1
                counts["source_question_id_missing"] += 1
                continue
            question_id = question_id.strip()
            question_evidence = evidence_by_question.get(question_id, {})
            if question_evidence:
                if question_id in seen_evidence_question_ids:
                    raise ValueError(
                        f"source line {source_line}: duplicate question_id with released evidence: {question_id}"
                    )
                seen_evidence_question_ids.add(question_id)
                found_evidence_questions.add(question_id)
            historical_labels = _canonical_history(source_row.get("output"), migration=migration)
            if historical_labels is None:
                _write_jsonl_row(
                    holds,
                    _compact_hold(
                        source_line=source_line,
                        source_row=source_row,
                        reason="source_output_not_rendered_labels",
                    ),
                )
                counts["hold"] += 1
                counts["source_output_not_rendered_labels"] += 1
                continue
            if not historical_labels:
                _write_jsonl_row(
                    holds,
                    _compact_hold(
                        source_line=source_line,
                        source_row=source_row,
                        reason="no_historical_knowledge_labels",
                        historical_labels=historical_labels,
                    ),
                )
                counts["hold"] += 1
                counts["no_historical_knowledge_labels"] += 1
                continue
            inactive_labels = tuple(
                label
                for label in historical_labels
                if label not in rulebook.records or rulebook.records[label].status != "active"
            )
            if inactive_labels:
                _write_jsonl_row(
                    holds,
                    _compact_hold(
                        source_line=source_line,
                        source_row=source_row,
                        reason="historical_label_not_active_taxonomy",
                        historical_labels=historical_labels,
                        missing_labels=inactive_labels,
                    ),
                )
                counts["hold"] += 1
                counts["historical_label_not_active_taxonomy"] += 1
                continue

            missing_labels: list[str] = []
            mismatch_labels: list[str] = []
            approved_review_ids: dict[str, list[str]] = {}
            for historical_label in historical_labels:
                possible_evidence = question_evidence.get(historical_label, ())
                if not possible_evidence:
                    missing_labels.append(historical_label)
                    continue
                matching = tuple(
                    item
                    for item in possible_evidence
                    if item.source_line == source_line
                    and item.parent_id == source_row.get("parent_id")
                    and item.is_sub_question is source_row.get("is_sub_question")
                )
                if not matching:
                    mismatch_labels.append(historical_label)
                    continue
                approved_review_ids[historical_label] = [item.review_id for item in matching]
                used_evidence_review_ids.update(item.review_id for item in matching)
            if missing_labels or mismatch_labels:
                reason = (
                    "positive_evidence_source_identity_mismatch"
                    if mismatch_labels and not missing_labels
                    else "missing_positive_evidence_for_historical_label"
                )
                _write_jsonl_row(
                    holds,
                    _compact_hold(
                        source_line=source_line,
                        source_row=source_row,
                        reason=reason,
                        historical_labels=historical_labels,
                        missing_labels=tuple(sorted(missing_labels)),
                        identity_mismatch_labels=tuple(sorted(mismatch_labels)),
                    ),
                )
                counts["hold"] += 1
                counts[reason] += 1
                continue
            _write_jsonl_row(
                output,
                {
                    "schema_version": SILVER_QUESTION_SCHEMA_VERSION,
                    "status": "silver_question_candidate",
                    "source_line": source_line,
                    "question_id": question_id,
                    "parent_id": source_row.get("parent_id"),
                    "is_sub_question": source_row.get("is_sub_question"),
                    "historical_knowledge_labels": list(historical_labels),
                    "approved_evidence_review_ids": approved_review_ids,
                    "source_record": source_row,
                },
            )
            counts["silver_question_candidate"] += 1

    report = {
        "schema_version": "silver-question-assembly-report-v1",
        "source_path": str(source_path),
        "source_sha256": source_hasher.hexdigest(),
        "silver_evidence_path": str(silver_evidence_path),
        "silver_evidence_records": evidence_records,
        "released_evidence_review_ids_used": len(used_evidence_review_ids),
        "released_evidence_questions_not_found_in_source": len(
            set(evidence_by_question) - found_evidence_questions
        ),
        "counts": dict(sorted(counts.items())),
    }
    return report
