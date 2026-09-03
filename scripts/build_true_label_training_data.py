#!/usr/bin/env python3
"""Assemble v3 training rows from positive final-label evidence, offline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.true_label_training_assembly import (
    build_true_label_training_data,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-db", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True, help="repaired v3 source JSONL")
    parser.add_argument("--teacher-csv", type=Path, required=True)
    parser.add_argument("--taxonomy-migration", type=Path, required=True)
    parser.add_argument(
        "--exclude-label",
        action="append",
        default=[],
        help="knowledge label to remove from merged outputs (repeatable; raw @ or canonical ->)",
    )
    parser.add_argument("--output", type=Path, required=True, help="training JSONL")
    parser.add_argument("--provenance-output", type=Path, required=True)
    parser.add_argument("--hold-output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    if args.report.exists():
        parser.error(f"refusing to overwrite existing report: {args.report}")
    try:
        report = build_true_label_training_data(
            snapshot_db=args.snapshot_db,
            source_path=args.source,
            teacher_csv=args.teacher_csv,
            taxonomy_migration=args.taxonomy_migration,
            output_path=args.output,
            provenance_path=args.provenance_output,
            hold_output_path=args.hold_output,
            excluded_labels=tuple(args.exclude_label),
        )
    except (FileExistsError, FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
