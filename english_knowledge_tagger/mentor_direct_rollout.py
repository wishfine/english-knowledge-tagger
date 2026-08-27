"""Reproduce mentor-v1 direct label verification for controlled full-label rollouts."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any, Mapping

from .candidate_labeling import LabelingServiceConfig, LabelingServiceError, Transport, _http_transport
from .knowledge_rulebook import KnowledgeRulebook
from .knowledge_taxonomy_migration import KnowledgeTaxonomyMigration
from .sft_labels import parse_sft_output_labels


PROMPT_VERSION = "mentor-direct-v1"
PACKET_SCHEMA_VERSION = "mentor-label-rollout-packet-v1"
_REMOVED_INPUT_PREFIXES = (
    "题型结构为：",
    "题型名称为：",
    "所给图片为题目题干",
)
_TYPE_METADATA = re.compile(r"(?m)^\s*题型(结构|名称)为：([^\r\n]*)")


@dataclass(frozen=True)
class MentorDirectRequest:
    packet_row: Mapping[str, Any]


@dataclass(frozen=True)
class MentorDirectResult:
    review_id: str
    model: str
    prompt_version: str
    request_id: str | None
    raw_response: str
    llm_match: bool
    reason: str
    should_be: str
    prompt_chars: int
    response_chars: int
    model_call_elapsed_ms: float


def load_mentor_label_definitions(path: Path) -> dict[str, Mapping[str, Any]]:
    """Load the exact definition payload used to calibrate mentor-v1 results."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"mentor label definitions are not valid JSON: {path}") from error
    if not isinstance(payload, Mapping):
        raise ValueError("mentor label definitions must be a JSON object")
    definitions: dict[str, Mapping[str, Any]] = {}
    for label, details in payload.items():
        if not isinstance(label, str) or not label.strip() or not isinstance(details, Mapping):
            raise ValueError("mentor label definitions must map non-empty labels to objects")
        definitions[label.strip()] = details
    return definitions


def clean_mentor_v1_input(input_text: str) -> str:
    """Apply exactly the source-line removal and prefix truncation of mentor-v1."""
    cleaned = [
        line
        for line in input_text.split("\n")
        if not line.strip().startswith(_REMOVED_INPUT_PREFIXES)
    ]
    result = "\n".join(cleaned)
    if len(result) > 2000:
        return result[:2000] + "...（截断）"
    return result


def _text(value: object, *, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _route_key(record: Mapping[str, Any]) -> dict[str, str | None]:
    """Preserve source type metadata for audit without treating it as model truth."""
    parsed = {match.group(1): match.group(2).strip() for match in _TYPE_METADATA.finditer(_text(record.get("input")))}
    return {
        "scope": "child" if record.get("is_sub_question") is True else "parent",
        "declared_type_structure": parsed.get("结构") or None,
        "declared_type_name": parsed.get("名称") or None,
    }


def _similar_description(
    definition: Mapping[str, Any], *, label_definitions: Mapping[str, Mapping[str, Any]]
) -> str:
    similar = definition.get("similar_labels")
    if not isinstance(similar, list):
        return ""
    rows: list[str] = []
    for item in similar:
        if not isinstance(item, Mapping):
            continue
        label = _text(item.get("label")).strip()
        if label:
            other = label_definitions.get(label, {})
            rows.append(f"  - {label}\n    释义要点: {_text(other.get('definition'))[:300]}")
    return "【近似/易混淆标签】以下标签与当前标签释义高度相似，请仔细区分：\n" + "\n".join(rows) + "\n" if rows else ""


def _cooccur_description(definition: Mapping[str, Any]) -> str:
    related = definition.get("cooccur_labels")
    if not isinstance(related, list):
        return ""
    rows: list[str] = []
    seen: set[tuple[str, str]] = set()
    for item in related:
        if not isinstance(item, Mapping):
            continue
        label = _text(item.get("label")).strip()
        condition = _text(item.get("condition")).strip()
        key = (label, condition)
        if label and not label.startswith("（") and key not in seen:
            seen.add(key)
            rows.append(f"  - {label}（当{condition}时需同时打此标签）")
    return "【关联标签】打此标签时，以下标签大概率需要同时打：\n" + "\n".join(rows) + "\n" if rows else ""


def _exclusive_description(definition: Mapping[str, Any]) -> str:
    exclusive = definition.get("exclusive_labels")
    if not isinstance(exclusive, list):
        return ""
    rows: list[str] = []
    for item in exclusive:
        if not isinstance(item, Mapping):
            continue
        label = _text(item.get("label")).strip()
        condition = _text(item.get("condition")).strip()
        if label and not label.startswith("None"):
            rows.append(f"  - {label}（当{condition}时应改用此标签）")
        elif not label or label == "None":
            rows.append(f"  - 当{condition}时，不应打此标签")
    return "【互斥标签】以下情况不应打此标签：\n" + "\n".join(rows) + "\n" if rows else ""


def build_mentor_direct_v1_prompt(
    packet_row: Mapping[str, Any], *, label_definitions: Mapping[str, Mapping[str, Any]]
) -> str:
    """Render the calibrating mentor-v1 prompt, including historical ``output_all``."""
    label = _text(packet_row.get("verify_label")).strip()
    definition = label_definitions.get(label)
    if not label or definition is None:
        raise ValueError("packet verify_label must have an exact mentor label definition")
    raw_input = packet_row.get("input")
    if not isinstance(raw_input, str):
        raise ValueError("packet input must be a string")
    output_all = packet_row.get("output_all")
    if not isinstance(output_all, str):
        raise ValueError("packet output_all must be a string")
    return f"""你是一位资深的初中英语教研老师，现在需要验证题目标签标注的准确性。

## 待验证标签
{label}

## 标签释义
{_text(definition.get('definition'), default='（无释义）')}

## 标签常见题干示例
{_text(definition.get('examples'))}

{_similar_description(definition, label_definitions=label_definitions)}{_cooccur_description(definition)}{_exclusive_description(definition)}
## 待验证题目信息
{_text(packet_row.get('instruction'))}
{clean_mentor_v1_input(raw_input)}

## 当前题目打的全部标签
{output_all}

## 验证要求
请判断这道题是否应该被打上「{label}」这个标签。要求题目必须**完全符合**释义内容所描述的考察点。
- 如果标签释义有给出相似的其它标签（近似标签），请仔细对比题目内容，判断题目究竟属于哪一个标签。
- 如果存在互斥标签的触发条件，请判断题目是否触发了互斥条件。
- 如果存在关联标签，请判断题目是否还需要同时打关联标签。

请按以下JSON格式回复（不要输出其他内容）：
{{"reason": "简要说明判断理由", "match": true/false, "should_be": "如果当前标签不对，应该打的标签是什么；如果正确则填'正确'"}}
"""


def _strip_fence(text: str) -> str:
    normalized = text.strip()
    if normalized.startswith("```"):
        normalized = normalized.split("\n", 1)[1] if "\n" in normalized else normalized[3:]
    if normalized.endswith("```"):
        normalized = normalized[:-3]
    return normalized.strip()


def _parse_mentor_direct_response(text: str) -> tuple[bool, str, str]:
    normalized = _strip_fence(text)
    try:
        payload = json.loads(normalized)
    except json.JSONDecodeError:
        matched = re.search(r"\{[^}]+\}", normalized, re.DOTALL)
        if matched is None:
            raise LabelingServiceError("mentor direct response is not valid JSON")
        try:
            payload = json.loads(matched.group())
        except json.JSONDecodeError as error:
            raise LabelingServiceError("mentor direct response is not valid JSON") from error
    if not isinstance(payload, Mapping) or not isinstance(payload.get("match"), bool):
        raise LabelingServiceError("mentor direct response must contain boolean match")
    reason = payload.get("reason")
    should_be = payload.get("should_be")
    if not isinstance(reason, str) or not isinstance(should_be, str):
        raise LabelingServiceError("mentor direct response reason and should_be must be strings")
    return payload["match"], reason, should_be


class MentorDirectClient:
    """Dependency-free, retrying client for the already calibrated mentor-v1 prompt."""

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
            raise ValueError("mentor direct endpoint must be non-empty")
        if max_retries <= 0:
            raise ValueError("max_retries must be positive")
        if retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds must be non-negative")
        self._config = config
        self._label_definitions = label_definitions
        self._transport = transport or _http_transport
        self._max_retries = max_retries
        self._retry_delay_seconds = retry_delay_seconds

    def verify(self, request: MentorDirectRequest) -> MentorDirectResult:
        review_id = _text(request.packet_row.get("review_id")).strip()
        if not review_id:
            raise ValueError("mentor direct packet review_id must be non-empty")
        prompt = build_mentor_direct_v1_prompt(
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
            "temperature": 0.1,
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
            raise last_error or LabelingServiceError("mentor direct request failed without an error")
        try:
            raw_response = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise LabelingServiceError("mentor direct response has no choices[0].message.content") from error
        if not isinstance(raw_response, str):
            raise LabelingServiceError("mentor direct completion content must be a string")
        llm_match, reason, should_be = _parse_mentor_direct_response(raw_response)
        return MentorDirectResult(
            review_id=review_id,
            model=response.get("model") if isinstance(response.get("model"), str) else self._config.model,
            prompt_version=PROMPT_VERSION,
            request_id=response.get("id") if isinstance(response.get("id"), str) else None,
            raw_response=raw_response,
            llm_match=llm_match,
            reason=reason,
            should_be=should_be,
            prompt_chars=len(prompt),
            response_chars=len(raw_response),
            model_call_elapsed_ms=(time.perf_counter_ns() - call_started_ns) / 1_000_000,
        )


def _canonical_label(
    verify_label: object, *, rulebook: KnowledgeRulebook, migration: KnowledgeTaxonomyMigration
) -> str:
    label = _text(verify_label).strip()
    if not label.startswith("知识点@"):
        raise ValueError("mentor direct verify_label must be a rendered knowledge label")
    legacy_path = "知识点->" + label.removeprefix("知识点@").replace("@", "->")
    canonical = migration.canonicalize(legacy_path).canonical_path
    taxonomy = rulebook.records.get(canonical)
    if taxonomy is None or taxonomy.status != "active":
        raise ValueError("mentor direct verify_label must map to an active teacher terminal label")
    return canonical


def mentor_result_to_evidence(
    packet_row: Mapping[str, Any],
    *,
    result: MentorDirectResult,
    rulebook: KnowledgeRulebook,
    migration: KnowledgeTaxonomyMigration,
) -> dict[str, Any]:
    """Convert one prompt-equivalent result to the calibration gate's stable contract."""
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
        "prompt_version": result.prompt_version,
        "request_id": result.request_id,
        "reason": result.reason,
        "should_be": result.should_be,
        "raw_response": result.raw_response,
        "model_call_elapsed_ms": result.model_call_elapsed_ms,
        "prompt_chars": result.prompt_chars,
        "response_chars": result.response_chars,
        "source_path": packet_row.get("source_path"),
        "label_definitions_path": packet_row.get("label_definitions_path"),
        "label_definitions_sha256": packet_row.get("label_definitions_sha256"),
        "output_all": packet_row.get("output_all"),
        "input_sha256": hashlib.sha256(_text(packet_row.get("input")).encode("utf-8")).hexdigest(),
    }


def mentor_error_to_evidence(
    packet_row: Mapping[str, Any],
    *,
    error: Exception,
    rulebook: KnowledgeRulebook,
    migration: KnowledgeTaxonomyMigration,
    model: str,
) -> dict[str, Any]:
    """Keep a model or parser failure as explicit holdable evidence."""
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
        "prompt_version": PROMPT_VERSION,
        "error": str(error),
        "source_path": packet_row.get("source_path"),
        "label_definitions_path": packet_row.get("label_definitions_path"),
        "label_definitions_sha256": packet_row.get("label_definitions_sha256"),
        "output_all": packet_row.get("output_all"),
        "input_sha256": hashlib.sha256(_text(packet_row.get("input")).encode("utf-8")).hexdigest(),
    }


def build_mentor_label_rollout_packet(
    source_path: Path,
    *,
    verify_label: str,
    label_definitions_path: Path,
    output_path: Path,
) -> dict[str, object]:
    """Stream all source records carrying one exact historical knowledge label."""
    target = verify_label.strip()
    if not target.startswith("知识点@"):
        raise ValueError("verify_label must be an exact rendered knowledge label beginning with 知识点@")
    definitions = load_mentor_label_definitions(label_definitions_path)
    if target not in definitions:
        raise ValueError("verify_label is not present in mentor label definitions")
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite existing rollout packet: {output_path}")
    label_definitions_sha256 = hashlib.sha256(label_definitions_path.read_bytes()).hexdigest()
    source_hasher = hashlib.sha256()
    selected_by_scope: Counter[str] = Counter()
    selected = 0
    source_rows = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with source_path.open("rb") as source, output_path.open("x", encoding="utf-8") as output:
        for source_line, raw_line in enumerate(source, 1):
            source_hasher.update(raw_line)
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError as error:
                raise ValueError(f"source line {source_line}: invalid JSON") from error
            if not isinstance(record, Mapping):
                raise ValueError(f"source line {source_line}: JSONL row must be an object")
            source_rows += 1
            parsed = parse_sft_output_labels(record.get("output"))
            if parsed is None or target not in parsed[0]:
                continue
            if not isinstance(record.get("output"), str):
                raise ValueError(f"source line {source_line}: output must be a rendered label string")
            scope = "child" if record.get("is_sub_question") is True else "parent"
            packet_row = {
                "schema_version": PACKET_SCHEMA_VERSION,
                "review_id": f"{PROMPT_VERSION}:{source_line}:{target}",
                "source_line": source_line,
                "question_id": record.get("question_id"),
                "parent_id": record.get("parent_id"),
                "is_sub_question": record.get("is_sub_question"),
                "scope": scope,
                "route_key": _route_key(record),
                "verify_label": target,
                "instruction": record.get("instruction"),
                "input": record.get("input"),
                "output_all": record.get("output"),
                "source_path": str(source_path),
                "label_definitions_path": str(label_definitions_path),
                "label_definitions_sha256": label_definitions_sha256,
            }
            output.write(json.dumps(packet_row, ensure_ascii=False, sort_keys=True) + "\n")
            selected += 1
            selected_by_scope[scope] += 1
    return {
        "schema_version": "mentor-label-rollout-packet-report-v1",
        "prompt_version": PROMPT_VERSION,
        "source_path": str(source_path),
        "source_sha256": source_hasher.hexdigest(),
        "source_records": source_rows,
        "verify_label": target,
        "label_definitions_path": str(label_definitions_path),
        "label_definitions_sha256": label_definitions_sha256,
        "output_path": str(output_path),
        "selected_records": selected,
        "selected_by_scope": dict(sorted(selected_by_scope.items())),
    }
