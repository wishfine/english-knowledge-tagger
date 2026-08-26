#!/usr/bin/env python3
"""Resolve a human blind review packet through its explicit A/B option mapping."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.knowledge_tree_definition_review_analysis import (
    summarize_definition_ablation_reviews,
)


def _load_jsonl(path: Path, *, name: str) -> tuple[Mapping[str, object], ...]:
    rows: list[Mapping[str, object]] = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{name} line {line_number} is not valid JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"{name} line {line_number} must be an object")
            rows.append(row)
    return tuple(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, required=True, help="JSONL mapping from blind A/B to mode and label")
    parser.add_argument("--reviews", type=Path, required=True, help="JSONL human blind review decisions")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite existing output: {args.output}")
    try:
        report = summarize_definition_ablation_reviews(
            _load_jsonl(args.mapping, name="mapping"),
            _load_jsonl(args.reviews, name="reviews"),
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
