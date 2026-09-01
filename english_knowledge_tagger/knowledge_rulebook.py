"""Read terminal knowledge-point definitions from the teacher-maintained CSV."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Mapping


LABEL_COLUMN = "末级知识点"
INTERPRETATION_COLUMN = "打标解读（标绿的标签，新题不再打）"
COMPRESSED_DEFINITION_COLUMN = "大模型压缩+人工微调的释义"
EXPLICIT_DEPRECATION_PHRASES = ("新题不再打", "新题不用打")


@dataclass(frozen=True)
class KnowledgeRulebookRecord:
    """One terminal knowledge-point definition and lifecycle state."""

    path: str
    status: str
    marking_interpretation: str
    compressed_definition: str
    definition_override: str | None = None

    @property
    def target_definition(self) -> str:
        return self.definition_override or self.marking_interpretation or self.compressed_definition

    @property
    def alternative_definition(self) -> str:
        return self.definition_override or self.compressed_definition or self.marking_interpretation


@dataclass(frozen=True)
class KnowledgeRulebook:
    """Knowledge definitions indexed by canonical ``知识点->...`` paths."""

    records: Mapping[str, KnowledgeRulebookRecord]

    def nearby_active_records(
        self, path: str, *, limit: int
    ) -> tuple[KnowledgeRulebookRecord, ...]:
        if limit <= 0:
            raise ValueError("nearby record limit must be positive")
        return self.direct_active_leaf_siblings(path)[:limit]

    def direct_active_leaf_siblings(self, path: str) -> tuple[KnowledgeRulebookRecord, ...]:
        """Return every active terminal sharing the exact immediate parent of ``path``."""
        parent, separator, _ = path.rpartition("->")
        if not separator:
            return ()
        return tuple(
            record
            for candidate_path, record in sorted(self.records.items())
            if candidate_path != path
            and record.status == "active"
            and candidate_path.startswith(f"{parent}->")
            and candidate_path.count("->") == path.count("->")
        )

    def retrieve_active_records(
        self,
        *,
        prefixes: tuple[str, ...],
        query: str,
        exclude_paths: frozenset[str],
        limit: int,
    ) -> tuple[KnowledgeRulebookRecord, ...]:
        """Return a small deterministic lexical shortlist from a type-allowed pool."""
        if limit <= 0:
            raise ValueError("retrieval limit must be positive")
        query_terms = _terms(query)
        scored: list[tuple[int, str, KnowledgeRulebookRecord]] = []
        for path, record in self.records.items():
            if (
                path in exclude_paths
                or record.status != "active"
                or not any(path == prefix or path.startswith(f"{prefix}->") for prefix in prefixes)
            ):
                continue
            document_terms = _terms(f"{path}\n{record.alternative_definition}")
            score = len(query_terms & document_terms)
            scored.append((score, path, record))
        return tuple(record for _, _, record in sorted(scored, key=lambda item: (-item[0], item[1]))[:limit])


def _terms(text: str) -> frozenset[str]:
    normalized = text.lower()
    ascii_words = re.findall(r"[a-z0-9]+", normalized)
    han = "".join(re.findall(r"[\u4e00-\u9fff]", normalized))
    han_bigrams = [han[index : index + 2] for index in range(max(0, len(han) - 1))]
    return frozenset(ascii_words + han_bigrams)


def _status(interpretation: str) -> str:
    if any(phrase in interpretation for phrase in EXPLICIT_DEPRECATION_PHRASES):
        return "deprecated"
    return "active"


def _load_definition_overrides(path: Path) -> dict[str, str]:
    """Load active, label-specific definition replacements from a versioned JSON file."""
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise ValueError("definition overrides JSON must be an object")
    if payload.get("schema_version") != "knowledge-definition-overrides-v1":
        raise ValueError("definition overrides schema_version must be knowledge-definition-overrides-v1")
    raw_overrides = payload.get("overrides")
    if not isinstance(raw_overrides, list):
        raise ValueError("definition overrides must contain an overrides list")
    overrides: dict[str, str] = {}
    for index, raw_override in enumerate(raw_overrides, 1):
        if not isinstance(raw_override, Mapping):
            raise ValueError(f"definition override {index} must be an object")
        label = raw_override.get("label")
        replacement = raw_override.get("replacement_definition")
        status = raw_override.get("status")
        if not isinstance(label, str) or not label.strip().startswith("知识点->"):
            raise ValueError(f"definition override {index} label must start with 知识点->")
        label = label.strip()
        if not isinstance(replacement, str) or not replacement.strip():
            raise ValueError(f"definition override {index} replacement_definition must be non-empty")
        if status not in {"active", "active_for_experiment"}:
            raise ValueError(
                f"definition override {index} status must be active or active_for_experiment"
            )
        if label in overrides:
            raise ValueError(f"duplicate definition override label: {label}")
        overrides[label] = replacement.strip()
    return overrides


def load_knowledge_rulebook(
    path: Path, *, overrides_path: Path | None = None
) -> KnowledgeRulebook:
    """Load only terminal knowledge-point rows from a UTF-8 teacher CSV."""
    overrides = _load_definition_overrides(overrides_path) if overrides_path is not None else {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or LABEL_COLUMN not in reader.fieldnames:
            raise ValueError(f"teacher CSV must contain {LABEL_COLUMN!r}")
        records: dict[str, KnowledgeRulebookRecord] = {}
        for row in reader:
            raw_path = row.get(LABEL_COLUMN)
            if not isinstance(raw_path, str):
                continue
            knowledge_path = raw_path.strip()
            if not knowledge_path.startswith("知识点->"):
                continue
            if knowledge_path in records:
                raise ValueError(f"duplicate terminal knowledge path in teacher CSV: {knowledge_path}")
            interpretation = (row.get(INTERPRETATION_COLUMN) or "").strip()
            compressed = (row.get(COMPRESSED_DEFINITION_COLUMN) or "").strip()
            records[knowledge_path] = KnowledgeRulebookRecord(
                path=knowledge_path,
                status=_status(interpretation),
                marking_interpretation=interpretation,
                compressed_definition=compressed,
                definition_override=overrides.get(knowledge_path),
            )
    missing = sorted(set(overrides) - set(records))
    if missing:
        raise ValueError(f"definition override label is absent from teacher CSV: {missing[0]}")
    return KnowledgeRulebook(records=records)
