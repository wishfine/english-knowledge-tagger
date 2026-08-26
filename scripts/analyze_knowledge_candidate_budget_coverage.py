#!/usr/bin/env python3
"""Compare frozen candidate-budget packet variants against approved gold corrections."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.knowledge_candidate_budget_coverage import (
    analyze_candidate_budget_coverage,
)


def _named_path(value: str) -> tuple[str, Path]:
    name, separator, raw_path = value.partition("=")
    if not separator or not name.strip() or not raw_path.strip():
        raise argparse.ArgumentTypeError("packet must use NAME=PATH")
    return name.strip(), Path(raw_path.strip())


def _load_jsonl(path: Path, *, label: str) -> tuple[Mapping[str, object], ...]:
    rows: list[Mapping[str, object]] = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{label} line {line_number} is not valid JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"{label} line {line_number} must be an object")
            rows.append(row)
    return tuple(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=_named_path, action="append", default=[])
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if len(args.packet) < 2:
        parser.error("--packet must be supplied at least twice")
    names = [name for name, _ in args.packet]
    if len(set(names)) != len(names):
        parser.error("--packet names must be unique")
    if args.output.exists():
        parser.error(f"refusing to overwrite existing output: {args.output}")
    try:
        packet_sets = {
            name: _load_jsonl(path, label=f"packet {name}")
            for name, path in args.packet
        }
        report = analyze_candidate_budget_coverage(
            packet_sets,
            _load_jsonl(args.gold, label="gold"),
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    report = {
        **report,
        "packet_paths": {name: str(path) for name, path in args.packet},
        "gold_path": str(args.gold),
        "output_path": str(args.output),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2, sort_keys=True)
        output.write("\n")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
