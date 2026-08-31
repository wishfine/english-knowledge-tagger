"""A label-blind gate deciding whether a question is one atomic knowledge task."""

from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any, Mapping

from .candidate_labeling import LabelingServiceConfig, LabelingServiceError, Transport, _http_transport


PROMPT_VERSION = "task-shape-gate-v1"
_SHAPES = frozenset({"atomic_knowledge", "lexical_or_other", "mixed_or_multiple_relations", "insufficient"})


@dataclass(frozen=True)
class TaskShapeGateResult:
    task_shape: str
    evidence: str
    raw_response: str
    elapsed_ms: float
    prompt_chars: int


def _context(task: Mapping[str, Any]) -> str:
    context = task.get("question_context")
    if not isinstance(context, str) or not context.strip():
        raise ValueError("task shape gate requires non-empty question_context")
    return context.strip()


def build_task_shape_prompt(task: Mapping[str, Any]) -> str:
    """Render a first-pass gate that cannot see any previous label or verdict."""
    return f'''你是英语题目任务形态审核员。请只依据题干、选项、答案、解析判断本题能否作为一个“单一、具体”的知识点定位任务。

分类：
- atomic_knowledge：题目有足够信息，且作答主要依赖一个可定位的知识点；即使是构词题，也必须明确要求一个具体源词到目标词的关系。
- lexical_or_other：普通翻译、单词/词义默写、固定搭配、仅展示双词性释义，或题目不要求实际完成某个知识点转换。
- mixed_or_multiple_relations：同题多空或多任务，核心同时涉及多个独立关系/知识点，不能诚实压成一个标签。
- insufficient：缺少具体题干、选项、答案或解析，无法可靠判断。

先判断“题目实际要求学生做什么”，不能因为题面出现双词性单词、词缀或某个语法形式就假设该关系是本题核心。
只输出 JSON：
{{"task_shape":"atomic_knowledge|lexical_or_other|mixed_or_multiple_relations|insufficient","evidence":"不超过80字，说明判断依据"}}

题目信息：
{_context(task)}'''


class TaskShapeGateClient:
    def __init__(self, config: LabelingServiceConfig, *, transport: Transport | None = None):
        if not config.endpoint:
            raise ValueError("task shape gate endpoint must be non-empty")
        self._config = config
        self._transport = transport or _http_transport

    def classify(self, task: Mapping[str, Any]) -> TaskShapeGateResult:
        prompt = build_task_shape_prompt(task)
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        started = time.perf_counter_ns()
        response = self._transport(self._config.endpoint, {"model": self._config.model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.0, "max_tokens": self._config.max_tokens}, self._config.timeout_seconds, headers)
        try:
            raw = response["choices"][0]["message"]["content"]
        except (KeyError, TypeError, IndexError) as error:
            raise LabelingServiceError("task shape response has no content") from error
        if not isinstance(raw, str):
            raise LabelingServiceError("task shape response content must be string")
        try:
            payload = json.loads(raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip())
        except json.JSONDecodeError as error:
            raise LabelingServiceError("task shape response is not JSON") from error
        if not isinstance(payload, Mapping) or payload.get("task_shape") not in _SHAPES or not isinstance(payload.get("evidence"), str) or not payload["evidence"].strip():
            raise LabelingServiceError("task shape response violates schema")
        return TaskShapeGateResult(task_shape=str(payload["task_shape"]), evidence=payload["evidence"].strip(), raw_response=raw, elapsed_ms=(time.perf_counter_ns()-started)/1_000_000, prompt_chars=len(prompt))
