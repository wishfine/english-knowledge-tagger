"""Stable type-label sampling and streamed DS question-type classification."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import heapq
import json
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .sft_labels import parse_sft_output_labels


PROMPT_VERSION = "question-type-classifier-v1"
SAMPLE_SCHEMA_VERSION = "question-type-reclassification-sample-v1"
RESULT_SCHEMA_VERSION = "question-type-reclassification-result-v1"
_REMOVED_INPUT_PREFIXES = ("题型结构为：", "题型名称为：")


class QuestionTypeServiceError(RuntimeError):
    """Raised when a streamed classifier response is unavailable or malformed."""


@dataclass(frozen=True)
class QuestionTypeServiceConfig:
    endpoint: str
    model: str = "DeepSeek-V4-Flash"
    max_tokens: int = 128
    temperature: float = 0.0
    timeout_seconds: float = 60.0
    api_key: str | None = None


@dataclass(frozen=True)
class StreamCompletion:
    request_id: str | None
    model: str | None
    content: str


@dataclass(frozen=True)
class QuestionTypeResult:
    predicted_type_label: str
    raw_response: str
    request_id: str | None
    model: str


StreamTransport = Callable[
    [str, dict[str, Any], float, Mapping[str, str]], StreamCompletion
]


def clean_question_input(input_text: str) -> str:
    """Remove declared type metadata without changing the remaining question text."""
    return "\n".join(
        line
        for line in input_text.split("\n")
        if not line.strip().startswith(_REMOVED_INPUT_PREFIXES)
    ).strip()


def build_question_type_prompt(base_prompt: str, input_text: str) -> str:
    """Combine the supplied classifier prompt with sanitized source ``input`` only."""
    prompt = base_prompt.strip()
    if not prompt:
        raise ValueError("question-type classifier prompt must be non-empty")
    cleaned = clean_question_input(input_text)
    if not cleaned:
        raise ValueError("question input is empty after removing declared type metadata")
    return f"{prompt}\n\n--------------------------------\n待判定题目信息\n--------------------------------\n\n{cleaned}"


def parse_question_type_response(text: str) -> str:
    """Parse the classifier's required single ``题型@...`` response."""
    normalized = text.strip()
    if normalized.startswith("```") and normalized.endswith("```"):
        lines = normalized.splitlines()
        if len(lines) >= 3:
            normalized = "\n".join(lines[1:-1]).strip()
    if (
        not normalized.startswith("题型@")
        or "\n" in normalized
        or ";" in normalized
        or "；" in normalized
    ):
        raise QuestionTypeServiceError(
            "classifier response must contain exactly one hierarchical 题型@ label"
        )
    return normalized


def _stream_http_transport(
    endpoint: str,
    payload: dict[str, Any],
    timeout_seconds: float,
    headers: Mapping[str, str],
) -> StreamCompletion:
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={**dict(headers), "Accept": "text/event-stream"},
        method="POST",
    )
    request_id: str | None = None
    response_model: str | None = None
    fragments: list[str] = []
    done = False
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    raise QuestionTypeServiceError(
                        "classifier stream contained a non-SSE response line"
                    )
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    done = True
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError as error:
                    raise QuestionTypeServiceError(
                        "classifier stream contained invalid JSON"
                    ) from error
                if not isinstance(chunk, Mapping):
                    raise QuestionTypeServiceError(
                        "classifier stream chunk must be a JSON object"
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
                if not isinstance(delta, Mapping):
                    continue
                content = delta.get("content")
                if isinstance(content, str):
                    fragments.append(content)
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise QuestionTypeServiceError(
            f"classifier returned HTTP {error.code}: {detail}"
        ) from error
    except (URLError, TimeoutError, OSError) as error:
        raise QuestionTypeServiceError(f"classifier request failed: {error}") from error
    if not done:
        raise QuestionTypeServiceError("classifier stream ended before data: [DONE]")
    return StreamCompletion(
        request_id=request_id,
        model=response_model,
        content="".join(fragments),
    )


class QuestionTypeClient:
    """Dependency-free client for one OpenAI-compatible streaming endpoint."""

    def __init__(
        self,
        config: QuestionTypeServiceConfig,
        *,
        base_prompt: str,
        transport: StreamTransport | None = None,
        max_retries: int = 3,
    ):
        if not config.endpoint.strip():
            raise ValueError("question-type endpoint must be non-empty")
        if max_retries <= 0:
            raise ValueError("max_retries must be positive")
        self._config = config
        self._base_prompt = base_prompt
        self._transport = transport or _stream_http_transport
        self._max_retries = max_retries

    def classify(self, input_text: str) -> QuestionTypeResult:
        prompt = build_question_type_prompt(self._base_prompt, input_text)
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        payload = {
            "model": self._config.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
            "stream": True,
        }
        last_error: QuestionTypeServiceError | None = None
        for _ in range(self._max_retries):
            try:
                completion = self._transport(
                    self._config.endpoint,
                    payload,
                    self._config.timeout_seconds,
                    headers,
                )
                predicted = parse_question_type_response(completion.content)
                return QuestionTypeResult(
                    predicted_type_label=predicted,
                    raw_response=completion.content,
                    request_id=completion.request_id,
                    model=completion.model or self._config.model,
                )
            except QuestionTypeServiceError as error:
                last_error = error
        raise last_error or QuestionTypeServiceError(
            "classifier request failed without an error"
        )


def _identifier(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (str, int)):
        normalized = str(value).strip()
        return normalized or None
    return None


def _type_labels(record: Mapping[str, Any]) -> tuple[str, ...]:
    parsed = parse_sft_output_labels(record.get("output"))
    if parsed is None:
        return ()
    return tuple(sorted(parsed[1]))


def _sample_score(seed: int, label: str, identifier: str) -> int:
    payload = f"{seed}\0{label}\0{identifier}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest(), "big")


def build_type_reclassification_sample(
    input_path: Path,
    *,
    output_path: Path,
    per_type: int = 1000,
    seed: int = 20260828,
) -> dict[str, Any]:
    """Select up to ``per_type`` rows for every exact rendered type label.

    Sampling is stable and bounded in memory. Records selected by more than one
    label are materialized once and retain all sampled strata in the packet.
    """
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite existing sample: {output_path}")
    if per_type <= 0:
        raise ValueError("per_type must be positive")

    label_counts: Counter[str] = Counter()
    heaps: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    processed: Counter[str] = Counter()
    with input_path.open("r", encoding="utf-8") as source:
        for source_line, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                processed["invalid_json_lines"] += 1
                continue
            if not isinstance(record, Mapping):
                processed["non_object_records"] += 1
                continue
            processed["valid_records"] += 1
            labels = _type_labels(record)
            if not labels:
                processed["records_without_type_labels"] += 1
                continue
            question_id = _identifier(record.get("question_id"))
            stable_identifier = question_id or f"source-line:{source_line}"
            for label in labels:
                label_counts[label] += 1
                score = _sample_score(seed, label, stable_identifier)
                entry = (-score, -source_line, source_line)
                heap = heaps[label]
                if len(heap) < per_type:
                    heapq.heappush(heap, entry)
                elif entry > heap[0]:
                    heapq.heapreplace(heap, entry)

    selected_by_line: dict[int, list[str]] = defaultdict(list)
    for label, heap in heaps.items():
        for _, _, source_line in heap:
            selected_by_line[source_line].append(label)
    for labels in selected_by_line.values():
        labels.sort()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    emitted = 0
    with input_path.open("r", encoding="utf-8") as source, output_path.open(
        "x", encoding="utf-8"
    ) as output:
        for source_line, line in enumerate(source, 1):
            sampled_labels = selected_by_line.get(source_line)
            if sampled_labels is None:
                continue
            record = json.loads(line)
            if not isinstance(record, Mapping):
                raise ValueError(
                    f"source line {source_line} changed between sample passes"
                )
            question_id = _identifier(record.get("question_id"))
            packet_row = {
                "schema_version": SAMPLE_SCHEMA_VERSION,
                "review_id": f"{PROMPT_VERSION}:{source_line}:{question_id or 'unknown'}",
                "source_path": str(input_path),
                "source_line": source_line,
                "question_id": question_id,
                "parent_id": _identifier(record.get("parent_id")),
                "is_sub_question": record.get("is_sub_question"),
                "sampled_type_labels": sampled_labels,
                "current_type_labels": list(_type_labels(record)),
                "instruction": record.get("instruction"),
                "input": record.get("input"),
                "output": record.get("output"),
                "contain_audio": record.get("contain_audio"),
                "whole_image": record.get("whole_image"),
            }
            output.write(json.dumps(packet_row, ensure_ascii=False, sort_keys=True) + "\n")
            emitted += 1

    return {
        "schema_version": "question-type-reclassification-sample-report-v1",
        "input_path": str(input_path),
        "output_path": str(output_path),
        "per_type": per_type,
        "seed": seed,
        "processed_records": dict(processed),
        "type_category_count": len(label_counts),
        "type_category_source_counts": dict(sorted(label_counts.items())),
        "type_category_sample_counts": {
            label: len(heaps[label]) for label in sorted(heaps)
        },
        "sample_memberships": sum(len(heap) for heap in heaps.values()),
        "unique_sample_records": emitted,
    }
