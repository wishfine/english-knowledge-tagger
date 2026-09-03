"""Deterministic completeness checks for final label discriminator packets."""

from __future__ import annotations

import re
from typing import Any, Mapping

from .enhanced_source_audit import (
    _modality,
    _section_has_content,
    _scope,
)


INPUT_STATUS_VALUES = frozenset(
    {
        "complete",
        "analysis_supported",
        "parent_context_only",
        "audio_or_image_missing",
        "sibling_mapping_ambiguous",
        "insufficient",
    }
)

LLM_INPUT_STATUS_VALUES = frozenset(
    {"complete", "analysis_supported", "insufficient", "ambiguous"}
)

_GENERIC_ANALYSIS = re.compile(
    r"^(?:略|无|无解析|同\s*[（(]\s*\d+\s*[）)]\s*题详解|同上(?:题)?详解?)$"
)
_SIBLING_REFERENCE = re.compile(r"同\s*[（(]\s*\d+\s*[）)]")
_ANALYSIS_EVIDENCE = re.compile(
    r"(?:考查|考察|句意|根据.{0,30}(?:可知|可见)|表示|指的是|应(?:填|选|用)|故选|故填|用.+表示)"
)


def _section_text(value: str, prefixes: tuple[str, ...]) -> str:
    """Extract the first section body while respecting the rendered fields."""
    lines = value.splitlines()
    section_prefixes = (
        "题目题干：",
        "当前小题题干：",
        "题目选项：",
        "当前小题选项：",
        "题目解析：",
        "当前小题解析：",
        "题目答案：",
        "当前小题答案：",
        "小题序号：",
        "题目大题题干：",
        "大题题干：",
        "父题上下文：",
        "根据以上信息，当前题目所属的题型方法类目和知识点类目为：",
    )
    for index, line in enumerate(lines):
        stripped = line.strip()
        prefix = next((item for item in prefixes if stripped.startswith(item)), None)
        if prefix is None:
            continue
        tail = stripped[len(prefix) :].strip()
        body = [tail] if tail else []
        for next_line in lines[index + 1 :]:
            next_stripped = next_line.strip()
            if next_stripped.startswith(section_prefixes):
                break
            if next_stripped:
                body.append(next_stripped)
        return "\n".join(item for item in body if item).strip()
    return ""


def _packet_scope(packet_row: Mapping[str, Any]) -> str:
    if isinstance(packet_row.get("is_sub_question"), bool):
        return "child" if packet_row["is_sub_question"] else "parent"
    route_key = packet_row.get("route_key")
    if isinstance(route_key, Mapping) and route_key.get("scope") in {"child", "parent"}:
        return str(route_key["scope"])
    return "unknown"


def _has_explicit_analysis(analysis: str) -> bool:
    normalized = re.sub(r"\s+", "", analysis)
    if not normalized or _GENERIC_ANALYSIS.fullmatch(normalized):
        return False
    if _SIBLING_REFERENCE.search(normalized):
        return False
    return bool(_ANALYSIS_EVIDENCE.search(analysis)) and len(normalized) >= 8


def classify_input_completeness(packet_row: Mapping[str, object]) -> dict[str, object]:
    """Classify whether a sanitized packet has enough evidence for label review.

    This is deliberately conservative. It never decides whether the label is
    correct; it only records what kind of input evidence is available.
    """
    question_text = packet_row.get("question_text")
    text = question_text.strip() if isinstance(question_text, str) else ""
    has_stem = _section_has_content(text, ("题目题干：", "当前小题题干："))
    has_options = _section_has_content(text, ("题目选项：", "当前小题选项："))
    has_answer = _section_has_content(text, ("题目答案：", "当前小题答案："))
    has_analysis = _section_has_content(text, ("题目解析：", "当前小题解析："))
    has_parent_material = _section_has_content(
        text, ("题目大题题干：", "大题题干：", "父题上下文：")
    )
    analysis = _section_text(text, ("题目解析：", "当前小题解析："))
    modality = _modality(packet_row, text)
    scope = _packet_scope(packet_row)
    sibling_reference = bool(_SIBLING_REFERENCE.search(analysis))
    explicit_analysis = _has_explicit_analysis(analysis)

    if not text:
        status = "insufficient"
        reason = "题面为空"
    elif sibling_reference and not has_stem:
        status = "sibling_mapping_ambiguous"
        reason = "解析引用其他小题，无法确认当前小题"
    elif has_stem:
        status = "complete"
        reason = "存在直接题干"
    elif explicit_analysis and (has_answer or has_options):
        status = "analysis_supported"
        reason = "无直接题干，但解析含具体判断依据"
    elif scope == "child" and has_parent_material:
        status = "parent_context_only"
        reason = "只有父题上下文，没有当前小题题干"
    elif has_analysis:
        status = "insufficient"
        reason = "只有泛化解析，缺少具体判断依据"
    elif modality in {"audio", "image", "audio_image"}:
        status = "audio_or_image_missing"
        reason = "依赖音频或图片，但没有可核验的直接题面"
    else:
        status = "insufficient"
        reason = "缺少直接题干和充分解析"

    return {
        "status": status,
        "scope": scope,
        "modality": modality,
        "has_stem": has_stem,
        "has_options": has_options,
        "has_answer": has_answer,
        "has_analysis": has_analysis,
        "has_parent_material": has_parent_material,
        "analysis_explicit": explicit_analysis,
        "audio": modality in {"audio", "audio_image"},
        "image": modality in {"image", "audio_image"},
        "reason": reason,
    }
