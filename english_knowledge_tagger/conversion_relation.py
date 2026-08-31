"""A narrow, auditable classifier for conversion versus word-form relations."""

from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any, Mapping

from .candidate_labeling import LabelingServiceConfig, LabelingServiceError, Transport, _http_transport


PROMPT_VERSION = "conversion-relation-v1"
_RELATIONS = frozenset({"conversion", "derivation", "inflection", "lexical_or_other", "insufficient"})
_CONFIDENCES = frozenset({"high", "medium", "low"})


@dataclass(frozen=True)
class ConversionRelationResult:
    relation: str
    confidence: str
    evidence: str
    raw_response: str
    elapsed_ms: float
    prompt_chars: int


def _context(task: Mapping[str, Any]) -> str:
    value = task.get("question_context")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("conversion relation task requires non-empty question_context")
    return value.strip()


def build_conversion_relation_prompt(task: Mapping[str, Any]) -> str:
    """Ask only for the lexical relation, not a taxonomy path or historical label."""
    return f'''你是初中英语构词法审核员。请只根据题干、选项、答案和解析，判断题目实际要求的词形关系。

分类定义：
- conversion：词形完全不变，只改变词性或词义功能，例如 water n.→water v.。
- derivation：添加/去除前后缀、字母增删或其他词形变化构成目标词，例如 direct→director（加 -or）、predict→prediction（加 -ion）。
- inflection：时态、复数、三单、比较级/最高级等语法形态变化，例如 say→says。
- lexical_or_other：普通翻译、默写、词义选择、固定搭配，或题目没有实际要求构词关系。
- insufficient：题面、答案或解析不足以判断。

不要输出知识点标签、不要引用历史标签、不要从其他 taxonomy 中猜 replacement。

只输出 JSON：
{{"relation":"conversion|derivation|inflection|lexical_or_other|insufficient","confidence":"high|medium|low","evidence":"不超过80字，说明源词、目标词及词形关系；信息不足时说明缺什么"}}

题目信息：
{_context(task)}'''


class ConversionRelationClient:
    def __init__(self, config: LabelingServiceConfig, *, transport: Transport | None = None):
        if not config.endpoint:
            raise ValueError("conversion relation endpoint must be non-empty")
        self._config = config
        self._transport = transport or _http_transport

    def classify(self, task: Mapping[str, Any]) -> ConversionRelationResult:
        prompt = build_conversion_relation_prompt(task)
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        started = time.perf_counter_ns()
        response = self._transport(self._config.endpoint, {"model": self._config.model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.0, "max_tokens": self._config.max_tokens}, self._config.timeout_seconds, headers)
        try:
            raw = response["choices"][0]["message"]["content"]
        except (KeyError, TypeError, IndexError) as error:
            raise LabelingServiceError("conversion relation response has no content") from error
        if not isinstance(raw, str):
            raise LabelingServiceError("conversion relation response content must be string")
        try:
            payload = json.loads(raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip())
        except json.JSONDecodeError as error:
            raise LabelingServiceError("conversion relation response is not JSON") from error
        if not isinstance(payload, Mapping) or payload.get("relation") not in _RELATIONS or payload.get("confidence") not in _CONFIDENCES or not isinstance(payload.get("evidence"), str) or not payload["evidence"].strip():
            raise LabelingServiceError("conversion relation response violates schema")
        return ConversionRelationResult(relation=str(payload["relation"]), confidence=str(payload["confidence"]), evidence=payload["evidence"].strip(), raw_response=raw, elapsed_ms=(time.perf_counter_ns()-started)/1_000_000, prompt_chars=len(prompt))
