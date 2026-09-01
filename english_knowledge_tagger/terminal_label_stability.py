"""Experimental three-way terminal-label stability packets, client, and analysis."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any, Mapping, Sequence

from .candidate_labeling import (
    LabelingServiceConfig,
    LabelingServiceError,
    Transport,
    _http_transport,
)
from .conversion_gate import _extract_json_payload
from .final_label_discriminator import clean_final_label_question
from .knowledge_rulebook import KnowledgeRulebook
from .knowledge_taxonomy_migration import KnowledgeTaxonomyMigration
from .mentor_direct_rollout import _route_key


PACKET_SCHEMA_VERSION = "terminal-label-stability-packet-v1"
EVIDENCE_SCHEMA_VERSION = "terminal-label-stability-evidence-v1"
REPORT_SCHEMA_VERSION = "terminal-label-stability-analysis-v1"
PROMPT_VERSION = "terminal-label-stability-v1"
_DECISIONS = frozenset({"keep", "non_target", "insufficient"})
_CONFIDENCES = frozenset({"high", "medium", "low"})
_GOLD_DECISIONS = frozenset({"keep", "remove", "uncertain"})


@dataclass(frozen=True)
class TerminalLabelStabilityResult:
    decision: str
    confidence: str
    criterion_evidence: tuple[str, ...]
    missing_context: tuple[str, ...]
    raw_response: str
    elapsed_ms: float
    prompt_chars: int


def _text(value: object, *, field: str, origin: str = "row") -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{origin}: {field} must be a non-empty string")
    return value.strip()


def _canonical_label(
    rendered_label: str,
    *,
    migration: KnowledgeTaxonomyMigration,
    rulebook: KnowledgeRulebook,
) -> str:
    if not rendered_label.startswith("知识点@"):
        raise ValueError("verify_label must begin with 知识点@")
    legacy_path = "知识点->" + rendered_label.removeprefix("知识点@").replace("@", "->")
    canonical = migration.canonicalize(legacy_path).canonical_path
    record = rulebook.records.get(canonical)
    if record is None or record.status != "active":
        raise ValueError("verify_label must map to an active teacher terminal label")
    return canonical


def _read_materialized(path: Path, *, verify_label: str) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"materialized line {line_number}: invalid JSON") from error
            if not isinstance(row, Mapping):
                raise ValueError(f"materialized line {line_number}: row must be an object")
            if row.get("verify_label") != verify_label:
                continue
            question_id = _text(
                row.get("question_id"), field="question_id", origin=f"materialized line {line_number}"
            )
            if question_id in selected:
                raise ValueError(f"materialized contains duplicate question_id {question_id!r}")
            selected[question_id] = {**row, "_source_line": line_number}
    if not selected:
        raise ValueError("materialized source has no records for verify_label")
    return selected


def _read_pseudo_gold(
    path: Path, *, verify_label: str
) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"pseudo-gold line {line_number}: invalid JSON") from error
            if not isinstance(row, Mapping):
                raise ValueError(f"pseudo-gold line {line_number}: row must be an object")
            if row.get("record_type") == "label_conclusion":
                continue
            rendered = row.get("verify_label")
            if rendered is not None and rendered != verify_label:
                raise ValueError(f"pseudo-gold line {line_number}: verify_label mismatch")
            question_id = _text(
                row.get("question_id"), field="question_id", origin=f"pseudo-gold line {line_number}"
            )
            if question_id in selected:
                raise ValueError(f"pseudo-gold contains duplicate question_id {question_id!r}")
            decision = row.get("decision")
            if decision not in _GOLD_DECISIONS:
                raise ValueError(f"pseudo-gold line {line_number}: unsupported decision")
            selected[question_id] = dict(row)
    if not selected:
        raise ValueError("pseudo-gold contains no review records")
    return selected


def _route_identity(route_key: Mapping[str, object]) -> str:
    return "|".join(
        str(route_key.get(key) or "<missing>")
        for key in ("scope", "declared_type_structure", "declared_type_name")
    )


def _split_assignments(
    source_by_question: Mapping[str, Mapping[str, Any]],
    gold_by_question: Mapping[str, Mapping[str, Any]],
    *,
    seed: str,
) -> dict[str, str]:
    strata: defaultdict[tuple[str, str], list[str]] = defaultdict(list)
    for question_id, gold in gold_by_question.items():
        source = source_by_question[question_id]
        route = _route_key(source)
        strata[(str(gold["decision"]), _route_identity(route))].append(question_id)
    assignments: dict[str, str] = {}
    for stratum, question_ids in sorted(strata.items()):
        ordered = sorted(
            question_ids,
            key=lambda item: hashlib.sha256(
                f"{seed}|{stratum[0]}|{stratum[1]}|{item}".encode("utf-8")
            ).hexdigest(),
        )
        train_end = round(len(ordered) * 0.60)
        dev_end = train_end + round(len(ordered) * 0.20)
        for index, question_id in enumerate(ordered):
            assignments[question_id] = (
                "definition_train"
                if index < train_end
                else "definition_dev"
                if index < dev_end
                else "locked_test"
            )
    return assignments


def build_terminal_label_stability_packet(
    materialized_path: Path,
    *,
    pseudo_gold_path: Path,
    verify_label: str,
    rulebook: KnowledgeRulebook,
    migration: KnowledgeTaxonomyMigration,
    output_path: Path,
    seed: str,
) -> dict[str, object]:
    """Join reviewed questions and emit definition variants without prompt leakage."""
    if output_path.exists():
        raise FileExistsError(f"terminal stability packet already exists: {output_path}")
    rendered = _text(verify_label, field="verify_label", origin="request")
    canonical = _canonical_label(rendered, migration=migration, rulebook=rulebook)
    record = rulebook.records[canonical]
    source_by_question = _read_materialized(materialized_path, verify_label=rendered)
    gold_by_question = _read_pseudo_gold(pseudo_gold_path, verify_label=rendered)
    unknown_gold = sorted(set(gold_by_question) - set(source_by_question))
    if unknown_gold:
        raise ValueError(f"pseudo-gold question is absent from materialized source: {unknown_gold[0]}")
    assignments = _split_assignments(
        source_by_question, gold_by_question, seed=seed
    )
    variants = [
        ("D0", record.marking_interpretation),
        ("D1", record.compressed_definition),
    ]
    if record.definition_override is not None:
        variants.append(("D2", record.definition_override))
    if any(not definition.strip() for _, definition in variants):
        raise ValueError("definition variants must be non-empty")

    packet_rows: list[dict[str, object]] = []
    for question_id in sorted(gold_by_question):
        source = source_by_question[question_id]
        input_text = _text(source.get("input"), field="input", origin=f"question {question_id}")
        question_text = clean_final_label_question(input_text)
        route_key = _route_key(source)
        parent_id = _text(
            source.get("parent_id"), field="parent_id", origin=f"question {question_id}"
        )
        for variant, definition in variants:
            packet_rows.append(
                {
                    "schema_version": PACKET_SCHEMA_VERSION,
                    "review_id": f"{PROMPT_VERSION}:{variant}:{canonical}:{question_id}",
                    "question_id": question_id,
                    "parent_id": parent_id,
                    "source_line": source["_source_line"],
                    "legacy_label": rendered,
                    "canonical_label": canonical,
                    "definition_variant": variant,
                    "definition_text": definition.strip(),
                    "question_text": question_text,
                    "route_key": route_key,
                    "pseudo_gold_decision": gold_by_question[question_id]["decision"],
                    "split": assignments[question_id],
                    "split_seed": seed,
                    "source_materialized_path": str(materialized_path),
                    "pseudo_gold_path": str(pseudo_gold_path),
                }
            )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as output:
        for row in packet_rows:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {
        "schema_version": "terminal-label-stability-packet-report-v1",
        "output_path": str(output_path),
        "verify_label": rendered,
        "canonical_label": canonical,
        "questions": len(gold_by_question),
        "definition_variants": [item[0] for item in variants],
        "packet_rows": len(packet_rows),
        "split_counts": dict(sorted(Counter(assignments.values()).items())),
        "seed": seed,
    }


def filter_terminal_label_stability_packet(
    rows: Sequence[Mapping[str, object]],
    *,
    split: str,
    definition_variants: frozenset[str] | None = None,
) -> tuple[dict[str, object], ...]:
    """Create a stage-specific packet without changing any row content."""
    if split not in {"definition_train", "definition_dev", "locked_test", "dynamic_verification"}:
        raise ValueError("unsupported terminal stability split")
    selected = []
    seen = set()
    for row in rows:
        if row.get("split") != split:
            continue
        variant = row.get("definition_variant")
        if definition_variants is not None and variant not in definition_variants:
            continue
        review_id = _text(row.get("review_id"), field="review_id", origin="packet row")
        if review_id in seen:
            raise ValueError(f"filtered packet contains duplicate review_id {review_id}")
        seen.add(review_id)
        selected.append(dict(row))
    return tuple(selected)


def build_terminal_label_stability_prompt(row: Mapping[str, Any]) -> str:
    """Render only question, target label, and one definition variant."""
    label = _text(row.get("legacy_label"), field="legacy_label")
    definition = _text(row.get("definition_text"), field="definition_text")
    question = _text(row.get("question_text"), field="question_text")
    return f"""你是初中英语知识点审核员。只判断给定知识点是否直接适用于当前题目。

待验证知识点：
{label}

知识点释义：
{definition}

题目内容：
{question}

判定规则：
- keep：题目答案必须直接依赖该释义所述知识点。
- non_target：题目信息充分，但答案不依赖该知识点；不能因为题面出现相关词或结构就保留。
- insufficient：缺少题干、选项、答案、解析、音频、图片或必要上下文，无法可靠判断。
- 允许同题存在其他并行知识点；其他标签存在不构成排除本标签的理由。

只输出 JSON：
{{"decision":"keep|non_target|insufficient","confidence":"high|medium|low","criterion_evidence":["直接依赖题面的短证据"],"missing_context":["缺失信息"]}}"""


def _string_tuple(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise LabelingServiceError(f"terminal stability response {field} must be a string list")
    return tuple(item.strip() for item in value)


class TerminalLabelStabilityClient:
    """OpenAI-compatible client with thinking explicitly disabled for repeatability."""

    def __init__(
        self,
        config: LabelingServiceConfig,
        *,
        transport: Transport | None = None,
    ):
        if not config.endpoint:
            raise ValueError("terminal stability endpoint must be non-empty")
        self._config = config
        self._transport = transport or _http_transport

    def classify(self, row: Mapping[str, Any]) -> TerminalLabelStabilityResult:
        prompt = build_terminal_label_stability_prompt(row)
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        started = time.perf_counter_ns()
        response = self._transport(
            self._config.endpoint,
            {
                "model": self._config.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": self._config.max_tokens,
                "temperature": 0.0,
                "chat_template_kwargs": {"enable_thinking": False},
            },
            self._config.timeout_seconds,
            headers,
        )
        try:
            raw = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise LabelingServiceError("terminal stability response has no content") from error
        if not isinstance(raw, str):
            raise LabelingServiceError("terminal stability response content must be a string")
        payload = _extract_json_payload(raw)
        decision = payload.get("decision")
        confidence = payload.get("confidence")
        if decision not in _DECISIONS:
            raise LabelingServiceError("terminal stability response has unsupported decision")
        if confidence not in _CONFIDENCES:
            raise LabelingServiceError("terminal stability response has unsupported confidence")
        evidence = _string_tuple(payload.get("criterion_evidence"), field="criterion_evidence")
        missing = _string_tuple(payload.get("missing_context"), field="missing_context")
        if decision == "keep" and not evidence:
            raise LabelingServiceError("terminal stability keep requires criterion evidence")
        if decision == "insufficient" and not missing:
            raise LabelingServiceError("terminal stability insufficient requires missing context")
        return TerminalLabelStabilityResult(
            decision=str(decision),
            confidence=str(confidence),
            criterion_evidence=evidence,
            missing_context=missing,
            raw_response=raw,
            elapsed_ms=(time.perf_counter_ns() - started) / 1_000_000,
            prompt_chars=len(prompt),
        )


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return ordered[index]


def _index_run(
    name: str, rows: Sequence[Mapping[str, object]]
) -> dict[str, Mapping[str, object]]:
    indexed: dict[str, Mapping[str, object]] = {}
    for row in rows:
        review_id = _text(row.get("review_id"), field="review_id", origin=f"run {name}")
        if review_id in indexed:
            raise ValueError(f"run {name}: duplicate review_id {review_id}")
        if row.get("decision") not in _DECISIONS or row.get("confidence") not in _CONFIDENCES:
            raise ValueError(f"run {name}: unsupported decision or confidence")
        indexed[review_id] = row
    return indexed


def summarize_terminal_label_stability_runs(
    packet_rows: Sequence[Mapping[str, object]],
    *,
    runs: Sequence[tuple[str, Sequence[Mapping[str, object]]]],
) -> dict[str, object]:
    """Compare exactly three repeat runs against fixed pseudo-gold metadata."""
    if len(runs) != 3:
        raise ValueError("terminal stability analysis requires exactly three runs")
    packet_index: dict[str, Mapping[str, object]] = {}
    for row in packet_rows:
        review_id = _text(row.get("review_id"), field="review_id", origin="packet")
        if review_id in packet_index:
            raise ValueError(f"packet contains duplicate review_id {review_id}")
        if row.get("pseudo_gold_decision") not in _GOLD_DECISIONS:
            raise ValueError("packet contains unsupported pseudo-gold decision")
        packet_index[review_id] = row
    indexes = tuple(_index_run(name, rows) for name, rows in runs)
    for (name, _), index in zip(runs, indexes):
        if set(index) != set(packet_index):
            raise ValueError(f"run {name}: review_id set does not match packet")

    grouped: defaultdict[str, list[str]] = defaultdict(list)
    for review_id, row in packet_index.items():
        key = "|".join(
            (
                str(row.get("canonical_label")),
                str(row.get("definition_variant")),
                str(row.get("split")),
            )
        )
        grouped[key].append(review_id)

    groups: dict[str, object] = {}
    for key, review_ids in sorted(grouped.items()):
        agreements = 0
        unanimous_keep: list[str] = []
        unanimous_high_keep: list[str] = []
        elapsed: list[float] = []
        prompt_chars: list[float] = []
        for review_id in review_ids:
            decisions = tuple(str(index[review_id]["decision"]) for index in indexes)
            confidences = tuple(str(index[review_id]["confidence"]) for index in indexes)
            if len(set(decisions)) == 1:
                agreements += 1
            if decisions == ("keep", "keep", "keep"):
                unanimous_keep.append(review_id)
                if confidences == ("high", "high", "high"):
                    unanimous_high_keep.append(review_id)
            for index in indexes:
                value = index[review_id].get("elapsed_ms")
                if isinstance(value, (int, float)):
                    elapsed.append(float(value))
                chars = index[review_id].get("prompt_chars")
                if isinstance(chars, (int, float)):
                    prompt_chars.append(float(chars))
        gold_keep = {
            review_id
            for review_id in review_ids
            if packet_index[review_id]["pseudo_gold_decision"] == "keep"
        }
        keep_correct = len(set(unanimous_keep) & gold_keep)
        precision = keep_correct / len(unanimous_keep) if unanimous_keep else None
        recall = keep_correct / len(gold_keep) if gold_keep else None
        high_false = sum(
            packet_index[review_id]["pseudo_gold_decision"] != "keep"
            for review_id in unanimous_high_keep
        )
        high_false_rate = (
            high_false / len(unanimous_high_keep) if unanimous_high_keep else 0.0
        )
        uncertain_high_keep = sum(
            packet_index[review_id]["pseudo_gold_decision"] == "uncertain"
            for review_id in unanimous_high_keep
        )
        agreement = agreements / len(review_ids) if review_ids else None
        passes = bool(
            agreement is not None
            and agreement >= 0.95
            and precision is not None
            and precision >= 0.95
            and high_false_rate <= 0.01
            and uncertain_high_keep == 0
        )
        groups[key] = {
            "records": len(review_ids),
            "three_run_decision_agreement": agreement,
            "unanimous_keep": len(unanimous_keep),
            "unanimous_high_keep": len(unanimous_high_keep),
            "unanimous_keep_precision": precision,
            "unanimous_keep_recall": recall,
            "high_confidence_false_positive_rate": high_false_rate,
            "uncertain_unanimous_high_keep": uncertain_high_keep,
            "elapsed_ms": {
                "count": len(elapsed),
                "p50": _percentile(elapsed, 0.50),
                "p95": _percentile(elapsed, 0.95),
            },
            "mean_prompt_chars": (
                sum(prompt_chars) / len(prompt_chars) if prompt_chars else None
            ),
            "passes_precision_first_gate": passes,
        }
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "runs": [name for name, _ in runs],
        "packet_records": len(packet_index),
        "groups": groups,
    }


def _selection_rank(group: Mapping[str, object]) -> tuple[float, float, float, float]:
    precision = group.get("unanimous_keep_precision")
    agreement = group.get("three_run_decision_agreement")
    false_rate = group.get("high_confidence_false_positive_rate")
    prompt_chars = group.get("mean_prompt_chars")
    return (
        float(precision) if isinstance(precision, (int, float)) else -1.0,
        float(agreement) if isinstance(agreement, (int, float)) else -1.0,
        -float(false_rate) if isinstance(false_rate, (int, float)) else -1.0,
        -float(prompt_chars) if isinstance(prompt_chars, (int, float)) else float("-inf"),
    )


def select_stable_definition_variants(
    summary: Mapping[str, object],
    *,
    split: str,
    allowed_variants_by_label: Mapping[str, frozenset[str]] | None = None,
) -> dict[str, object]:
    """Select the best passing variant per label for one frozen split."""
    if split not in {"definition_dev", "locked_test"}:
        raise ValueError("definition selection split must be definition_dev or locked_test")
    groups = summary.get("groups")
    if not isinstance(groups, Mapping):
        raise ValueError("terminal stability summary groups must be an object")
    by_label: defaultdict[str, list[tuple[str, Mapping[str, object]]]] = defaultdict(list)
    for key, group in groups.items():
        if not isinstance(key, str) or not isinstance(group, Mapping):
            continue
        parts = key.rsplit("|", 2)
        if len(parts) != 3 or parts[2] != split:
            continue
        label, variant = parts[0], parts[1]
        allowed = (allowed_variants_by_label or {}).get(label)
        if allowed is not None and variant not in allowed:
            continue
        by_label[label].append((variant, group))
    selected = {}
    for label, candidates in sorted(by_label.items()):
        passing = [
            item for item in candidates if item[1].get("passes_precision_first_gate") is True
        ]
        if not passing:
            selected[label] = {
                "status": "hold",
                "reason": "no definition variant passes precision-first gate",
            }
            continue
        best = max(passing, key=lambda item: (_selection_rank(item[1]), item[0]))
        selected[label] = {
            "status": "selected",
            "definition_variant": best[0],
            "metrics": dict(best[1]),
        }
    return {
        "schema_version": "terminal-label-definition-selection-v1",
        "split": split,
        "labels": selected,
    }


def assemble_terminal_stability_decisions(
    packet_rows: Sequence[Mapping[str, object]],
    *,
    runs: Sequence[tuple[str, Sequence[Mapping[str, object]]]],
    definition_selection: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    """Emit precision-first experimental keep/drop candidates or hold."""
    if len(runs) != 3:
        raise ValueError("terminal stability decisions require exactly three runs")
    raw_labels = definition_selection.get("labels")
    if not isinstance(raw_labels, Mapping):
        raise ValueError("definition selection labels must be an object")
    selected = {
        str(label): item.get("definition_variant")
        for label, item in raw_labels.items()
        if isinstance(item, Mapping)
        and item.get("status") == "selected"
        and isinstance(item.get("definition_variant"), str)
    }
    packet_index: dict[str, Mapping[str, object]] = {}
    for row in packet_rows:
        review_id = _text(row.get("review_id"), field="review_id", origin="packet")
        label = row.get("canonical_label")
        if not isinstance(label, str) or row.get("definition_variant") != selected.get(label):
            continue
        if review_id in packet_index:
            raise ValueError(f"selected packet contains duplicate review_id {review_id}")
        packet_index[review_id] = row
    indexes = tuple(_index_run(name, rows) for name, rows in runs)
    for (name, _), index in zip(runs, indexes):
        missing = set(packet_index) - set(index)
        if missing:
            raise ValueError(f"run {name} is missing selected review_id {sorted(missing)[0]}")
    decisions = []
    for review_id, packet in sorted(packet_index.items()):
        outcomes = tuple(
            (index[review_id].get("decision"), index[review_id].get("confidence"))
            for index in indexes
        )
        pseudo_gold = packet.get("pseudo_gold_decision")
        if pseudo_gold == "uncertain":
            disposition = "hold"
            reason = "pseudo_gold_uncertain"
        elif outcomes == (("keep", "high"),) * 3:
            disposition = "stable_keep_candidate"
            reason = "three_run_unanimous_high_keep"
        elif outcomes == (("non_target", "high"),) * 3:
            disposition = "stable_drop_candidate"
            reason = "three_run_unanimous_high_non_target"
        else:
            disposition = "hold"
            reason = "decision_or_confidence_not_unanimous"
        decisions.append(
            {
                "schema_version": "terminal-label-stability-decision-v1",
                "review_id": review_id,
                "question_id": packet.get("question_id"),
                "canonical_label": packet.get("canonical_label"),
                "definition_variant": packet.get("definition_variant"),
                "pseudo_gold_decision": pseudo_gold,
                "run_outcomes": [
                    {"decision": decision, "confidence": confidence}
                    for decision, confidence in outcomes
                ],
                "disposition": disposition,
                "reason": reason,
            }
        )
    return tuple(decisions)
