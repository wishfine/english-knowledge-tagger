"""Build sanitized packets for an unanchored final label discriminator."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import time
from dataclasses import dataclass
from typing import Any, Mapping

from .candidate_labeling import LabelingServiceConfig, LabelingServiceError, Transport, _http_transport
from .knowledge_rulebook import KnowledgeRulebook
from .knowledge_taxonomy_migration import KnowledgeTaxonomyMigration
from .mentor_direct_rollout import load_mentor_label_definitions


FINAL_PROMPT_VERSION = "final-label-discriminator-v1"
FINAL_PACKET_SCHEMA_VERSION = "final-label-discriminator-packet-v1"
_REMOVED_INPUT_PREFIXES = (
    "题型结构为：",
    "题型名称为：",
    "所给图片为题目题干",
)
_REMOVED_SFT_OUTPUT_PREFIXES = (
    "根据以上信息，当前题目所属的题型方法类目和知识点类目为：",
)
_CONFIDENCE_VALUES = frozenset({"high", "medium", "low"})


@dataclass(frozen=True)
class FinalLabelDiscriminatorRequest:
    packet_row: Mapping[str, Any]


@dataclass(frozen=True)
class FinalLabelDiscriminatorResult:
    review_id: str
    model: str
    endpoint: str
    prompt_version: str
    request_id: str | None
    raw_response: str
    llm_match: bool
    confidence: str
    reason: str
    prompt_chars: int
    response_chars: int
    model_call_elapsed_ms: float


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def clean_final_label_question(input_text: str) -> str:
    """Remove model-forbidden metadata while preserving question content."""
    if not isinstance(input_text, str):
        raise ValueError("input must be a string")
    lines = [
        line
        for line in input_text.splitlines()
        if not line.strip().startswith(_REMOVED_INPUT_PREFIXES + _REMOVED_SFT_OUTPUT_PREFIXES)
    ]
    question_text = "\n".join(lines).strip()
    if not question_text:
        raise ValueError("question content is empty after metadata removal")
    if len(question_text) > 2000:
        return question_text[:2000] + "...（截断）"
    return question_text


def _required_route_key(value: object, *, source: str) -> dict[str, str | None]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{source}: route_key must be an object")
    scope = value.get("scope")
    if scope not in {"parent", "child"}:
        raise ValueError(f"{source}: route_key.scope must be parent or child")
    route_key: dict[str, str | None] = {"scope": scope}
    for key in ("declared_type_structure", "declared_type_name"):
        item = value.get(key)
        if item is not None and not isinstance(item, str):
            raise ValueError(f"{source}: route_key.{key} must be a string or null")
        route_key[key] = item.strip() if isinstance(item, str) and item.strip() else None
    return route_key


def build_final_label_discriminator_packet(
    eligible_packet_path: Path,
    *,
    label_definitions_path: Path,
    output_path: Path,
) -> dict[str, object]:
    """Sanitize one route-eligible mentor packet without modifying its source."""
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite existing final discriminator packet: {output_path}")
    label_definitions = load_mentor_label_definitions(label_definitions_path)
    definition_sha256 = hashlib.sha256(label_definitions_path.read_bytes()).hexdigest()
    selected = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with eligible_packet_path.open("r", encoding="utf-8") as source, output_path.open(
        "x", encoding="utf-8"
    ) as output:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                source_row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"eligible packet line {line_number}: invalid JSON") from error
            if not isinstance(source_row, Mapping):
                raise ValueError(f"eligible packet line {line_number}: JSONL row must be an object")
            source_name = f"eligible packet line {line_number}"
            if source_row.get("schema_version") != "mentor-label-rollout-packet-v1":
                raise ValueError(f"{source_name}: unexpected packet schema_version")
            if source_row.get("rollout_route_decision") != "eligible":
                raise ValueError(f"{source_name}: packet must have rollout_route_decision=eligible")
            verify_label = _text(source_row.get("verify_label"), field=f"{source_name}: verify_label")
            if verify_label not in label_definitions:
                raise ValueError(f"{source_name}: verify_label is absent from label definitions")
            question_id = _text(source_row.get("question_id"), field=f"{source_name}: question_id")
            parent_id = _text(source_row.get("parent_id"), field=f"{source_name}: parent_id")
            source_line = source_row.get("source_line")
            if not isinstance(source_line, int) or isinstance(source_line, bool) or source_line <= 0:
                raise ValueError(f"{source_name}: source_line must be a positive integer")
            is_sub_question = source_row.get("is_sub_question")
            if not isinstance(is_sub_question, bool):
                raise ValueError(f"{source_name}: is_sub_question must be boolean")
            packet_row = {
                "schema_version": FINAL_PACKET_SCHEMA_VERSION,
                "review_id": f"{FINAL_PROMPT_VERSION}:{source_line}:{verify_label}",
                "question_id": question_id,
                "parent_id": parent_id,
                "source_line": source_line,
                "is_sub_question": is_sub_question,
                "route_key": _required_route_key(source_row.get("route_key"), source=source_name),
                "verify_label": verify_label,
                "question_text": clean_final_label_question(source_row.get("input")),
                "source_packet_path": str(eligible_packet_path),
                "source_path": source_row.get("source_path"),
                "label_definitions_path": str(label_definitions_path),
                "label_definitions_sha256": definition_sha256,
            }
            output.write(json.dumps(packet_row, ensure_ascii=False, sort_keys=True) + "\n")
            selected += 1
    return {
        "schema_version": "final-label-discriminator-packet-report-v1",
        "prompt_version": FINAL_PROMPT_VERSION,
        "eligible_packet_path": str(eligible_packet_path),
        "label_definitions_path": str(label_definitions_path),
        "label_definitions_sha256": definition_sha256,
        "output_path": str(output_path),
        "selected_records": selected,
    }


def build_final_label_discriminator_prompt(
    packet_row: Mapping[str, Any], *, label_definitions: Mapping[str, Mapping[str, Any]]
) -> str:
    """Render an unanchored direct-label decision prompt.

    Route metadata intentionally remains outside this function: it is a
    business eligibility rule, not evidence visible to the language model.
    """
    label = _text(packet_row.get("verify_label"), field="packet verify_label")
    definition = label_definitions.get(label)
    if definition is None:
        raise ValueError("packet verify_label must have an exact label definition")
    question_text = _text(packet_row.get("question_text"), field="packet question_text")
    return f"""你是一位资深的初中英语教研老师，需要核验一个候选知识点标签是否适用于给定题目。

## 待验证标签
{label}

## 标签释义
{_text(definition.get("definition"), field="label definition")}

## 题目内容
{question_text}

## 判断要求
仅依据题目内容和标签释义判断。题目必须直接考查该标签所述的知识点才可判定为 true；不要因为答案词性、题目背景或其他可能知识点而勉强判定。若题目信息不足，或无法确认是否直接考查该知识点，判定为 false 并说明信息缺失或边界原因。

请仅输出 JSON，不要输出 Markdown 或其他文字：
{{"match": true/false, "confidence": "high"/"medium"/"low", "reason": "不超过80字的判断依据"}}
"""


def _strip_fence(text: str) -> str:
    normalized = text.strip()
    if normalized.startswith("```"):
        normalized = normalized.split("\n", 1)[1] if "\n" in normalized else normalized[3:]
    if normalized.endswith("```"):
        normalized = normalized[:-3]
    return normalized.strip()


def _parse_final_label_response(text: str) -> tuple[bool, str, str]:
    normalized = _strip_fence(text)
    try:
        payload = json.loads(normalized)
    except json.JSONDecodeError:
        matched = re.search(r"\{[^{}]+\}", normalized, re.DOTALL)
        if matched is None:
            raise LabelingServiceError("final label discriminator response is not valid JSON")
        try:
            payload = json.loads(matched.group())
        except json.JSONDecodeError as error:
            raise LabelingServiceError("final label discriminator response is not valid JSON") from error
    if not isinstance(payload, Mapping) or not isinstance(payload.get("match"), bool):
        raise LabelingServiceError("final label discriminator response must contain boolean match")
    confidence = payload.get("confidence")
    reason = payload.get("reason")
    if confidence not in _CONFIDENCE_VALUES:
        raise LabelingServiceError("final label discriminator confidence must be high, medium, or low")
    if not isinstance(reason, str) or not reason.strip():
        raise LabelingServiceError("final label discriminator reason must be a non-empty string")
    return payload["match"], confidence, reason.strip()


class FinalLabelDiscriminatorClient:
    """Retrying OpenAI-compatible client for unanchored final label decisions."""

    def __init__(
        self,
        config: LabelingServiceConfig,
        *,
        label_definitions: Mapping[str, Mapping[str, Any]],
        transport: Transport | None = None,
        max_retries: int = 3,
        retry_delay_seconds: float = 2.0,
    ):
        if not config.endpoint:
            raise ValueError("final label discriminator endpoint must be non-empty")
        if max_retries <= 0:
            raise ValueError("max_retries must be positive")
        if retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds must be non-negative")
        self._config = config
        self._label_definitions = label_definitions
        self._transport = transport or _http_transport
        self._max_retries = max_retries
        self._retry_delay_seconds = retry_delay_seconds

    def verify(self, request: FinalLabelDiscriminatorRequest) -> FinalLabelDiscriminatorResult:
        review_id = _text(request.packet_row.get("review_id"), field="packet review_id")
        prompt = build_final_label_discriminator_prompt(
            request.packet_row, label_definitions=self._label_definitions
        )
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        payload = {
            "model": self._config.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 512,
            "chat_template_kwargs": {"enable_thinking": False},
            "temperature": 0,
        }
        last_error: LabelingServiceError | None = None
        call_started_ns = time.perf_counter_ns()
        response: Mapping[str, Any] | None = None
        for attempt in range(self._max_retries):
            try:
                response = self._transport(
                    self._config.endpoint, payload, self._config.timeout_seconds, headers
                )
                break
            except LabelingServiceError as error:
                last_error = error
                if attempt + 1 < self._max_retries and self._retry_delay_seconds:
                    time.sleep(self._retry_delay_seconds)
        if response is None:
            raise last_error or LabelingServiceError("final label discriminator request failed")
        try:
            raw_response = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise LabelingServiceError(
                "final label discriminator response has no choices[0].message.content"
            ) from error
        if not isinstance(raw_response, str):
            raise LabelingServiceError("final label discriminator completion content must be a string")
        llm_match, confidence, reason = _parse_final_label_response(raw_response)
        return FinalLabelDiscriminatorResult(
            review_id=review_id,
            model=response.get("model") if isinstance(response.get("model"), str) else self._config.model,
            endpoint=self._config.endpoint,
            prompt_version=FINAL_PROMPT_VERSION,
            request_id=response.get("id") if isinstance(response.get("id"), str) else None,
            raw_response=raw_response,
            llm_match=llm_match,
            confidence=confidence,
            reason=reason,
            prompt_chars=len(prompt),
            response_chars=len(raw_response),
            model_call_elapsed_ms=(time.perf_counter_ns() - call_started_ns) / 1_000_000,
        )


def _canonical_label(
    verify_label: object, *, rulebook: KnowledgeRulebook, migration: KnowledgeTaxonomyMigration
) -> str:
    label = _text(verify_label, field="verify_label")
    if not label.startswith("知识点@"):
        raise ValueError("verify_label must be a rendered knowledge label beginning with 知识点@")
    legacy_path = "知识点->" + label.removeprefix("知识点@").replace("@", "->")
    canonical = migration.canonicalize(legacy_path).canonical_path
    taxonomy = rulebook.records.get(canonical)
    if taxonomy is None or taxonomy.status != "active":
        raise ValueError("verify_label must map to an active teacher terminal label")
    return canonical


def final_result_to_evidence(
    packet_row: Mapping[str, Any],
    *,
    result: FinalLabelDiscriminatorResult,
    rulebook: KnowledgeRulebook,
    migration: KnowledgeTaxonomyMigration,
) -> dict[str, Any]:
    """Create gate-compatible evidence without reintroducing hidden prompt fields."""
    question_text = _text(packet_row.get("question_text"), field="packet question_text")
    return {
        "schema_version": "terminal-label-discriminator-evidence-v1",
        "review_id": result.review_id,
        "question_id": packet_row.get("question_id"),
        "parent_id": packet_row.get("parent_id"),
        "source_line": packet_row.get("source_line"),
        "is_sub_question": packet_row.get("is_sub_question"),
        "route_key": packet_row.get("route_key"),
        "legacy_label": packet_row.get("verify_label"),
        "canonical_label": _canonical_label(
            packet_row.get("verify_label"), rulebook=rulebook, migration=migration
        ),
        "llm_match": result.llm_match,
        "status": "candidate",
        "model": result.model,
        "endpoint": result.endpoint,
        "prompt_version": result.prompt_version,
        "request_id": result.request_id,
        "confidence": result.confidence,
        "reason": result.reason,
        "raw_response": result.raw_response,
        "model_call_elapsed_ms": result.model_call_elapsed_ms,
        "prompt_chars": result.prompt_chars,
        "response_chars": result.response_chars,
        "source_packet_path": packet_row.get("source_packet_path"),
        "source_path": packet_row.get("source_path"),
        "label_definitions_path": packet_row.get("label_definitions_path"),
        "label_definitions_sha256": packet_row.get("label_definitions_sha256"),
        "question_text_sha256": hashlib.sha256(question_text.encode("utf-8")).hexdigest(),
    }


def final_error_to_evidence(
    packet_row: Mapping[str, Any],
    *,
    error: Exception,
    rulebook: KnowledgeRulebook,
    migration: KnowledgeTaxonomyMigration,
    model: str,
    endpoint: str,
) -> dict[str, Any]:
    """Keep model/parse failures explicit and holdable without source mutation."""
    question_text = _text(packet_row.get("question_text"), field="packet question_text")
    return {
        "schema_version": "terminal-label-discriminator-evidence-v1",
        "review_id": packet_row.get("review_id"),
        "question_id": packet_row.get("question_id"),
        "parent_id": packet_row.get("parent_id"),
        "source_line": packet_row.get("source_line"),
        "is_sub_question": packet_row.get("is_sub_question"),
        "route_key": packet_row.get("route_key"),
        "legacy_label": packet_row.get("verify_label"),
        "canonical_label": _canonical_label(
            packet_row.get("verify_label"), rulebook=rulebook, migration=migration
        ),
        "llm_match": None,
        "status": "error",
        "model": model,
        "endpoint": endpoint,
        "prompt_version": FINAL_PROMPT_VERSION,
        "error": str(error),
        "source_packet_path": packet_row.get("source_packet_path"),
        "source_path": packet_row.get("source_path"),
        "label_definitions_path": packet_row.get("label_definitions_path"),
        "label_definitions_sha256": packet_row.get("label_definitions_sha256"),
        "question_text_sha256": hashlib.sha256(question_text.encode("utf-8")).hexdigest(),
    }
