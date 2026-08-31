"""DS-V4 client for one constrained knowledge-taxonomy tree decision."""

from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Mapping

from .candidate_labeling import (
    LabelingServiceConfig,
    LabelingServiceError,
    Transport,
    _http_transport,
)
from .knowledge_taxonomy_tree import NO_MATCH, KnowledgeTaxonomyTree
from .knowledge_tree_search import TreeChoice, TreeChoiceRequest


PROMPT_VERSION = "knowledge-tree-choice-ds-v4-v1"
_COVERAGE = frozenset({"covered", "insufficient", "unknown"})
TERMINAL_DEFINITION_MODES = frozenset({"compressed", "none"})
CONVERSION_PATH = "知识点->词汇->构词法->转化法"
CONVERSION_NEGATIVE_CONSTRAINT = (
    "转化法额外约束：词缀、拼写增删、-ing/-ed、复数、三单、比较级等词形变化不是转化法；"
    "只有词形不变而词性改变才可选转化法。\n"
)


@dataclass(frozen=True)
class ParsedTreeChoice:
    status: str
    choice: str | None
    candidate_coverage: str | None
    evidence: str | None
    error: str | None


def _unparsed(error: str) -> ParsedTreeChoice:
    return ParsedTreeChoice(
        status="unparsed",
        choice=None,
        candidate_coverage=None,
        evidence=None,
        error=error,
    )


def _strip_code_fence(text: str) -> str:
    normalized = text.strip()
    if normalized.startswith("```") and normalized.endswith("```"):
        lines = normalized.splitlines()
        return "\n".join(lines[1:-1]).strip()
    return normalized


def parse_tree_choice_response(
    text: str, *, allowed_choices: frozenset[str]
) -> ParsedTreeChoice:
    """Accept exactly one offered child or the reserved no-match control token."""
    try:
        payload = json.loads(_strip_code_fence(text))
    except json.JSONDecodeError as error:
        return _unparsed(f"response is not valid JSON: {error.msg}")
    if not isinstance(payload, Mapping):
        return _unparsed("response JSON must be an object")
    choice = payload.get("choice")
    coverage = payload.get("candidate_coverage")
    evidence = payload.get("evidence")
    if not isinstance(choice, str) or not choice:
        return _unparsed("choice must be a non-empty string")
    if choice not in allowed_choices:
        return _unparsed("choice is outside the supplied current tree step")
    if coverage not in _COVERAGE:
        return _unparsed("candidate_coverage must be covered, insufficient, or unknown")
    if not isinstance(evidence, str):
        return _unparsed("evidence must be a string")
    if choice != NO_MATCH and coverage != "covered":
        return _unparsed("a concrete child choice requires covered candidate coverage")
    return ParsedTreeChoice(
        status="candidate",
        choice=choice,
        candidate_coverage=coverage,
        evidence=evidence,
        error=None,
    )


def build_tree_choice_prompt(
    request: TreeChoiceRequest,
    tree: KnowledgeTaxonomyTree,
    *,
    terminal_definition_mode: str = "compressed",
    conversion_negative_constraint: bool = False,
    conversion_structured_guard: bool = False,
) -> str:
    """Render only the current siblings and a separate no-match control option."""
    if terminal_definition_mode not in TERMINAL_DEFINITION_MODES:
        raise ValueError(f"unsupported terminal_definition_mode: {terminal_definition_mode}")
    candidates: list[str] = []
    for path in request.candidate_paths:
        definition = tree.definition(path) if terminal_definition_mode == "compressed" else None
        if definition:
            candidates.append(f"- {path}\n  压缩释义：{definition}")
        else:
            candidates.append(f"- {path}")
    candidates.append(f"- {NO_MATCH}\n  含义：当前节点的所有候选均不是本题核心考点。")
    constraint = (
        CONVERSION_NEGATIVE_CONSTRAINT
        if conversion_negative_constraint and CONVERSION_PATH in request.candidate_paths
        else ""
    )
    structured_guard = (
        "在选择前先在内部完成三个检查（不要把检查过程输出）："
        "(1)题目是否实际要求完成一个具体转换；"
        "(2)源词和目标词的词形是否完全不变；"
        "(3)题目是否同时包含多个独立关系或信息不足。"
        "只有‘实际要求完成 + 词形完全不变’时才能选择转化法；"
        "加前后缀、字母增删、时态、复数、三单、比较级、动名词不是转化法。"
        "仅列出同一单词的名词义/动词义也不是转化法。"
        "若关系混合或证据不足，优先选择 __NO_MATCH__，不要为了得到末级标签而猜测。\n"
        if conversion_structured_guard
        else ""
    )
    return (
        "你正在为一道英语小题定位一个知识点候选的下一层 taxonomy 节点。"
        "只能依据题干、选项、答案和解析判断，不得臆造未给出的节点。\n"
        "本轮只在当前层选择一个节点；若当前层均不匹配，选择 __NO_MATCH__。"
        "__NO_MATCH__ 是控制项，不是知识点标签。\n"
        "candidate_coverage：选择具体节点时必须是 covered；选择 __NO_MATCH__ 时，"
        "若当前候选不足以覆盖可能考点填 insufficient，题面不足填 unknown，否则填 covered。\n"
        "只输出一个 JSON 对象，不要 Markdown 或额外字段：\n"
        '{"choice":"当前层给出的完整路径或__NO_MATCH__",'
        '"candidate_coverage":"covered|insufficient|unknown",'
        '"evidence":"题干、答案或解析中的短证据"}\n\n'
        f"当前节点：{request.parent_path}\n"
        f"{constraint}"
        f"{structured_guard}"
        "当前层候选：\n"
        f"{'\n'.join(candidates)}\n\n"
        "题目信息：\n"
        f"{request.question_context.strip()}"
    )


class KnowledgeTreeChoiceClient:
    """Dependency-free DS-V4 selector for one tree step."""

    def __init__(
        self,
        config: LabelingServiceConfig,
        tree: KnowledgeTaxonomyTree,
        *,
        terminal_definition_mode: str = "compressed",
        conversion_negative_constraint: bool = False,
        conversion_structured_guard: bool = False,
        transport: Transport | None = None,
    ):
        if not config.endpoint:
            raise ValueError("tree choice endpoint must be non-empty")
        if terminal_definition_mode not in TERMINAL_DEFINITION_MODES:
            raise ValueError(f"unsupported terminal_definition_mode: {terminal_definition_mode}")
        self._config = config
        self._tree = tree
        self._terminal_definition_mode = terminal_definition_mode
        self._conversion_negative_constraint = conversion_negative_constraint
        self._conversion_structured_guard = conversion_structured_guard
        self._transport = transport or _http_transport

    def choose(self, request: TreeChoiceRequest) -> TreeChoice:
        if not request.question_context.strip():
            raise ValueError("tree choice question_context must be non-empty")
        if not request.candidate_paths:
            raise ValueError("tree choice candidate_paths must be non-empty")
        if len(set(request.candidate_paths)) != len(request.candidate_paths):
            raise ValueError("tree choice candidate_paths must be unique")
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        prompt = build_tree_choice_prompt(
            request,
            self._tree,
            terminal_definition_mode=self._terminal_definition_mode,
            conversion_negative_constraint=self._conversion_negative_constraint,
            conversion_structured_guard=self._conversion_structured_guard,
        )
        payload = {
            "model": self._config.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self._config.max_tokens,
            "temperature": 0.0,
        }
        call_started_ns = time.perf_counter_ns()
        response = self._transport(
            self._config.endpoint, payload, self._config.timeout_seconds, headers
        )
        try:
            raw_response = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise LabelingServiceError(
                "tree choice service response has no choices[0].message.content"
            ) from error
        if not isinstance(raw_response, str):
            raise LabelingServiceError("tree choice completion content must be a string")
        parsed = parse_tree_choice_response(
            raw_response, allowed_choices=frozenset((*request.candidate_paths, NO_MATCH))
        )
        model_call_elapsed_ms = (time.perf_counter_ns() - call_started_ns) / 1_000_000
        return TreeChoice(
            choice=parsed.choice or "",
            candidate_coverage=parsed.candidate_coverage or "unknown",
            evidence=parsed.evidence or "",
            raw_response=raw_response,
            parse_error=parsed.error,
            model_call_elapsed_ms=model_call_elapsed_ms,
            prompt_chars=len(prompt),
            response_chars=len(raw_response),
        )
