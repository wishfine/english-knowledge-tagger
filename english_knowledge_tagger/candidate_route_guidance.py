"""Interpret teacher route language without turning common types into filters."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Mapping

from .knowledge_rulebook import KnowledgeRulebook


ROUTE_GUIDANCE_SCHEMA_VERSION = "candidate-route-guidance-v1"
_MANIFEST_SCHEMA_VERSION = "positive-candidate-manifest-v1"
_SOFT_TYPICAL = "soft_typical"
_HARD_EXCLUSIVE = "hard_exclusive"


@dataclass(frozen=True)
class LabelRouteGuidance:
    """A route interpretation for one rendered historical label."""

    legacy_label: str
    canonical_label: str
    mode: str
    allowed_routes: tuple[str, ...]
    csv_evidence: str


@dataclass(frozen=True)
class CandidateRouteGuidance:
    """Snapshot-bound route guidance for every manifest candidate label."""

    manifest_path: Path
    manifest_sha256: str
    labels: Mapping[str, LabelRouteGuidance]
    default_reason: str

    def mode_for(self, legacy_label: str) -> LabelRouteGuidance:
        try:
            return self.labels[legacy_label]
        except KeyError as error:
            raise ValueError(f"label is not covered by route guidance: {legacy_label!r}") from error


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _required_string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _required_string_list(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    items = tuple(_required_string(item, field=f"{field} item") for item in value)
    if len(items) != len(set(items)):
        raise ValueError(f"{field} must not contain duplicate routes")
    return items


def _load_manifest(path: Path) -> dict[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"candidate manifest is not valid JSON: {path}") from error
    if not isinstance(payload, Mapping) or payload.get("schema_version") != _MANIFEST_SCHEMA_VERSION:
        raise ValueError("candidate manifest has unexpected schema_version")
    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise ValueError("candidate manifest candidates must be a non-empty list")
    candidates: dict[str, str] = {}
    for index, item in enumerate(raw_candidates, 1):
        if not isinstance(item, Mapping):
            raise ValueError(f"manifest candidate {index} must be an object")
        legacy_label = _required_string(
            item.get("legacy_label"), field=f"manifest candidate {index} legacy_label"
        )
        canonical_label = _required_string(
            item.get("canonical_label"), field=f"manifest candidate {index} canonical_label"
        )
        if legacy_label in candidates:
            raise ValueError(f"candidate manifest has duplicate legacy label: {legacy_label!r}")
        candidates[legacy_label] = canonical_label
    return candidates


def _type_guidance_excerpt(definition: str) -> str:
    for line in definition.splitlines():
        if "题型" in line:
            return line.strip()
    return "<teacher definition has no explicit type wording>"


def load_candidate_route_guidance(
    path: Path, *, manifest_path: Path, rulebook: KnowledgeRulebook
) -> CandidateRouteGuidance:
    """Load exact hard exclusions; all unspecified manifest labels stay soft."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"candidate route guidance is not valid JSON: {path}") from error
    if not isinstance(payload, Mapping) or payload.get("schema_version") != ROUTE_GUIDANCE_SCHEMA_VERSION:
        raise ValueError("candidate route guidance has unexpected schema_version")

    manifest_sha256 = _required_string(payload.get("manifest_sha256"), field="manifest_sha256")
    actual_manifest_sha256 = _sha256(manifest_path)
    if manifest_sha256 != actual_manifest_sha256:
        raise ValueError(
            "candidate route guidance manifest_sha256 does not match the supplied candidate manifest"
        )
    candidates = _load_manifest(manifest_path)

    default = payload.get("default")
    if not isinstance(default, Mapping):
        raise ValueError("candidate route guidance default must be an object")
    if default.get("mode") != _SOFT_TYPICAL:
        raise ValueError("candidate route guidance default.mode must be soft_typical")
    if _required_string_list(default.get("allowed_routes"), field="default.allowed_routes"):
        raise ValueError("soft_typical default must not contain allowed_routes")
    default_reason = _required_string(default.get("reason"), field="default.reason")

    raw_overrides = payload.get("hard_exclusive_overrides")
    if not isinstance(raw_overrides, list):
        raise ValueError("hard_exclusive_overrides must be a list")
    overrides: dict[str, LabelRouteGuidance] = {}
    for index, item in enumerate(raw_overrides, 1):
        if not isinstance(item, Mapping):
            raise ValueError(f"hard_exclusive_overrides[{index}] must be an object")
        legacy_label = _required_string(
            item.get("legacy_label"), field=f"hard_exclusive_overrides[{index}].legacy_label"
        )
        canonical_label = _required_string(
            item.get("canonical_label"), field=f"hard_exclusive_overrides[{index}].canonical_label"
        )
        if legacy_label not in candidates:
            raise ValueError(
                f"hard_exclusive_overrides[{index}] label is not present in candidate manifest: "
                f"{legacy_label!r}"
            )
        if candidates[legacy_label] != canonical_label:
            raise ValueError(
                f"hard_exclusive_overrides[{index}] canonical label does not match candidate manifest"
            )
        rulebook_record = rulebook.records.get(canonical_label)
        if rulebook_record is None or rulebook_record.status != "active":
            raise ValueError(
                f"hard_exclusive_overrides[{index}] canonical label is not active in teacher rulebook"
            )
        allowed_routes = _required_string_list(
            item.get("allowed_routes"), field=f"hard_exclusive_overrides[{index}].allowed_routes"
        )
        if not allowed_routes:
            raise ValueError(f"hard_exclusive_overrides[{index}] must contain allowed_routes")
        csv_evidence = _required_string(
            item.get("csv_evidence"), field=f"hard_exclusive_overrides[{index}].csv_evidence"
        )
        if csv_evidence not in rulebook_record.marking_interpretation:
            raise ValueError(
                f"hard_exclusive_overrides[{index}] csv_evidence is absent from teacher definition"
            )
        if legacy_label in overrides:
            raise ValueError(f"candidate route guidance has duplicate hard override: {legacy_label!r}")
        overrides[legacy_label] = LabelRouteGuidance(
            legacy_label=legacy_label,
            canonical_label=canonical_label,
            mode=_HARD_EXCLUSIVE,
            allowed_routes=allowed_routes,
            csv_evidence=csv_evidence,
        )

    labels: dict[str, LabelRouteGuidance] = {}
    for legacy_label, canonical_label in candidates.items():
        hard_override = overrides.get(legacy_label)
        if hard_override is not None:
            labels[legacy_label] = hard_override
            continue
        record = rulebook.records.get(canonical_label)
        if record is None or record.status != "active":
            raise ValueError(f"candidate label is not active in teacher rulebook: {canonical_label}")
        labels[legacy_label] = LabelRouteGuidance(
            legacy_label=legacy_label,
            canonical_label=canonical_label,
            mode=_SOFT_TYPICAL,
            allowed_routes=(),
            csv_evidence=_type_guidance_excerpt(record.marking_interpretation),
        )
    return CandidateRouteGuidance(
        manifest_path=manifest_path,
        manifest_sha256=actual_manifest_sha256,
        labels=labels,
        default_reason=default_reason,
    )


def build_candidate_route_guidance_report(
    guidance: CandidateRouteGuidance,
) -> dict[str, object]:
    """Return a human-reviewable report; it has no data-release semantics."""
    hard = [item for item in guidance.labels.values() if item.mode == _HARD_EXCLUSIVE]
    soft = [item for item in guidance.labels.values() if item.mode == _SOFT_TYPICAL]
    return {
        "schema_version": "candidate-route-guidance-report-v1",
        "purpose": "non_releasing_teacher_route_interpretation",
        "manifest_path": str(guidance.manifest_path),
        "manifest_sha256": guidance.manifest_sha256,
        "candidate_label_count": len(guidance.labels),
        "hard_exclusive_count": len(hard),
        "soft_typical_count": len(soft),
        "default_reason": guidance.default_reason,
        "hard_exclusive_labels": [
            {
                "legacy_label": item.legacy_label,
                "canonical_label": item.canonical_label,
                "allowed_routes": list(item.allowed_routes),
                "csv_evidence": item.csv_evidence,
            }
            for item in sorted(hard, key=lambda value: value.legacy_label)
        ],
        "soft_typical_labels": [
            {
                "legacy_label": item.legacy_label,
                "canonical_label": item.canonical_label,
                "csv_type_guidance": item.csv_evidence,
            }
            for item in sorted(soft, key=lambda value: value.legacy_label)
        ],
    }
