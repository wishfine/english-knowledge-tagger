"""Freeze a non-releasing work queue from human-review and raw-yield ledgers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .knowledge_rulebook import KnowledgeRulebook
from .knowledge_taxonomy_migration import KnowledgeTaxonomyMigration
from .mentor_verification_priority import wilson_lower_one_sided_95


MANIFEST_SCHEMA_VERSION = "positive-candidate-manifest-v1"
_FRACTION = re.compile(r"(?P<numerator>\d+)\s*/\s*(?P<denominator>\d+)")


def _ledger_rows(path: Path) -> dict[str, tuple[str, ...]]:
    rows: dict[str, tuple[str, ...]] = {}
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.startswith("| 知识点@"):
                continue
            cells = tuple(cell.strip() for cell in line.strip().strip("|").split("|"))
            if len(cells) < 3:
                raise ValueError(f"ledger line {line_number}: expected at least three table cells")
            label = cells[0]
            if label in rows:
                raise ValueError(f"ledger line {line_number}: duplicate label {label!r}")
            rows[label] = cells
    return rows


def _fraction(value: object, *, field: str, label: str) -> tuple[int, int]:
    if not isinstance(value, str):
        raise ValueError(f"{label}: {field} must be a string fraction")
    match = _FRACTION.search(value)
    if match is None:
        raise ValueError(f"{label}: {field} must contain a 'numerator/denominator' fraction")
    numerator = int(match.group("numerator"))
    denominator = int(match.group("denominator"))
    if denominator <= 0 or numerator < 0 or numerator > denominator:
        raise ValueError(f"{label}: {field} fraction is invalid")
    return numerator, denominator


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _legacy_to_canonical(label: str, migration: KnowledgeTaxonomyMigration) -> str:
    if not label.startswith("知识点@"):
        raise ValueError(f"manifest label must start with 知识点@: {label!r}")
    legacy_path = "知识点->" + label.removeprefix("知识点@").replace("@", "->")
    return migration.canonicalize(legacy_path).canonical_path


def _row(
    *,
    label: str,
    raw_matches: int,
    raw_sample_size: int,
    true_retain: int,
    true_reviewed: int,
    canonical_label: str,
) -> dict[str, object]:
    match_rate = raw_matches / raw_sample_size
    return {
        "legacy_label": label,
        "canonical_label": canonical_label,
        "raw_yield": {
            "matches": raw_matches,
            "sample_size": raw_sample_size,
            "match_rate": match_rate,
            "wilson_lower_one_sided_95": wilson_lower_one_sided_95(
                raw_matches, raw_sample_size
            ),
        },
        "human_true_audit": {"retain": true_retain, "reviewed": true_reviewed},
    }


def build_positive_candidate_manifest(
    full_sample_ledger_path: Path,
    *,
    raw_yield_ledger_path: Path,
    rulebook: KnowledgeRulebook,
    migration: KnowledgeTaxonomyMigration,
    output_path: Path,
) -> dict[str, object]:
    """Create an auditable work queue; it cannot release any label evidence."""
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite existing candidate manifest: {output_path}")
    full_rows = _ledger_rows(full_sample_ledger_path)
    raw_rows = _ledger_rows(raw_yield_ledger_path)
    candidates: list[dict[str, object]] = []
    taxonomy_blocked: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []
    for label, full_cells in full_rows.items():
        raw_cells = raw_rows.get(label)
        if raw_cells is None:
            excluded.append({"legacy_label": label, "reason": "raw_yield_missing"})
            continue
        raw_matches, raw_sample_size = _fraction(raw_cells[1], field="raw_yield", label=label)
        true_retain, true_reviewed = _fraction(
            full_cells[2], field="human_true_audit", label=label
        )
        canonical_label = _legacy_to_canonical(label, migration)
        row = _row(
            label=label,
            raw_matches=raw_matches,
            raw_sample_size=raw_sample_size,
            true_retain=true_retain,
            true_reviewed=true_reviewed,
            canonical_label=canonical_label,
        )
        lcb = row["raw_yield"]["wilson_lower_one_sided_95"]  # type: ignore[index]
        if lcb < 0.70:
            excluded.append({**row, "reason": "wilson_lower_below_0_70"})
            continue
        if (true_retain, true_reviewed) != (12, 12):
            excluded.append({**row, "reason": "human_true_audit_not_12_of_12"})
            continue
        taxonomy = rulebook.records.get(canonical_label)
        if taxonomy is None or taxonomy.status != "active":
            taxonomy_blocked.append({**row, "reason": "canonical_label_not_active"})
            continue
        candidates.append(row)
    candidates.sort(
        key=lambda item: (
            -item["raw_yield"]["match_rate"],  # type: ignore[index]
            item["legacy_label"],
        )
    )
    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "purpose": "non_releasing_positive_candidate_work_queue",
        "criteria": {
            "wilson_lower_one_sided_95_minimum": 0.70,
            "human_true_audit": {"retain": 12, "reviewed": 12},
            "canonical_label_status": "active",
        },
        "inputs": {
            "full_sample_ledger_path": str(full_sample_ledger_path),
            "full_sample_ledger_sha256": _sha256(full_sample_ledger_path),
            "raw_yield_ledger_path": str(raw_yield_ledger_path),
            "raw_yield_ledger_sha256": _sha256(raw_yield_ledger_path),
        },
        "candidates": candidates,
        "taxonomy_blocked": taxonomy_blocked,
        "excluded": excluded,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {
        "schema_version": "positive-candidate-manifest-report-v1",
        "output_path": str(output_path),
        "full_sample_ledger_records": len(full_rows),
        "raw_yield_ledger_records": len(raw_rows),
        "candidate_records": len(candidates),
        "taxonomy_blocked_records": len(taxonomy_blocked),
        "excluded_records": len(excluded),
    }
