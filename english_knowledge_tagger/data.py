"""Validated question records and leakage-resistant dataset splitting."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import random
import re
from typing import Any, Iterable, Mapping
import unicodedata


class DataContractError(ValueError):
    """Raised when a taxonomy or a labeled JSONL record is invalid."""


@dataclass(frozen=True)
class QuestionRecord:
    """One validated supervised English-question labeling record."""

    id: str
    question: str
    options: tuple[str, ...]
    answer: str | None
    analysis: str | None
    knowledge_points: tuple[str, ...]
    source: str | None = None


def normalize_text(value: str) -> str:
    """Normalize Unicode and whitespace for comparison and content grouping."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


def load_taxonomy(path: Path) -> frozenset[str]:
    """Load the versioned knowledge-point taxonomy from JSON."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DataContractError(f"cannot load taxonomy {path}: {error}") from error

    labels = payload.get("knowledge_points") if isinstance(payload, dict) else payload
    if not isinstance(labels, list) or not labels:
        raise DataContractError("taxonomy must contain a non-empty knowledge_points array")

    normalized = [normalize_text(label) for label in labels if isinstance(label, str)]
    if len(normalized) != len(labels) or any(not label for label in normalized):
        raise DataContractError("taxonomy labels must be non-empty strings")
    if len(set(normalized)) != len(normalized):
        raise DataContractError("taxonomy labels must be unique after normalization")
    return frozenset(normalized)


def _optional_text(payload: Mapping[str, Any], field: str, line_number: int) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise DataContractError(f"line {line_number}: {field} must be a string when provided")
    normalized = normalize_text(value)
    return normalized or None


def _options(payload: Mapping[str, Any], line_number: int) -> tuple[str, ...]:
    value = payload.get("options")
    if value is None:
        return ()
    if isinstance(value, str):
        normalized = normalize_text(value)
        return (normalized,) if normalized else ()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise DataContractError(f"line {line_number}: options must be a string or a string array")
    return tuple(item for item in (normalize_text(item) for item in value) if item)


def _record_from_payload(
    payload: Mapping[str, Any], taxonomy: frozenset[str] | set[str], line_number: int
) -> QuestionRecord:
    record_id = payload.get("id")
    question = payload.get("question")
    labels = payload.get("knowledge_points")
    if not isinstance(record_id, str) or not normalize_text(record_id):
        raise DataContractError(f"line {line_number}: id must be a non-empty string")
    if not isinstance(question, str) or not normalize_text(question):
        raise DataContractError(f"line {line_number}: question must be a non-empty string")
    if not isinstance(labels, list) or not labels or any(not isinstance(label, str) for label in labels):
        raise DataContractError(f"line {line_number}: knowledge_points must be a non-empty string array")

    normalized_labels = tuple(sorted({normalize_text(label) for label in labels}))
    if any(not label for label in normalized_labels):
        raise DataContractError(f"line {line_number}: knowledge_points may not contain empty labels")
    unknown_labels = sorted(set(normalized_labels) - set(taxonomy))
    if unknown_labels:
        raise DataContractError(
            f"line {line_number}: knowledge_points not in taxonomy: {', '.join(unknown_labels)}"
        )

    return QuestionRecord(
        id=normalize_text(record_id),
        question=normalize_text(question),
        options=_options(payload, line_number),
        answer=_optional_text(payload, "answer", line_number),
        analysis=_optional_text(payload, "analysis", line_number),
        knowledge_points=normalized_labels,
        source=_optional_text(payload, "source", line_number),
    )


def load_records(path: Path, taxonomy: frozenset[str] | set[str]) -> list[QuestionRecord]:
    """Read a labeled JSONL file and enforce its public data contract."""
    records: list[QuestionRecord] = []
    seen_ids: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise DataContractError(f"cannot read data file {path}: {error}") from error

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as error:
            raise DataContractError(f"line {line_number}: invalid JSON: {error.msg}") from error
        if not isinstance(payload, dict):
            raise DataContractError(f"line {line_number}: every JSONL line must be an object")
        record = _record_from_payload(payload, taxonomy, line_number)
        if record.id in seen_ids:
            raise DataContractError(f"line {line_number}: duplicate id {record.id!r}")
        seen_ids.add(record.id)
        records.append(record)

    if not records:
        raise DataContractError("data file contains no labeled records")
    return records


def load_inference_records(path: Path) -> list[QuestionRecord]:
    """Read question JSONL for prediction without requiring gold labels."""
    records: list[QuestionRecord] = []
    seen_ids: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise DataContractError(f"cannot read inference file {path}: {error}") from error

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as error:
            raise DataContractError(f"line {line_number}: invalid JSON: {error.msg}") from error
        if not isinstance(payload, dict):
            raise DataContractError(f"line {line_number}: every JSONL line must be an object")
        record_id = payload.get("id")
        question = payload.get("question")
        if not isinstance(record_id, str) or not normalize_text(record_id):
            raise DataContractError(f"line {line_number}: id must be a non-empty string")
        if not isinstance(question, str) or not normalize_text(question):
            raise DataContractError(f"line {line_number}: question must be a non-empty string")
        normalized_id = normalize_text(record_id)
        if normalized_id in seen_ids:
            raise DataContractError(f"line {line_number}: duplicate id {normalized_id!r}")
        seen_ids.add(normalized_id)
        records.append(
            QuestionRecord(
                id=normalized_id,
                question=normalize_text(question),
                options=_options(payload, line_number),
                answer=_optional_text(payload, "answer", line_number),
                analysis=_optional_text(payload, "analysis", line_number),
                knowledge_points=(),
                source=_optional_text(payload, "source", line_number),
            )
        )
    if not records:
        raise DataContractError("inference file contains no question records")
    return records


def content_hash(record: QuestionRecord) -> str:
    """Return a stable hash of model-visible question content, excluding labels and ID."""
    canonical = {
        "question": record.question,
        "options": list(record.options),
        "answer": record.answer or "",
        "analysis": record.analysis or "",
    }
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def split_records(
    records: Iterable[QuestionRecord], validation_ratio: float = 0.1, seed: int = 42
) -> tuple[list[QuestionRecord], list[QuestionRecord]]:
    """Split records by content hash so duplicate visible questions cannot leak."""
    if not 0 < validation_ratio < 1:
        raise DataContractError("validation_ratio must be strictly between 0 and 1")
    items = list(records)
    if len(items) < 2:
        raise DataContractError("at least two records are required to create train and validation splits")

    groups: dict[str, list[QuestionRecord]] = {}
    for record in items:
        groups.setdefault(content_hash(record), []).append(record)
    if len(groups) < 2:
        raise DataContractError("at least two distinct question contents are required for a split")

    hashes = sorted(groups)
    random.Random(seed).shuffle(hashes)
    target_validation_count = max(1, round(len(items) * validation_ratio))
    validation_hashes: set[str] = set()
    validation_count = 0
    for question_hash in hashes:
        if validation_count >= target_validation_count:
            break
        validation_hashes.add(question_hash)
        validation_count += len(groups[question_hash])
    if len(validation_hashes) == len(groups):
        validation_hashes.remove(hashes[-1])

    train = [record for record in items if content_hash(record) not in validation_hashes]
    validation = [record for record in items if content_hash(record) in validation_hashes]
    if not train or not validation:
        raise DataContractError("unable to create non-empty train and validation splits")
    return train, validation
