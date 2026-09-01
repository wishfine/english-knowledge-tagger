"""A conservative target-label gate for the conversion-law cleanup loop."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
from typing import Any, Mapping

from .candidate_labeling import LabelingServiceConfig, LabelingServiceError, Transport, _http_transport


PROMPT_VERSION = "conversion-gate-v1"
DEFAULT_TARGET_DEFINITION = (
    "- 转化法：同一个英文词的拼写完全不变，只因为词性或句法功能改变而使用，并且这种关系是本题得到答案所必需的。\n"
    "- 例如：plant(v.) → plant(n.)、water(n.) → water(v.)、book(n.) → book(v.)。"
)
_DECISIONS = frozenset({"target_conversion", "non_target", "insufficient"})
_CONFIDENCES = frozenset({"high", "medium", "low"})


@dataclass(frozen=True)
class ConversionGateResult:
    """A target-label decision with explicit form and dependency evidence."""

    decision: str
    confidence: str
    source_forms: tuple[str, ...]
    target_forms: tuple[str, ...]
    form_unchanged: bool | None
    pos_or_function_changed: bool | None
    answer_depends_on_relation: bool | None
    evidence: str
    raw_response: str
    elapsed_ms: float
    prompt_chars: int


def _context(task: Mapping[str, Any]) -> str:
    value = task.get("question_context")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("conversion gate task requires non-empty question_context")
    return value.strip()


def build_conversion_gate_prompt(
    task: Mapping[str, Any], *, target_definition: str | None = None
) -> str:
    """Render a label-blind, three-way gate prompt.

    The model decides only whether the *target* conversion label applies.  It
    never chooses a replacement taxonomy label, so ``non_target`` cannot be
    turned into an arbitrary tree candidate by a required-label policy.
    """

    definition = (target_definition or DEFAULT_TARGET_DEFINITION).strip()
    if not definition:
        raise ValueError("conversion gate target_definition must be non-empty")
    return f'''你是初中英语构词法审核员。现在只判断“转化法”这个目标知识点是否适用于题目，不要给出任何替换标签。

目标知识点的严格定义：
{definition}

明确排除：
- 添加或删除前缀、后缀、字母，或其它拼写变化：属于派生法，不是转化法。
- 时态、复数、第三人称单数、比较级/最高级等形态变化：属于屈折或语法，不是转化法。
- 只是列出同一个词的多个词性/词义、普通翻译、默写、固定搭配，若题目答案不依赖实际词性转化，也不是转化法。
- 一题同时有多个关系时，只有确实存在“同形词因词性/功能改变而直接参与答案”才可判为目标；无法从题面确认时判 insufficient。

判定顺序：
1. 找出题目实际要求填写或选择的源词和目标词；不要把解析中随手提到的词当成答案关系。
2. 判断源词和目标词拼写是否完全相同。
3. 判断是否发生词性或句法功能改变。
4. 判断答案是否必须依赖这层同形转化。

只输出一个 JSON 对象，不要输出 Markdown、知识点路径、历史标签或额外解释：
{{"decision":"target_conversion|non_target|insufficient","confidence":"high|medium|low","source_forms":["源词"],"target_forms":["目标词"],"form_unchanged":true/false/null,"pos_or_function_changed":true/false/null,"answer_depends_on_relation":true/false/null,"evidence":"不超过100字，说明实际源词、目标词和判定依据；信息不足时说明缺失内容"}}

题目信息：
{_context(task)}'''


def _strip_fence(text: str) -> str:
    normalized = text.strip()
    if normalized.startswith("```"):
        normalized = normalized.split("\n", 1)[1] if "\n" in normalized else normalized[3:]
    if normalized.endswith("```"):
        normalized = normalized[:-3]
    return normalized.strip()


def _string_list(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise LabelingServiceError(f"conversion gate response {field} must be a list of non-empty strings")
    return tuple(item.strip() for item in value)


def _optional_bool(value: object, *, field: str) -> bool | None:
    if value is not None and not isinstance(value, bool):
        raise LabelingServiceError(f"conversion gate response {field} must be boolean or null")
    return value


def _form_key(value: str) -> str:
    """Compare lexical forms while ignoring POS annotations and punctuation."""
    without_pos = re.sub(r"\([^)]*\)", "", value)
    return re.sub(r"[^a-z0-9]+", "", without_pos.lower())


def _parse_response(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(_strip_fence(raw))
    except json.JSONDecodeError as error:
        raise LabelingServiceError("conversion gate response is not JSON") from error
    if not isinstance(payload, Mapping):
        raise LabelingServiceError("conversion gate response must be a JSON object")
    decision = payload.get("decision")
    confidence = payload.get("confidence")
    evidence = payload.get("evidence")
    if decision not in _DECISIONS:
        raise LabelingServiceError("conversion gate response has unsupported decision")
    if confidence not in _CONFIDENCES:
        raise LabelingServiceError("conversion gate response has unsupported confidence")
    if not isinstance(evidence, str) or not evidence.strip():
        raise LabelingServiceError("conversion gate response evidence must be non-empty")
    source_forms = _string_list(payload.get("source_forms"), field="source_forms")
    target_forms = _string_list(payload.get("target_forms"), field="target_forms")
    form_unchanged = _optional_bool(payload.get("form_unchanged"), field="form_unchanged")
    pos_changed = _optional_bool(
        payload.get("pos_or_function_changed"), field="pos_or_function_changed"
    )
    depends = _optional_bool(
        payload.get("answer_depends_on_relation"), field="answer_depends_on_relation"
    )
    if decision == "insufficient" and not any(value is None for value in (form_unchanged, pos_changed, depends)):
        raise LabelingServiceError("insufficient requires at least one unknown structural evidence field")
    if decision == "target_conversion" and not (form_unchanged and pos_changed and depends):
        raise LabelingServiceError("target_conversion requires all three structural evidence fields to be true")
    if decision == "target_conversion":
        source_keys = sorted(key for key in (_form_key(item) for item in source_forms) if key)
        target_keys = sorted(key for key in (_form_key(item) for item in target_forms) if key)
        if not source_keys or source_keys != target_keys:
            decision = "insufficient"
            confidence = "low"
            form_unchanged = False
            evidence = "结构字段不一致，无法确认源词和目标词词形完全相同。"
    return {
        "decision": str(decision),
        "confidence": str(confidence),
        "source_forms": source_forms,
        "target_forms": target_forms,
        "form_unchanged": form_unchanged,
        "pos_or_function_changed": pos_changed,
        "answer_depends_on_relation": depends,
        "evidence": evidence.strip(),
    }


class ConversionGateClient:
    """Dependency-free OpenAI-compatible client for the conversion target gate."""

    def __init__(
        self,
        config: LabelingServiceConfig,
        *,
        target_definition: str | None = None,
        prompt_version: str = PROMPT_VERSION,
        transport: Transport | None = None,
    ):
        if not config.endpoint:
            raise ValueError("conversion gate endpoint must be non-empty")
        if target_definition is not None and not target_definition.strip():
            raise ValueError("conversion gate target_definition must be non-empty")
        if not prompt_version.strip():
            raise ValueError("conversion gate prompt_version must be non-empty")
        self._config = config
        self._target_definition = target_definition.strip() if target_definition is not None else None
        self._prompt_version = prompt_version.strip()
        self._transport = transport or _http_transport

    @property
    def prompt_version(self) -> str:
        return self._prompt_version

    def classify(self, task: Mapping[str, Any]) -> ConversionGateResult:
        prompt = build_conversion_gate_prompt(task, target_definition=self._target_definition)
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
            },
            self._config.timeout_seconds,
            headers,
        )
        try:
            raw = response["choices"][0]["message"]["content"]
        except (KeyError, TypeError, IndexError) as error:
            raise LabelingServiceError("conversion gate response has no content") from error
        if not isinstance(raw, str):
            raise LabelingServiceError("conversion gate response content must be string")
        payload = _parse_response(raw)
        return ConversionGateResult(
            **payload,
            raw_response=raw,
            elapsed_ms=(time.perf_counter_ns() - started) / 1_000_000,
            prompt_chars=len(prompt),
        )
