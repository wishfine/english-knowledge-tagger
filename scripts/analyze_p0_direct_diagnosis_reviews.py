#!/usr/bin/env python3
"""Validate and summarize a completed P0 blinded-review result JSONL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.p0_direct_diagnosis_review_analysis import (
    analyze_p0_direct_diagnosis_reviews,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--true-packet", type=Path, required=True)
    parser.add_argument("--false-packet", type=Path, required=True)
    parser.add_argument("--audit-index", type=Path, required=True)
    parser.add_argument("--reviewer-results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite existing output: {args.output}")
    try:
        report = analyze_p0_direct_diagnosis_reviews(
            args.true_packet,
            false_packet_path=args.false_packet,
            audit_index_path=args.audit_index,
            reviewer_results_path=args.reviewer_results,
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
