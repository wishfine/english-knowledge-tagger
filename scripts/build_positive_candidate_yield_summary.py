#!/usr/bin/env python3
"""Build a current DS-match summary for frozen positive-candidate manifests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.positive_candidate_yield_summary import (
    build_positive_candidate_yield_summary,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", action="append", type=Path, required=True)
    parser.add_argument("--mentor-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite existing output: {args.output}")
    try:
        report = build_positive_candidate_yield_summary(tuple(args.manifest), args.mentor_report)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(json.dumps({"candidate_labels": report.count("| 知识点@"), "output": str(args.output)}))


if __name__ == "__main__":
    main()
