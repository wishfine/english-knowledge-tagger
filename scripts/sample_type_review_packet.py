#!/usr/bin/env python3
"""Create a blind, stratified packet for question-type policy review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.type_review_packet import build_type_review_packet


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--per-route", type=int, default=5)
    parser.add_argument("--include-legacy-labels", action="store_true")
    args = parser.parse_args()

    if args.output.exists() or args.report.exists():
        parser.error("refusing to overwrite an existing packet or report")
    try:
        report = build_type_review_packet(
            args.input,
            output_path=args.output,
            per_route=args.per_route,
            include_legacy_labels=args.include_legacy_labels,
        )
    except (FileExistsError, OSError, ValueError) as error:
        parser.error(str(error))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
