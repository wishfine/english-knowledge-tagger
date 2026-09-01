#!/usr/bin/env python3
"""Expand one stability split with all or one selected D3 definition candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.contrastive_definition import (
    expand_stability_packet_with_definition_candidates,
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--definitions", type=Path, required=True)
    parser.add_argument("--split", choices=("definition_dev", "locked_test"), required=True)
    parser.add_argument("--selected-variant")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite existing output: {args.output}")
    try:
        definitions = json.loads(args.definitions.read_text(encoding="utf-8"))
        candidates = definitions.get("candidates") if isinstance(definitions, dict) else None
        if not isinstance(candidates, list):
            raise ValueError("definitions candidates must be a list")
        if args.selected_variant:
            candidates = [
                item
                for item in candidates
                if isinstance(item, dict) and item.get("candidate_id") == args.selected_variant
            ]
            if len(candidates) != 1:
                raise ValueError("selected definition variant is absent or duplicated")
        expanded = expand_stability_packet_with_definition_candidates(
            _jsonl(args.packet), candidates=candidates, split=args.split
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        for row in expanded:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    report = {
        "schema_version": "contrastive-definition-packet-expansion-report-v1",
        "packet": str(args.packet),
        "definitions": str(args.definitions),
        "split": args.split,
        "selected_variant": args.selected_variant,
        "output": str(args.output),
        "records": len(expanded),
    }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
