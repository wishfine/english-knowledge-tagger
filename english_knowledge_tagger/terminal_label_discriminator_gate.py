"""Conservatively release normalised direct terminal-label discriminator evidence.

This module deliberately does not know any mentor-runner JSON schema.  Its input
is the small, versioned evidence contract produced by an adapter.  Keeping the
adapter separate prevents a change in an upstream DS runner from silently
changing what can enter a silver data batch.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .knowledge_rulebook import KnowledgeRulebook
from .terminal_label_calibration_policy import TerminalLabelCalibrationPolicy


EVIDENCE_SCHEMA_VERSION = "terminal-label-discriminator-evidence-v1"
_SUPPORTED_STATUSES = frozenset({"candidate", "error"})


@dataclass(frozen=True)
class TerminalLabelGateResult:
    """Rows routed by an auditable policy, plus a compact aggregate report."""

    silver: tuple[dict[str, Any], ...]
    relabel: tuple[dict[str, Any], ...]
    hold: tuple[dict[str, Any], ...]
    report: dict[str, Any]


def _string(value: object, *, field: str, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: {field} must be a non-empty string")
    return value.strip()


def _positive_int(value: object, *, field: str, source: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{source}: {field} must be a positive integer")
    return value


def _route_name(row: Mapping[str, Any]) -> str:
    route_key = row.get("route_key")
    if not isinstance(route_key, Mapping):
        return "unrouted"
    structure = route_key.get("declared_type_structure")
    name = route_key.get("declared_type_name")
    if isinstance(structure, str) and structure.strip() and isinstance(name, str) and name.strip():
        return f"{structure.strip()} × {name.strip()}"
    return "unrouted"


def _normalise_evidence(
    raw_row: object,
    *,
    line_number: int,
    rulebook: KnowledgeRulebook,
) -> dict[str, Any]:
    source = f"evidence line {line_number}"
    if not isinstance(raw_row, Mapping):
        raise ValueError(f"{source}: JSONL row must be an object")
    if raw_row.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        raise ValueError(f"{source}: schema_version must be {EVIDENCE_SCHEMA_VERSION!r}")
    status = _string(raw_row.get("status"), field="status", source=source)
    if status not in _SUPPORTED_STATUSES:
        raise ValueError(f"{source}: unsupported status {status!r}")
    llm_match = raw_row.get("llm_match")
    if not isinstance(llm_match, bool):
        raise ValueError(f"{source}: llm_match must be a boolean")
    is_sub_question = raw_row.get("is_sub_question")
    if not isinstance(is_sub_question, bool):
        raise ValueError(f"{source}: is_sub_question must be a boolean")
    canonical_label = _string(raw_row.get("canonical_label"), field="canonical_label", source=source)
    rulebook_record = rulebook.records.get(canonical_label)
    if rulebook_record is None or rulebook_record.status != "active":
        raise ValueError(f"{source}: canonical_label must be an active teacher terminal label")
    normalised = dict(raw_row)
    normalised.update(
        {
            "review_id": _string(raw_row.get("review_id"), field="review_id", source=source),
            "question_id": _string(raw_row.get("question_id"), field="question_id", source=source),
            "parent_id": _string(raw_row.get("parent_id"), field="parent_id", source=source),
            "source_line": _positive_int(raw_row.get("source_line"), field="source_line", source=source),
            "legacy_label": _string(raw_row.get("legacy_label"), field="legacy_label", source=source),
            "canonical_label": canonical_label,
            "llm_match": llm_match,
            "status": status,
            "model": _string(raw_row.get("model"), field="model", source=source),
            "prompt_version": _string(
                raw_row.get("prompt_version"), field="prompt_version", source=source
            ),
            "is_sub_question": is_sub_question,
            "scope": "child" if is_sub_question else "parent",
        }
    )
    return normalised


def _policy_snapshot(policy_rule: Any) -> dict[str, Any]:
    return {
        "calibration_stage": policy_rule.calibration_stage,
        "positive_disposition": policy_rule.positive_disposition,
        "negative_disposition": policy_rule.negative_disposition,
        "audit": {
            "positive": {
                "retain": policy_rule.positive_audit.retain,
                "remove": policy_rule.positive_audit.remove,
                "uncertain": policy_rule.positive_audit.uncertain,
            },
            "negative": {
                "retain": policy_rule.negative_audit.retain,
                "remove": policy_rule.negative_audit.remove,
                "uncertain": policy_rule.negative_audit.uncertain,
            },
        },
    }


def _disposition(row: Mapping[str, Any], policy_rule: Any) -> tuple[str, str]:
    if row["status"] != "candidate":
        return "hold", f"discriminator_status_{row['status']}"
    if row["llm_match"]:
        if policy_rule.positive_disposition == "silver_label_candidate":
            return "silver_label_candidate", "policy_positive_silver"
        return "hold", "policy_positive_hold"
    if policy_rule.negative_disposition == "relabel_candidate":
        return "relabel_candidate", "policy_negative_relabel"
    return "hold", "policy_negative_hold"


def gate_terminal_label_discriminator(
    rows: Iterable[object],
    *,
    policy: TerminalLabelCalibrationPolicy,
    rulebook: KnowledgeRulebook,
) -> TerminalLabelGateResult:
    """Route direct label verdicts without changing a source label.

    ``silver_label_candidate`` proves only that this individual legacy label has
    passed a calibrated direct check.  It does not assert the question has a
    complete knowledge-label set and therefore cannot create an HQ/SFT row.
    """
    silver: list[dict[str, Any]] = []
    relabel: list[dict[str, Any]] = []
    hold: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    labels: dict[str, Counter[str]] = {}
    scopes: Counter[str] = Counter()
    routes: Counter[str] = Counter()
    seen_verdicts: dict[tuple[str, str], bool] = {}

    for line_number, raw_row in enumerate(rows, 1):
        row = _normalise_evidence(raw_row, line_number=line_number, rulebook=rulebook)
        evidence_key = (row["question_id"], row["canonical_label"])
        prior_verdict = seen_verdicts.get(evidence_key)
        if prior_verdict is not None and prior_verdict != row["llm_match"]:
            raise ValueError(
                f"evidence line {line_number}: conflicting duplicate question_id × canonical_label "
                f"evidence for {row['question_id']} × {row['canonical_label']}"
            )
        seen_verdicts[evidence_key] = row["llm_match"]
        policy_rule = policy.for_label(row["canonical_label"])
        disposition, reason = _disposition(row, policy_rule)
        output_row = {
            **row,
            "disposition": disposition,
            "disposition_reason": reason,
            "calibration_policy": _policy_snapshot(policy_rule),
        }
        counts[disposition] += 1
        labels.setdefault(row["canonical_label"], Counter())[disposition] += 1
        scopes[row["scope"]] += 1
        routes[_route_name(row)] += 1
        if disposition == "silver_label_candidate":
            silver.append(output_row)
        elif disposition == "relabel_candidate":
            relabel.append(output_row)
        else:
            hold.append(output_row)

    return TerminalLabelGateResult(
        silver=tuple(silver),
        relabel=tuple(relabel),
        hold=tuple(hold),
        report={
            "schema_version": "terminal-label-discriminator-gate-report-v1",
            "counts": {
                "silver_label_candidate": counts["silver_label_candidate"],
                "relabel_candidate": counts["relabel_candidate"],
                "hold": counts["hold"],
            },
            "by_canonical_label": {
                label: dict(sorted(dispositions.items()))
                for label, dispositions in sorted(labels.items())
            },
            "by_scope": dict(sorted(scopes.items())),
            "by_route": dict(sorted(routes.items())),
        },
    )
