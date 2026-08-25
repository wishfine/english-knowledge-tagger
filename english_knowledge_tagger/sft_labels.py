"""Parsing helpers for the rendered legacy SFT target string."""

from __future__ import annotations

import re


def parse_sft_output_labels(output: object) -> tuple[frozenset[str], frozenset[str]] | None:
    """Parse ``题型@...;知识点@...`` output into knowledge and type label sets.

    Returns ``None`` only when the value is not a rendered SFT label string. Empty
    placeholders such as ``知识点@空`` are recognized and become an empty set.
    """
    if not isinstance(output, str):
        return None
    knowledge: set[str] = set()
    question_type: set[str] = set()
    recognized = False
    for fragment in re.split(r"[;；\n]+", output):
        label = fragment.strip()
        if label.startswith("知识点@"):
            recognized = True
            if label != "知识点@空":
                knowledge.add(label)
        elif label.startswith("题型@"):
            recognized = True
            if label != "题型@空":
                question_type.add(label)
    if not recognized:
        return None
    return frozenset(knowledge), frozenset(question_type)
