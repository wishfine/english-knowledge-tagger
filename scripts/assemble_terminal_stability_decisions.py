#!/usr/bin/env python3
"""Assemble stable keep/drop candidates and holds from a selected definition."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.terminal_label_stability import (
    assemble_terminal_stability_decisions,
)


def _jsonl(path: Path):
    rows = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path} line {line_number}: invalid JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"{path} line {line_number}: row must be an object")
            rows.append(row)
    return tuple(rows)


def _named(value: str):
    name, separator, raw_path = value.partition("=")
    if not separator or not name.strip() or not raw_path.strip():
        raise ValueError("--run must use NAME=PATH")
    return name.strip(), Path(raw_path.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--run", action="append", required=True)
    parser.add_argument("--definition-selection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite existing output: {args.output}")
    try:
        named = tuple(_named(value) for value in args.run)
        if len(named) != 3 or len({name for name, _ in named}) != 3:
            raise ValueError("exactly three uniquely named --run values are required")
        selection = json.loads(args.definition_selection.read_text(encoding="utf-8"))
        decisions = assemble_terminal_stability_decisions(
            _jsonl(args.packet),
            runs=tuple((name, _jsonl(path)) for name, path in named),
            definition_selection=selection,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        for row in decisions:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    report = {
        "schema_version": "terminal-label-stability-decision-report-v1",
        "records": len(decisions),
        "disposition_counts": {
            disposition: sum(row["disposition"] == disposition for row in decisions)
            for disposition in (
                "stable_keep_candidate",
                "stable_drop_candidate",
                "hold",
            )
        },
        "output": str(args.output),
    }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
