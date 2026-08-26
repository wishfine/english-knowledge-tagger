#!/usr/bin/env python3
"""Normalize a model-runner JSONL export for the direct terminal-label gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.terminal_label_discriminator_normalize import (
    load_discriminator_field_map,
    normalise_terminal_label_discriminator_row,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Raw JSONL from one discriminator runner")
    parser.add_argument("--field-map", type=Path, required=True, help="Explicit runner field mapping JSON")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite existing output: {args.output}")
    try:
        field_map = load_discriminator_field_map(args.field_map)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        rows = 0
        with args.input.open("r", encoding="utf-8") as source, args.output.open("x", encoding="utf-8") as output:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                try:
                    raw_row = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(f"raw discriminator line {line_number}: invalid JSON") from error
                output.write(
                    json.dumps(
                        normalise_terminal_label_discriminator_row(
                            raw_row, line_number=line_number, field_map=field_map
                        ),
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\n"
                )
                rows += 1
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps({"input": str(args.input), "output": str(args.output), "rows": rows}, ensure_ascii=False))


if __name__ == "__main__":
    main()
