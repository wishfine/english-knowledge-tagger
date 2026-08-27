#!/usr/bin/env python3
"""Rank mentor verifier labels by their conservative match-true yield bound."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.mentor_verification_priority import (
    assess_mentor_verification_summary,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True, help="mentor overall_summary.json")
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--target-lcb", type=float, default=0.70)
    parser.add_argument("--minimum-true-records", type=int, default=12)
    args = parser.parse_args()
    if args.output_json.exists() or args.output_csv.exists():
        parser.error("refusing to overwrite an existing priority output")
    try:
        summary = json.loads(args.summary.read_text(encoding="utf-8"))
        rows = assess_mentor_verification_summary(
            summary,
            target_lcb=args.target_lcb,
            minimum_true_records=args.minimum_true_records,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "mentor-verification-priority-v1",
        "target_wilson_lower_95": args.target_lcb,
        "minimum_true_records": args.minimum_true_records,
        "rows": list(rows),
    }
    args.output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with args.output_csv.open("x", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]) if rows else ["verify_label", "status"])
        writer.writeheader()
        writer.writerows(rows)
    print(
        json.dumps(
            {
                "output_json": str(args.output_json),
                "output_csv": str(args.output_csv),
                "labels": len(rows),
                "rollout_candidates": sum(row["status"] == "rollout_candidate" for row in rows),
                "note": "yield_only_not_label_accuracy",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
