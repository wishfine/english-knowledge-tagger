"""Shared prompt and canonical supervised-response rendering."""

from __future__ import annotations

import json
from typing import Iterable

from .data import QuestionRecord, normalize_text


SYSTEM_PROMPT = """你是英语题目知识点标注助手。
只输出一个 JSON 对象，格式必须为 {\"knowledge_points\":[\"知识点1\",\"知识点2\"]}。
只选择题目实际考查的知识点；不要解释、不要输出 Markdown、不要编造 taxonomy 外的标签。"""


def build_messages(record: QuestionRecord) -> list[dict[str, str]]:
    """Render every model-visible field in a stable, human-readable order."""
    sections = [f"【题干】\n{record.question}"]
    if record.options:
        rendered_options = "\n".join(
            f"{chr(ord('A') + index)}. {option}" for index, option in enumerate(record.options)
        )
        sections.append(f"【选项】\n{rendered_options}")
    if record.answer:
        sections.append(f"【答案】\n{record.answer}")
    if record.analysis:
        sections.append(f"【解析】\n{record.analysis}")
    sections.append("请输出该题的知识点 JSON。")
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(sections)},
    ]


def canonical_response(labels: Iterable[str]) -> str:
    """Serialize labels exactly once in deterministic JSON order."""
    normalized = sorted({normalize_text(label) for label in labels if isinstance(label, str) and normalize_text(label)})
    return json.dumps({"knowledge_points": normalized}, ensure_ascii=False, separators=(",", ":"))
