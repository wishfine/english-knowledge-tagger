"""Read teacher-maintained question-type definitions without changing source data."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


LABEL_COLUMN = "末级知识点"
INTERPRETATION_COLUMN = "打标解读（标绿的标签，新题不再打）"
COMPRESSED_DEFINITION_COLUMN = "大模型压缩+人工微调的释义"
EXPLICIT_DEPRECATION_PHRASES = ("新题不再打", "新题不用打")
DISCOURAGED_PHRASES = ("新题基本不用打",)


@dataclass(frozen=True)
class TypeRulebookRecord:
    """One terminal question-type path from the teacher's rulebook."""

    path: str
    status: str
    marking_interpretation: str
    compressed_definition: str


@dataclass(frozen=True)
class TypeRulebook:
    """Terminal type paths and their lifecycle state.

    ``deprecated`` means the teacher explicitly says new questions must not use
    the type. ``discouraged`` is intentionally retained in candidate sets because
    it needs a later content/policy decision rather than an automatic exclusion.
    """

    records: Mapping[str, TypeRulebookRecord]

    def status_for(self, path: str) -> str | None:
        record = self.records.get(path)
        return record.status if record is not None else None

    def candidates_for_prefixes(self, prefixes: tuple[str, ...]) -> tuple[str, ...]:
        normalized_prefixes = tuple(prefix.strip() for prefix in prefixes if prefix.strip())
        return tuple(
            path
            for path, record in sorted(self.records.items())
            if record.status != "deprecated"
            and any(path == prefix or path.startswith(f"{prefix}->") for prefix in normalized_prefixes)
        )


def _status(interpretation: str) -> str:
    if any(phrase in interpretation for phrase in EXPLICIT_DEPRECATION_PHRASES):
        return "deprecated"
    if any(phrase in interpretation for phrase in DISCOURAGED_PHRASES):
        return "discouraged"
    return "active"


def load_type_rulebook(path: Path) -> TypeRulebook:
    """Load terminal ``题型->...`` definitions from a UTF-8 teacher CSV.

    The original CSV also contains knowledge-point rows. They are intentionally
    ignored here: question-type routing must not infer knowledge-point policy.
    """
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or LABEL_COLUMN not in reader.fieldnames:
            raise ValueError(f"teacher CSV must contain {LABEL_COLUMN!r}")
        records: dict[str, TypeRulebookRecord] = {}
        for row in reader:
            raw_path = row.get(LABEL_COLUMN)
            if not isinstance(raw_path, str):
                continue
            type_path = raw_path.strip()
            if not type_path.startswith("题型->"):
                continue
            if type_path in records:
                raise ValueError(f"duplicate terminal type path in teacher CSV: {type_path}")
            interpretation = (row.get(INTERPRETATION_COLUMN) or "").strip()
            compressed_definition = (row.get(COMPRESSED_DEFINITION_COLUMN) or "").strip()
            records[type_path] = TypeRulebookRecord(
                path=type_path,
                status=_status(interpretation),
                marking_interpretation=interpretation,
                compressed_definition=compressed_definition,
            )
    return TypeRulebook(records=records)
