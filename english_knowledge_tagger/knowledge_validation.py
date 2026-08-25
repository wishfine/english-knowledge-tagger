"""Auditable DS-V4 validation of one historical knowledge-point label at a time."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping

from .candidate_labeling import (
    LabelingServiceConfig,
    LabelingServiceError,
    Transport,
    _http_transport,
)


PROMPT_VERSION = "knowledge-label-validation-ds-v4-v2"
VERDICTS = frozenset({"keep", "replace", "drop", "uncertain"})


@dataclass(frozen=True)
class ValidationAlternative:
    label: str
    definition: str


@dataclass(frozen=True)
class KnowledgeValidationRequest:
    review_id: str
    question_context: str
    legacy_label: str
    target_definition: str
    alternatives: tuple[ValidationAlternative, ...]
    max_output_labels: int
    target_is_type_allowed: bool = True


@dataclass(frozen=True)
class ParsedValidation:
    status: str
    verdict: str | None
    candidate_coverage: str | None
    best_label: str | None
    evidence: str | None
    reason: str | None
    error: str | None


@dataclass(frozen=True)
class KnowledgeValidationResult:
    review_id: str
    model: str
    prompt_version: str
    request_id: str | None
    raw_response: str
    status: str
    verdict: str | None
    candidate_coverage: str | None
    best_label: str | None
    evidence: str | None
    reason: str | None
    error: str | None


def _json_example() -> str:
    return (
        '{"verdict":"keep|replace|drop|uncertain",'
        '"best_label":"候选标签路径或null",'
        '"candidate_coverage":"covered|insufficient|unknown",'
        '"evidence":"题干、答案或解析中的短证据",'
        '"reason":"判定理由"}'
    )


def build_knowledge_validation_prompt(request: KnowledgeValidationRequest) -> str:
    """Render one-label validation prompt with a bounded, type-constrained pool."""
    alternatives = "\n".join(
        f"- {item.label}\n  压缩释义：{item.definition}" for item in request.alternatives
    ) or "- （没有可用近邻候选；如无法判断请输出 uncertain）"
    target_constraint = (
        "当前历史标签不在该小题题型允许的知识点范围内，不能输出 keep；只能选择给出的替换候选，或输出 drop/uncertain。\n"
        if not request.target_is_type_allowed
        else ""
    )
    return (
        "你在复核一道英语小题的一个历史知识点标签。历史标签不是事实，必须以题干、选项、答案和解析为准。\n"
        "本轮只验证当前这一个历史标签：不要因为题中出现其他考点而额外添加标签。\n"
        "候选标签来自该小题题型允许的知识点池；best_label 只能选择当前标签、下面列出的候选标签或 null，不能杜撰。\n"
        "判定规则：\n"
        "- keep：当前标签是解题必需的核心考点，best_label 必须为当前标签。\n"
        "- replace：当前标签不合适，但一个列出的候选标签更合适，best_label 必须为该候选。\n"
        "- drop：当前标签不是解题必需考点，且候选中没有应替换标签，best_label 必须为 null。\n"
        "- uncertain：题目信息不足、候选池未覆盖或无法可靠判断，best_label 必须为 null。\n"
        "- candidate_coverage：若候选池足以判断填 covered；若正确标签可能不在候选池中填 insufficient；题面无法判断覆盖情况填 unknown。\n"
        "- 若 candidate_coverage 不是 covered，不得输出 keep、replace 或 drop，必须输出 uncertain。\n"
        f"{target_constraint}"
        "只输出一个 JSON 对象，不要 Markdown、解释前缀或额外字段。格式：\n"
        f"{_json_example()}\n\n"
        f"待验证历史标签：{request.legacy_label}\n"
        f"该标签原始释义：{request.target_definition}\n\n"
        "可替换的近邻候选标签及压缩释义：\n"
        f"{alternatives}\n\n"
        "题目信息：\n"
        f"{request.question_context.strip()}"
    )


def _unparsed(error: str) -> ParsedValidation:
    return ParsedValidation(
        status="unparsed",
        verdict=None,
        candidate_coverage=None,
        best_label=None,
        evidence=None,
        reason=None,
        error=error,
    )


def _strip_code_fence(text: str) -> str:
    normalized = text.strip()
    if normalized.startswith("```") and normalized.endswith("```"):
        lines = normalized.splitlines()
        return "\n".join(lines[1:-1]).strip()
    return normalized


def parse_validation_response(
    text: str,
    *,
    legacy_label: str,
    allowed_labels: frozenset[str],
    target_is_type_allowed: bool = True,
) -> ParsedValidation:
    """Strictly parse a model verdict and reject labels outside the supplied pool."""
    try:
        payload = json.loads(_strip_code_fence(text))
    except json.JSONDecodeError as error:
        return _unparsed(f"response is not valid JSON: {error.msg}")
    if not isinstance(payload, Mapping):
        return _unparsed("response JSON must be an object")
    verdict = payload.get("verdict")
    best_label = payload.get("best_label")
    candidate_coverage = payload.get("candidate_coverage")
    evidence = payload.get("evidence")
    reason = payload.get("reason")
    if not isinstance(verdict, str) or verdict not in VERDICTS:
        return _unparsed("verdict must be keep, replace, drop, or uncertain")
    if candidate_coverage not in {"covered", "insufficient", "unknown"}:
        return _unparsed("candidate_coverage must be covered, insufficient, or unknown")
    if best_label is not None and not isinstance(best_label, str):
        return _unparsed("best_label must be a string or null")
    if isinstance(best_label, str) and best_label not in allowed_labels:
        return _unparsed("best_label is outside the supplied candidate pool")
    if not isinstance(evidence, str) or not isinstance(reason, str):
        return _unparsed("evidence and reason must be strings")
    if verdict == "keep" and not target_is_type_allowed:
        return _unparsed("keep verdict is outside the small-question candidate pool")
    if verdict == "keep" and best_label != legacy_label:
        return _unparsed("keep verdict requires best_label to equal the historical label")
    if verdict == "replace" and (best_label is None or best_label == legacy_label):
        return _unparsed("replace verdict requires a different best_label")
    if verdict in {"drop", "uncertain"} and best_label is not None:
        return _unparsed(f"{verdict} verdict requires best_label to be null")
    if verdict != "uncertain" and candidate_coverage != "covered":
        return _unparsed("non-uncertain verdict requires candidate_coverage to be covered")
    return ParsedValidation(
        status="candidate",
        verdict=verdict,
        candidate_coverage=candidate_coverage,
        best_label=best_label,
        evidence=evidence,
        reason=reason,
        error=None,
    )


class KnowledgeValidationClient:
    """Small dependency-free client that validates one label without changing it."""

    def __init__(self, config: LabelingServiceConfig, *, transport: Transport | None = None):
        if not config.endpoint:
            raise ValueError("validation endpoint must be non-empty")
        self._config = config
        self._transport = transport or _http_transport

    def validate(self, request: KnowledgeValidationRequest) -> KnowledgeValidationResult:
        if not request.review_id.strip() or not request.question_context.strip():
            raise ValueError("review_id and question_context must be non-empty")
        if not request.legacy_label.strip() or not request.target_definition.strip():
            raise ValueError("legacy_label and target_definition must be non-empty")
        if request.max_output_labels <= 0:
            raise ValueError("max_output_labels must be positive")
        if len({alternative.label for alternative in request.alternatives}) != len(request.alternatives):
            raise ValueError("alternative labels must be unique")
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        payload = {
            "model": self._config.model,
            "messages": [{"role": "user", "content": build_knowledge_validation_prompt(request)}],
            "max_tokens": self._config.max_tokens,
            "temperature": 0.0,
        }
        response = self._transport(
            self._config.endpoint, payload, self._config.timeout_seconds, headers
        )
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise LabelingServiceError("validation service response has no choices[0].message.content") from error
        if not isinstance(content, str):
            raise LabelingServiceError("validation completion content must be a string")
        allowed_labels = frozenset(
            {
                *( (request.legacy_label,) if request.target_is_type_allowed else () ),
                *(alternative.label for alternative in request.alternatives),
            }
        )
        parsed = parse_validation_response(
            content,
            legacy_label=request.legacy_label,
            allowed_labels=allowed_labels,
            target_is_type_allowed=request.target_is_type_allowed,
        )
        return KnowledgeValidationResult(
            review_id=request.review_id,
            model=response.get("model") if isinstance(response.get("model"), str) else self._config.model,
            prompt_version=PROMPT_VERSION,
            request_id=response.get("id") if isinstance(response.get("id"), str) else None,
            raw_response=content,
            status=parsed.status,
            verdict=parsed.verdict,
            candidate_coverage=parsed.candidate_coverage,
            best_label=parsed.best_label,
            evidence=parsed.evidence,
            reason=parsed.reason,
            error=parsed.error,
        )
