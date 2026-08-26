#!/usr/bin/env python3
"""Compare three baseline and three all-direct-sibling DS validation runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.knowledge_effective_pool_ablation_analysis import (
    Run,
    summarize_effective_pool_ablation,
)


def _named_path(value: str) -> tuple[str, Path]:
    name, separator, raw_path = value.partition("=")
    if not separator or not name.strip() or not raw_path.strip():
        raise argparse.ArgumentTypeError("run must use NAME=PATH")
    return name.strip(), Path(raw_path.strip())


def _load_rows(name: str, path: Path) -> tuple[Mapping[str, object], ...]:
    rows: list[Mapping[str, object]] = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"run {name} line {line_number} is not valid JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"run {name} line {line_number} must be an object")
            rows.append(row)
    return tuple(rows)


def _runs(values: list[tuple[str, Path]], *, group: str) -> tuple[Run, ...]:
    if len(values) != 3:
        raise ValueError(f"{group} requires exactly three NAME=PATH runs")
    if len({name for name, _ in values}) != len(values):
        raise ValueError(f"{group} has duplicate run names")
    return tuple((name, _load_rows(name, path)) for name, path in values)


def _new_labels(path: Path) -> dict[str, tuple[str, ...]]:
    selected: dict[str, tuple[str, ...]] = {}
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"coverage line {line_number} is not valid JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"coverage line {line_number} must be an object")
            review_id = row.get("review_id")
            labels = row.get("newly_available_alternative_labels")
            if not isinstance(review_id, str) or not review_id.strip() or not isinstance(labels, list):
                raise ValueError(f"coverage line {line_number} needs review_id and label list")
            normalized = tuple(label for label in labels if isinstance(label, str) and label.strip())
            if not normalized:
                continue
            if len(normalized) != len(labels) or len(set(normalized)) != len(normalized):
                raise ValueError(f"coverage line {line_number} has invalid newly available labels")
            if review_id in selected:
                raise ValueError(f"coverage has duplicate review_id {review_id}")
            selected[review_id] = normalized
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=_named_path, action="append", default=[])
    parser.add_argument("--candidate", type=_named_path, action="append", default=[])
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite existing output: {args.output}")
    try:
        report = summarize_effective_pool_ablation(
            _runs(args.baseline, group="baseline"),
            _runs(args.candidate, group="candidate"),
            new_labels_by_review_id=_new_labels(args.coverage),
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
