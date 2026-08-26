"""Sparse human-approved release rules for direct terminal-label discrimination."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Mapping

from .knowledge_rulebook import KnowledgeRulebook


SCHEMA_VERSION = "terminal-label-calibration-policy-v1"
POSITIVE_DISPOSITIONS = frozenset({"silver_label_candidate", "hold"})
NEGATIVE_DISPOSITIONS = frozenset({"relabel_candidate", "hold"})
CALIBRATION_STAGES = frozenset({"unreviewed", "screened_12", "released_post_sweep"})


@dataclass(frozen=True)
class CalibrationAuditCounts:
    retain: int
    remove: int
    uncertain: int

    @property
    def reviewed(self) -> int:
        return self.retain + self.remove + self.uncertain


@dataclass(frozen=True)
class TerminalLabelCalibrationRule:
    canonical_label: str
    positive_disposition: str
    negative_disposition: str
    calibration_stage: str
    positive_audit: CalibrationAuditCounts
    negative_audit: CalibrationAuditCounts


_UNREVIEWED = TerminalLabelCalibrationRule(
    canonical_label="",
    positive_disposition="hold",
    negative_disposition="hold",
    calibration_stage="unreviewed",
    positive_audit=CalibrationAuditCounts(retain=0, remove=0, uncertain=0),
    negative_audit=CalibrationAuditCounts(retain=0, remove=0, uncertain=0),
)


@dataclass(frozen=True)
class TerminalLabelCalibrationPolicy:
    rules: Mapping[str, TerminalLabelCalibrationRule]

    def for_label(self, canonical_label: str) -> TerminalLabelCalibrationRule:
        """Unlisted labels are intentionally held until their calibration is complete."""
        rule = self.rules.get(canonical_label)
        if rule is not None:
            return rule
        return TerminalLabelCalibrationRule(
            canonical_label=canonical_label,
            positive_disposition=_UNREVIEWED.positive_disposition,
            negative_disposition=_UNREVIEWED.negative_disposition,
            calibration_stage=_UNREVIEWED.calibration_stage,
            positive_audit=_UNREVIEWED.positive_audit,
            negative_audit=_UNREVIEWED.negative_audit,
        )


def _string(value: object, *, field: str, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: {field} must be a non-empty string")
    return value.strip()


def _count(value: object, *, field: str, source: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{source}: {field} must be a non-negative integer")
    return value


def _audit(value: object, *, field: str, source: str) -> CalibrationAuditCounts:
    if not isinstance(value, Mapping):
        raise ValueError(f"{source}: audit.{field} must be an object")
    return CalibrationAuditCounts(
        retain=_count(value.get("retain"), field=f"audit.{field}.retain", source=source),
        remove=_count(value.get("remove"), field=f"audit.{field}.remove", source=source),
        uncertain=_count(value.get("uncertain"), field=f"audit.{field}.uncertain", source=source),
    )


def _rule(raw_rule: object, *, source: str, rulebook: KnowledgeRulebook) -> TerminalLabelCalibrationRule:
    if not isinstance(raw_rule, Mapping):
        raise ValueError(f"{source}: label rule must be an object")
    canonical_label = _string(raw_rule.get("canonical_label"), field="canonical_label", source=source)
    rulebook_record = rulebook.records.get(canonical_label)
    if rulebook_record is None or rulebook_record.status != "active":
        raise ValueError(f"{source}: canonical_label must be an active teacher terminal label")
    positive_disposition = _string(
        raw_rule.get("positive_disposition"), field="positive_disposition", source=source
    )
    negative_disposition = _string(
        raw_rule.get("negative_disposition"), field="negative_disposition", source=source
    )
    stage = _string(raw_rule.get("calibration_stage"), field="calibration_stage", source=source)
    if positive_disposition not in POSITIVE_DISPOSITIONS:
        raise ValueError(f"{source}: unsupported positive_disposition {positive_disposition!r}")
    if negative_disposition not in NEGATIVE_DISPOSITIONS:
        raise ValueError(f"{source}: unsupported negative_disposition {negative_disposition!r}")
    if stage not in CALIBRATION_STAGES:
        raise ValueError(f"{source}: unsupported calibration_stage {stage!r}")
    audit = raw_rule.get("audit")
    if not isinstance(audit, Mapping):
        raise ValueError(f"{source}: audit must be an object")
    positive_audit = _audit(audit.get("positive"), field="positive", source=source)
    negative_audit = _audit(audit.get("negative"), field="negative", source=source)
    if stage == "unreviewed" and (
        positive_disposition != "hold" or negative_disposition != "hold"
    ):
        raise ValueError(f"{source}: unreviewed labels must keep both dispositions hold")
    if positive_disposition == "silver_label_candidate":
        if positive_audit.reviewed == 0:
            raise ValueError(f"{source}: positive silver release requires reviewed positive samples")
        if positive_audit.remove:
            raise ValueError(f"{source}: positive audit.remove must be 0 for silver release")
    if negative_disposition == "relabel_candidate":
        if negative_audit.reviewed == 0:
            raise ValueError(f"{source}: negative relabel release requires reviewed negative samples")
        if negative_audit.retain or negative_audit.uncertain:
            raise ValueError(
                f"{source}: negative relabel release requires audit negative retain and uncertain to be 0"
            )
    return TerminalLabelCalibrationRule(
        canonical_label=canonical_label,
        positive_disposition=positive_disposition,
        negative_disposition=negative_disposition,
        calibration_stage=stage,
        positive_audit=positive_audit,
        negative_audit=negative_audit,
    )


def load_terminal_label_calibration_policy(
    path: Path, *, rulebook: KnowledgeRulebook
) -> TerminalLabelCalibrationPolicy:
    """Load a sparse calibration policy; omitted labels are held by default."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"terminal label calibration policy is not valid JSON: {path}") from error
    if not isinstance(payload, Mapping) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"terminal label calibration policy schema_version must be {SCHEMA_VERSION!r}")
    raw_labels = payload.get("labels")
    if not isinstance(raw_labels, list):
        raise ValueError("terminal label calibration policy labels must be a list")
    rules: dict[str, TerminalLabelCalibrationRule] = {}
    for index, raw_rule in enumerate(raw_labels, 1):
        rule = _rule(raw_rule, source=f"terminal label calibration policy labels[{index}]", rulebook=rulebook)
        if rule.canonical_label in rules:
            raise ValueError(f"duplicate terminal label calibration policy label: {rule.canonical_label}")
        rules[rule.canonical_label] = rule
    return TerminalLabelCalibrationPolicy(rules=rules)
