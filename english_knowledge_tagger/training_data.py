"""Completion-only tokenization shared by the supervised training command."""

from __future__ import annotations

from typing import Any, Protocol

from .data import QuestionRecord
from .prompting import build_messages, canonical_response


class ChatTokenizer(Protocol):
    eos_token: str | None

    def apply_chat_template(self, messages: list[dict[str, str]], *, tokenize: bool, add_generation_prompt: bool) -> Any: ...

    def __call__(self, text: str, *, add_special_tokens: bool) -> dict[str, Any]: ...


def tokenize_completion(
    tokenizer: ChatTokenizer,
    prompt_messages: list[dict[str, str]],
    completion: str,
    max_length: int | None = None,
) -> dict[str, list[int]]:
    """Tokenize a chat prompt while applying loss only to its assistant completion."""
    prompt_ids = list(
        tokenizer.apply_chat_template(prompt_messages, tokenize=True, add_generation_prompt=True)
    )
    eos_token = tokenizer.eos_token or ""
    completion_ids = list(tokenizer(completion + eos_token, add_special_tokens=False)["input_ids"])
    if not completion_ids:
        raise ValueError("completion must produce at least one token")
    if max_length is not None:
        if max_length <= 0:
            raise ValueError("max_length must be positive")
        if len(completion_ids) > max_length:
            raise ValueError("max_length is shorter than the required assistant completion")
        prompt_ids = prompt_ids[-(max_length - len(completion_ids)) :] if max_length > len(completion_ids) else []

    input_ids = prompt_ids + completion_ids
    return {
        "input_ids": input_ids,
        "attention_mask": [1] * len(input_ids),
        "labels": [-100] * len(prompt_ids) + completion_ids,
    }


def build_training_example(tokenizer: ChatTokenizer, record: QuestionRecord, max_length: int) -> dict[str, list[int]]:
    """Render one validated record into a masked causal-language-model example."""
    return tokenize_completion(
        tokenizer,
        build_messages(record),
        canonical_response(record.knowledge_points),
        max_length=max_length,
    )
