"""Validate web-GPT reviews made directly against one mentor verifier JSONL."""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import re
from typing import Mapping


SCHEMA_VERSION = "web-gpt-raw-review-evidence-v1"
_DECISIONS = ("keep", "remove", "uncertain")
_CONCLUSION_DISPOSITIONS = (
    "p0_remediation",
    "route_segment_candidate",
    "teacher_policy_required",
    "hold",
)
_REASON_CODES = {
    "transitivity_contrast",
    "object_case",
    "double_object",
    "object_complement",
    "passive_requirement",
    "lexical_or_spelling_only",
    "tense_or_aux_only",
    "fixed_phrase_only",
    "insufficient_context",
    "definition_conflict",
    "other",
}
_TYPE_METADATA = re.compile(r"(?m)^题型(结构|名称)为：([^\r\n]*)")


def _string(value: object, *, field: str, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: {field} must be a non-empty string")
    return value.strip()


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _read_source_jsonl(path: Path, *, verify_label: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen_question_ids: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for source_line, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"source line {source_line}: invalid JSON") from error
            if not isinstance(raw, Mapping):
                raise ValueError(f"source line {source_line}: JSONL row must be an object")
            source = f"source line {source_line}"
            if _string(raw.get("verify_label"), field="verify_label", source=source) != verify_label:
                raise ValueError(f"{source}: verify_label differs from requested label")
            question_id = _string(raw.get("question_id"), field="question_id", source=source)
            if question_id in seen_question_ids:
                raise ValueError(f"{source}: duplicate question_id {question_id!r}")
            seen_question_ids.add(question_id)
            parent_id = _string(raw.get("parent_id"), field="parent_id", source=source)
            direct_match = raw.get("llm_match")
            if not isinstance(direct_match, bool):
                raise ValueError(f"{source}: llm_match must be boolean")
            input_text = _string(raw.get("input"), field="input", source=source)
            metadata = {match.group(1): match.group(2).strip() for match in _TYPE_METADATA.finditer(input_text)}
            route = {
                "scope": "child" if raw.get("is_sub_question") is True else "parent" if raw.get("is_sub_question") is False else "unknown",
                "declared_type_structure": metadata.get("结构") or "缺失",
                "declared_type_name": metadata.get("名称") or "缺失",
            }
            rows.append(
                {
                    "source_line": source_line,
                    "question_id": question_id,
                    "parent_id": parent_id,
                    "route_key": route,
                    "direct_match": direct_match,
                    "direct_should_be": _optional_string(raw.get("llm_should_be")),
                }
            )
    return rows


def _parse_object_stream(path: Path) -> list[dict[str, object]]:
    raw = path.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    position = 0
    rows: list[dict[str, object]] = []
    while position < len(raw):
        while position < len(raw) and raw[position].isspace():
            position += 1
        if position == len(raw):
            break
        try:
            item, position = decoder.raw_decode(raw, position)
        except json.JSONDecodeError as error:
            raise ValueError(f"reviewer results byte {position}: invalid JSON object stream") from error
        if not isinstance(item, dict):
            raise ValueError(f"reviewer results record {len(rows) + 1}: must be an object")
        rows.append(item)
    return rows


def _route_name(route: Mapping[str, object]) -> str:
    return " × ".join(
        _string(route.get(field), field=f"route_key.{field}", source="source")
        for field in ("scope", "declared_type_structure", "declared_type_name")
    )


def _counts(rows: list[dict[str, object]]) -> dict[str, int]:
    counts = Counter(str(row["decision"]) for row in rows)
    return {decision: counts[decision] for decision in _DECISIONS}


def _group_counts(rows: list[dict[str, object]], *, field: str) -> dict[str, dict[str, int]]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        if field == "route":
            key = _route_name(row["route_key"])
        else:
            value = row.get(field)
            key = value.strip() if isinstance(value, str) and value.strip() else "<none>"
        grouped[key][str(row["decision"])] += 1
    return {
        key: {decision: counts[decision] for decision in _DECISIONS}
        for key, counts in sorted(grouped.items())
    }


def _validate_conclusion(
    conclusion: Mapping[str, object],
    *,
    verify_label: str,
    source_question_ids: set[str],
) -> dict[str, object]:
    """Validate the one optional label-level conclusion from Web GPT.

    This record communicates the reviewer's aggregate recommendation.  It is
    deliberately kept separate from per-question decisions and never changes
    the evidence-only release gate.
    """
    if _string(conclusion.get("verify_label"), field="verify_label", source="label_conclusion") != verify_label:
        raise ValueError("label_conclusion: verify_label differs from requested label")
    disposition = conclusion.get("recommended_disposition")
    if disposition not in _CONCLUSION_DISPOSITIONS:
        raise ValueError(
            "label_conclusion: recommended_disposition must be one of "
            + ", ".join(_CONCLUSION_DISPOSITIONS)
        )
    teacher_question_ids = conclusion.get("teacher_question_ids")
    if not isinstance(teacher_question_ids, list) or len(teacher_question_ids) > 10:
        raise ValueError("label_conclusion: teacher_question_ids must be a list with at most 10 IDs")
    normalized_ids = [_string(item, field="teacher_question_ids item", source="label_conclusion") for item in teacher_question_ids]
    if len(set(normalized_ids)) != len(normalized_ids):
        raise ValueError("label_conclusion: teacher_question_ids contains duplicates")
    unknown_ids = set(normalized_ids) - source_question_ids
    if unknown_ids:
        raise ValueError(f"label_conclusion: unknown teacher_question_id {sorted(unknown_ids)[0]!r}")
    return {
        "recommended_disposition": disposition,
        "teacher_question_ids": normalized_ids,
        "rationale": _string(conclusion.get("rationale"), field="rationale", source="label_conclusion"),
    }


def analyze_web_gpt_raw_reviews(
    source_path: Path,
    *,
    reviewer_results_path: Path,
    verify_label: str,
) -> tuple[dict[str, object], tuple[dict[str, object], ...]]:
    """Validate an anchored web-GPT review of every row in one mentor JSONL.

    The reviewer saw historical/DS fields, so the result is intentionally marked
    as auxiliary evidence only. It cannot directly release or modify labels.
    """
    target = _string(verify_label, field="verify_label", source="web GPT raw review request")
    source_rows = _read_source_jsonl(source_path, verify_label=target)
    source_by_question_id = {str(row["question_id"]): row for row in source_rows}
    parsed_rows = _parse_object_stream(reviewer_results_path)
    conclusion_rows = [row for row in parsed_rows if row.get("record_type") == "label_conclusion"]
    if len(conclusion_rows) > 1:
        raise ValueError("reviewer results: at most one label_conclusion record is allowed")
    if conclusion_rows and parsed_rows[-1] is not conclusion_rows[0]:
        raise ValueError("reviewer results: label_conclusion must be the final record")
    review_rows = [row for row in parsed_rows if row.get("record_type") != "label_conclusion"]
    conclusion = (
        _validate_conclusion(
            conclusion_rows[0],
            verify_label=target,
            source_question_ids=set(source_by_question_id),
        )
        if conclusion_rows
        else None
    )
    review_by_question_id: dict[str, dict[str, object]] = {}
    for position, review in enumerate(review_rows, 1):
        origin = f"reviewer results record {position}"
        question_id = _string(review.get("question_id"), field="question_id", source=origin)
        parent_id = _string(review.get("parent_id"), field="parent_id", source=origin)
        if question_id in review_by_question_id:
            raise ValueError(f"{origin}: duplicate question_id {question_id!r}")
        source_row = source_by_question_id.get(question_id)
        if source_row is None:
            raise ValueError(f"{origin}: unknown question_id {question_id!r}")
        if parent_id != source_row["parent_id"]:
            raise ValueError(f"{origin}: parent_id does not match source for {question_id!r}")
        decision = review.get("decision")
        if decision not in _DECISIONS:
            raise ValueError(f"{origin}: decision must be one of {', '.join(_DECISIONS)}")
        reason_code = review.get("reason_code")
        if reason_code not in _REASON_CODES:
            raise ValueError(f"{origin}: unsupported reason_code {reason_code!r}")
        _string(review.get("reason"), field="reason", source=origin)
        review_by_question_id[question_id] = review

    missing = set(source_by_question_id) - set(review_by_question_id)
    if missing:
        raise ValueError(f"missing reviewer result for question_id {sorted(missing)[0]!r}")

    normalized: list[dict[str, object]] = []
    for source_row in source_rows:
        question_id = str(source_row["question_id"])
        review = review_by_question_id[question_id]
        normalized.append(
            {
                "schema_version": SCHEMA_VERSION,
                "reviewer_mode": "anchored_raw_source_review",
                "verify_label": target,
                "source_line": source_row["source_line"],
                "question_id": question_id,
                "parent_id": source_row["parent_id"],
                "route_key": source_row["route_key"],
                "mentor_direct_verdict": "match" if source_row["direct_match"] else "mismatch",
                "mentor_should_be": source_row["direct_should_be"],
                "decision": review["decision"],
                "reason_code": review["reason_code"],
                "reason": review["reason"].strip(),
            }
        )

    by_mentor: dict[str, Counter[str]] = {"match": Counter(), "mismatch": Counter()}
    conflict_decisions: Counter[str] = Counter()
    for row in normalized:
        by_mentor[str(row["mentor_direct_verdict"])][str(row["decision"])] += 1
        if row["mentor_direct_verdict"] == "mismatch" and row["mentor_should_be"] == "正确":
            conflict_decisions[str(row["decision"])] += 1
    report = {
        "schema_version": "web-gpt-raw-review-analysis-v1",
        "source_path": str(source_path),
        "reviewer_results_path": str(reviewer_results_path),
        "verify_label": target,
        "reviewer_mode": "anchored_raw_source_review",
        "source_records": len(source_rows),
        "review_records": len(review_rows),
        "web_gpt_conclusion": conclusion,
        "decisions": _counts(normalized),
        "by_route": _group_counts(normalized, field="route"),
        "by_reason_code": _group_counts(normalized, field="reason_code"),
        "mentor_direct_verdict_x_web_decision": {
            verdict: {decision: by_mentor[verdict][decision] for decision in _DECISIONS}
            for verdict in ("match", "mismatch")
        },
        "mentor_contract_conflict_web_decisions": {
            decision: conflict_decisions[decision] for decision in _DECISIONS
        },
        "release_status": "reviewer_evidence_only",
        "note": "reviewer saw raw historical/mentor fields; use only with independent calibration or teacher adjudication",
    }
    return report, tuple(normalized)
