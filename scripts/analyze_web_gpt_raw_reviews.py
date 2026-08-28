#!/usr/bin/env python3
"""Normalize and summarize a web-GPT review of one raw mentor label JSONL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.web_gpt_raw_review_analysis import analyze_web_gpt_raw_reviews


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--reviewer-results", type=Path, required=True)
    parser.add_argument("--verify-label", required=True)
    parser.add_argument("--normalized-output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.normalized_output == args.report:
        parser.error("normalized output and report paths must differ")
    existing = [path for path in (args.normalized_output, args.report) if path.exists()]
    if existing:
        parser.error(f"refusing to overwrite existing output: {existing[0]}")
    try:
        report, normalized = analyze_web_gpt_raw_reviews(
            args.source,
            reviewer_results_path=args.reviewer_results,
            verify_label=args.verify_label,
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    args.normalized_output.parent.mkdir(parents=True, exist_ok=True)
    with args.normalized_output.open("x", encoding="utf-8") as output:
        for row in normalized:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
