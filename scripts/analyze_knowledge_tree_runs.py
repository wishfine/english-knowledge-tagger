#!/usr/bin/env python3
"""Compare three compressed-definition and three no-definition tree-routing runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.knowledge_tree_run_analysis import summarize_run_groups


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


def _runs(values: list[tuple[str, Path]], *, expected_mode: str) -> tuple[tuple[str, tuple[Mapping[str, object], ...]], ...]:
    if len(values) != 3:
        raise ValueError(f"{expected_mode} mode requires exactly three runs")
    if len({name for name, _ in values}) != len(values):
        raise ValueError(f"{expected_mode} mode has duplicate run names")
    runs = tuple((name, _load_rows(name, path)) for name, path in values)
    modes = {row.get("terminal_definition_mode") for _, rows in runs for row in rows}
    if modes != {expected_mode}:
        raise ValueError(
            f"{expected_mode} mode run rows must all declare terminal_definition_mode={expected_mode!r}"
        )
    return runs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-definitions", type=_named_path, action="append", default=[])
    parser.add_argument("--without-definitions", type=_named_path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite existing output: {args.output}")
    try:
        report = summarize_run_groups(
            {
                "compressed": _runs(args.with_definitions, expected_mode="compressed"),
                "none": _runs(args.without_definitions, expected_mode="none"),
            }
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
