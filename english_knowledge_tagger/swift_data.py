"""Convert validated records to the system/query/response schema used by MS-Swift."""

from __future__ import annotations

from .data import QuestionRecord
from .prompting import build_messages, canonical_response


def to_swift_sft_row(record: QuestionRecord) -> dict[str, str]:
    """Return one completion-only SFT row without leaking labels into the prompt."""
    messages = build_messages(record)
    return {
        "system": messages[0]["content"],
        "query": messages[1]["content"],
        "response": canonical_response(record.knowledge_points),
    }
