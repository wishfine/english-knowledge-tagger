"""Auditable OpenAI-compatible client for candidate knowledge-point labeling."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PROMPT_VERSION = "child-kp-ds-v4-v1"
Transport = Callable[[str, dict[str, Any], float, Mapping[str, str]], Mapping[str, Any]]


class LabelingServiceError(RuntimeError):
    """Raised when the labeling service response is unavailable or malformed."""


@dataclass(frozen=True)
class LabelingServiceConfig:
    """Connection settings for the internal OpenAI-compatible labeling endpoint."""

    endpoint: str
    model: str = "ds-v4-flash"
    max_tokens: int = 1024
    temperature: float = 0.0
    timeout_seconds: float = 90.0
    api_key: str | None = None


@dataclass(frozen=True)
class LabelingRequest:
    """One review item sent to the model; this never modifies source labels."""

    review_id: str
    question_context: str
    candidate_definitions: str | None = None


@dataclass(frozen=True)
class CandidateLabelResult:
    """Raw and parsed model output retained for human review and later patching."""

    review_id: str
    model: str
    prompt_version: str
    request_id: str | None
    raw_response: str
    labels: tuple[str, ...]
    unparsed_fragments: tuple[str, ...]
    status: str = "candidate"


def build_child_knowledge_prompt(request: LabelingRequest) -> str:
    """Render the versioned, output-only prompt used for child-question candidate labels."""
    candidate_section = ""
    if request.candidate_definitions:
        candidate_section = (
            "\n候选标签及释义（仅当题目确实满足释义时使用；不应为了凑标签而选择）：\n"
            f"{request.candidate_definitions.strip()}\n"
        )
    return (
        "给定一道英语题目（含题目内容、解析及参考答案），请标注学生解答该题时"
        "必须运用的核心知识点。\n"
        "要求：\n"
        "1. 以题目、答案和解析中的实际考查点为准，排除干扰选项、次要信息和无关内容。\n"
        "2. 标签遵循“新知识树@一级分类@二级分类@...@具体知识点”的层级结构。\n"
        "3. 多个标签使用英文分号分隔；只输出标签，不输出分析、解释、序号或 Markdown。\n"
        "4. 不确定时宁可少标，也不要臆造标签。\n"
        f"{candidate_section}\n"
        "题目上下文：\n"
        f"{request.question_context.strip()}\n\n"
        "本题知识点标签为："
    )


def parse_label_response(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Extract strict hierarchical labels while preserving non-label text for review."""
    labels: list[str] = []
    unparsed: list[str] = []
    known_prefixes = ("新知识树@", "知识点@")
    for line in text.splitlines() or [text]:
        for fragment in re.split(r"[;；]+", line):
            normalized = fragment.strip().strip("`")
            if not normalized:
                continue
            if normalized.startswith(known_prefixes) and normalized.count("@") >= 1:
                if normalized not in labels:
                    labels.append(normalized)
            else:
                unparsed.append(normalized)
    return tuple(labels), tuple(unparsed)


def _http_transport(
    endpoint: str, payload: dict[str, Any], timeout_seconds: float, headers: Mapping[str, str]
) -> Mapping[str, Any]:
    """Call an OpenAI-compatible endpoint using SSE streaming.

    All experiment clients share this transport, so setting ``stream`` here keeps
    their request behavior consistent without requiring each prompt client to
    duplicate SSE parsing.  A normal JSON response is still accepted for
    compatibility with older or proxy deployments that ignore the stream flag.
    """
    request_payload = {**payload, "stream": True}
    request = Request(
        endpoint,
        data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
        headers={**dict(headers), "Accept": "text/event-stream"},
        method="POST",
    )
    request_id: str | None = None
    response_model: str | None = None
    fragments: list[str] = []
    normal_response_lines: list[str] = []
    done = False
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    if fragments or done:
                        raise LabelingServiceError(
                            "labeling service stream contained a non-SSE response line"
                        )
                    normal_response_lines.append(line)
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    done = True
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError as error:
                    raise LabelingServiceError(
                        "labeling service stream contained invalid JSON"
                    ) from error
                if not isinstance(chunk, Mapping):
                    raise LabelingServiceError(
                        "labeling service stream chunk must be a JSON object"
                    )
                if isinstance(chunk.get("id"), str):
                    request_id = chunk["id"]
                if isinstance(chunk.get("model"), str):
                    response_model = chunk["model"]
                choices = chunk.get("choices")
                if not isinstance(choices, list) or not choices:
                    continue
                choice = choices[0]
                if not isinstance(choice, Mapping):
                    continue
                delta = choice.get("delta")
                if isinstance(delta, Mapping):
                    content = delta.get("content")
                    if isinstance(content, str):
                        fragments.append(content)
                    continue
                message = choice.get("message")
                if isinstance(message, Mapping):
                    content = message.get("content")
                    if isinstance(content, str):
                        fragments.append(content)
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise LabelingServiceError(f"labeling service returned HTTP {error.code}: {detail}") from error
    except (URLError, TimeoutError, OSError, UnicodeDecodeError) as error:
        raise LabelingServiceError(f"labeling service request failed: {error}") from error

    if not done and normal_response_lines:
        try:
            normal_response = json.loads("\n".join(normal_response_lines))
        except json.JSONDecodeError as error:
            raise LabelingServiceError("labeling service returned invalid JSON") from error
        if not isinstance(normal_response, Mapping):
            raise LabelingServiceError("labeling service normal response must be a JSON object")
        return normal_response
    if not done:
        raise LabelingServiceError("labeling service stream ended before data: [DONE]")
    return {
        "id": request_id,
        "model": response_model,
        "choices": [{"message": {"content": "".join(fragments)}}],
    }


class CandidateLabelClient:
    """Small dependency-free client; inject a transport in tests or alternative deployments."""

    def __init__(self, config: LabelingServiceConfig, *, transport: Transport | None = None):
        if not config.endpoint:
            raise ValueError("labeling endpoint must be non-empty")
        self._config = config
        self._transport = transport or _http_transport

    def label(self, request: LabelingRequest) -> CandidateLabelResult:
        if not request.review_id.strip():
            raise ValueError("review_id must be non-empty")
        if not request.question_context.strip():
            raise ValueError("question_context must be non-empty")

        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        payload = {
            "model": self._config.model,
            "messages": [{"role": "user", "content": build_child_knowledge_prompt(request)}],
            "max_tokens": self._config.max_tokens,
            "temperature": self._config.temperature,
        }
        response = self._transport(
            self._config.endpoint, payload, self._config.timeout_seconds, headers
        )
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise LabelingServiceError("labeling service response has no choices[0].message.content") from error
        if not isinstance(content, str):
            raise LabelingServiceError("labeling service completion content must be a string")

        labels, unparsed = parse_label_response(content)
        request_id = response.get("id") if isinstance(response.get("id"), str) else None
        response_model = response.get("model") if isinstance(response.get("model"), str) else self._config.model
        return CandidateLabelResult(
            review_id=request.review_id,
            model=response_model,
            prompt_version=PROMPT_VERSION,
            request_id=request_id,
            raw_response=content,
            labels=labels,
            unparsed_fragments=unparsed,
        )
