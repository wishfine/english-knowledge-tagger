#!/usr/bin/env python3
"""Create an enriched type inventory and a new editable type-policy CSV."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.type_inventory_enriched import inventory_sft_jsonl_enriched


CSV_FIELDS = (
    "scope",
    "declared_type_structure",
    "declared_type_name",
    "record_count",
    "knowledge_label_count_distribution",
    "type_label_count_distribution",
    "unlabeled_record_count",
    "type_label_assignment_count",
    "historical_type_labels",
    "type_label_combination_counts",
    "samples_by_historical_label",
    "unlabeled_sample_question_ids",
    "type_policy_status",
    "policy_kind",
    "required_labels",
    "allowed_type_prefixes",
    "cardinality_min",
    "cardinality_max",
    "decision_rule",
    "exclusion_conditions",
    "review_sample_size",
    "reviewer",
    "review_notes",
)


def _render_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--sample-per-label", type=int, default=10)
    parser.add_argument("--sample-unlabeled", type=int, default=10)
    parser.add_argument("--progress-every", type=int, default=100_000)
    args = parser.parse_args()

    if args.output_json == args.output_csv:
        parser.error("--output-json and --output-csv must be different paths")
    if args.output_json.exists() or args.output_csv.exists():
        parser.error("refusing to overwrite an existing enriched inventory output")

    report = inventory_sft_jsonl_enriched(
        args.input,
        sample_per_label=args.sample_per_label,
        sample_unlabeled=args.sample_unlabeled,
        progress_every=args.progress_every,
        progress_callback=lambda count: print(
            json.dumps({"processed_valid_records": count}),
            file=sys.stderr,
            flush=True,
        ),
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_json.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
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
                    "knowledge_label_count_distribution": _render_json(
                        row["knowledge_label_count_distribution"]
                    ),
                    "type_label_count_distribution": _render_json(
                        row["type_label_count_distribution"]
                    ),
                    "unlabeled_record_count": row["unlabeled_record_count"],
                    "type_label_assignment_count": row["type_label_assignment_count"],
                    "historical_type_labels": _render_json(row["historical_type_labels"]),
                    "type_label_combination_counts": _render_json(
                        row["type_label_combination_counts"]
                    ),
                    "samples_by_historical_label": _render_json(
                        row["samples_by_historical_label"]
                    ),
                    "unlabeled_sample_question_ids": _render_json(
                        row["unlabeled_sample_question_ids"]
                    ),
                    "type_policy_status": "unmapped",
                    "policy_kind": "",
                    "required_labels": "",
                    "allowed_type_prefixes": "",
                    "cardinality_min": "",
                    "cardinality_max": "",
                    "decision_rule": "",
                    "exclusion_conditions": "",
                    "review_sample_size": "",
                    "reviewer": "",
                    "review_notes": "",
                }
            )

    print(
        json.dumps(
            {
                "input": str(args.input),
                "output_json": str(args.output_json),
                "output_csv": str(args.output_csv),
                "valid_records": report["valid_records"],
                "scope_counts": report["scope_counts"],
                "inventory_rows": len(report["rows"]),
                "schema_version": report["schema_version"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
