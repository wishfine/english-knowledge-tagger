#!/usr/bin/env python3
"""Build a non-releasing work queue from current review and raw-yield ledgers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook
from english_knowledge_tagger.knowledge_taxonomy_migration import load_knowledge_taxonomy_migration
from english_knowledge_tagger.positive_candidate_manifest import build_positive_candidate_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-sample-ledger", type=Path, required=True)
    parser.add_argument("--raw-yield-ledger", type=Path, required=True)
    parser.add_argument("--teacher-csv", type=Path, required=True)
    parser.add_argument("--taxonomy-migration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error(f"refusing to overwrite existing report: {args.report}")
    try:
        report = build_positive_candidate_manifest(
            args.full_sample_ledger,
            raw_yield_ledger_path=args.raw_yield_ledger,
            rulebook=load_knowledge_rulebook(args.teacher_csv),
            migration=load_knowledge_taxonomy_migration(args.taxonomy_migration),
            output_path=args.output,
        )
    except (FileExistsError, OSError, ValueError) as error:
        parser.error(str(error))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
