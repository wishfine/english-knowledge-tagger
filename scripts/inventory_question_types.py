#!/usr/bin/env python3
"""Create a parent/child question-type inventory and an editable policy-mapping CSV."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.type_inventory import inventory_sft_jsonl


CSV_FIELDS = (
    "scope",
    "declared_type_structure",
    "declared_type_name",
    "record_count",
    "knowledge_label_count_distribution",
    "historical_type_labels",
    "sample_question_ids",
    "policy_status",
    "knowledge_policy",
    "required_type_policy",
    "review_notes",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--sample-limit", type=int, default=3)
    args = parser.parse_args()

    if args.output_json.exists() or args.output_csv.exists():
        parser.error("refusing to overwrite an existing inventory output")
    report = inventory_sft_jsonl(args.input, sample_limit=args.sample_limit)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with args.output_csv.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in report["rows"]:
            writer.writerow(
                {
                    "scope": row["scope"],
                    "declared_type_structure": row["declared_type_structure"],
                    "declared_type_name": row["declared_type_name"],
                    "record_count": row["record_count"],
                    "knowledge_label_count_distribution": json.dumps(
                        row["knowledge_label_count_distribution"], ensure_ascii=False, sort_keys=True
                    ),
                    "historical_type_labels": json.dumps(
                        row["historical_type_labels"], ensure_ascii=False, sort_keys=True
                    ),
                    "sample_question_ids": json.dumps(
                        row["sample_question_ids"], ensure_ascii=False
                    ),
                    "policy_status": "unmapped",
                    "knowledge_policy": "",
                    "required_type_policy": "",
                    "review_notes": "",
                }
            )
    print(
        json.dumps(
            {
                "input": str(args.input),
                "output_json": str(args.output_json),
                "output_csv": str(args.output_csv),
                "scope_counts": report["scope_counts"],
                "inventory_rows": len(report["rows"]),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
