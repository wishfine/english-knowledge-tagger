"""Derive a non-releasing incremental queue from two candidate manifest snapshots."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


MANIFEST_SCHEMA_VERSION = "positive-candidate-manifest-v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _string(value: object, *, field: str, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: {field} must be a non-empty string")
    return value.strip()


def _load_manifest(path: Path) -> tuple[dict[str, dict[str, Any]], Mapping[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"candidate manifest is not valid JSON: {path}") from error
    if not isinstance(payload, Mapping) or payload.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError("candidate manifest has unexpected schema_version")
    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise ValueError("candidate manifest candidates must be a non-empty list")
    candidates: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(raw_candidates, 1):
        if not isinstance(item, Mapping):
            raise ValueError(f"candidate manifest candidate {index} must be an object")
        source = f"candidate manifest candidate {index}"
        legacy_label = _string(item.get("legacy_label"), field="legacy_label", source=source)
        canonical_label = _string(item.get("canonical_label"), field="canonical_label", source=source)
        if legacy_label in candidates:
            raise ValueError(f"candidate manifest has duplicate legacy label: {legacy_label!r}")
        candidates[legacy_label] = dict(item)
        candidates[legacy_label]["legacy_label"] = legacy_label
        candidates[legacy_label]["canonical_label"] = canonical_label
    return candidates, payload


def build_positive_candidate_delta_manifest(
    *,
    latest_manifest_path: Path,
    base_manifest_path: Path,
    output_path: Path,
) -> dict[str, object]:
    """Freeze only newly eligible labels while preserving latest ledger lineage."""
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite existing delta manifest: {output_path}")
    latest, latest_payload = _load_manifest(latest_manifest_path)
    base, _ = _load_manifest(base_manifest_path)
    for legacy_label, base_row in base.items():
        latest_row = latest.get(legacy_label)
        if latest_row is None:
            raise ValueError(
                f"base candidate is not present in latest manifest: {legacy_label!r}"
            )
        if latest_row["canonical_label"] != base_row["canonical_label"]:
            raise ValueError(
                f"base candidate canonical label differs in latest manifest: {legacy_label!r}"
            )
    delta = [row for label, row in latest.items() if label not in base]
    if not delta:
        raise ValueError("latest manifest contains no new candidates beyond base manifest")
    inputs = latest_payload.get("inputs")
    if not isinstance(inputs, Mapping):
        raise ValueError("latest manifest inputs must be an object")
    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "purpose": "non_releasing_incremental_positive_candidate_work_queue",
        "criteria": latest_payload.get("criteria"),
        "inputs": dict(inputs),
        "base_manifest_path": str(base_manifest_path),
        "base_manifest_sha256": _sha256(base_manifest_path),
        "latest_manifest_path": str(latest_manifest_path),
        "latest_manifest_sha256": _sha256(latest_manifest_path),
        "candidates": delta,
        "taxonomy_blocked": [],
        "excluded": [],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {
        "schema_version": "positive-candidate-delta-manifest-report-v1",
        "output_path": str(output_path),
        "base_candidate_records": len(base),
        "latest_candidate_records": len(latest),
        "delta_candidate_records": len(delta),
    }
