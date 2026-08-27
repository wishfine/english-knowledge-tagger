#!/usr/bin/env python3
"""Scan final source once for a non-releasing positive-candidate route inventory."""

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
from english_knowledge_tagger.positive_candidate_inventory import inventory_positive_candidate_batch


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--teacher-csv", type=Path, required=True)
    parser.add_argument("--taxonomy-migration", type=Path, required=True)
    parser.add_argument("--inventory-output", type=Path, required=True)
    parser.add_argument("--route-samples-output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--sample-size-per-route", type=int, default=5)
    parser.add_argument("--seed", required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error(f"refusing to overwrite existing report: {args.report}")
    try:
        report = inventory_positive_candidate_batch(
            args.source,
            manifest_path=args.manifest,
            rulebook=load_knowledge_rulebook(args.teacher_csv),
            migration=load_knowledge_taxonomy_migration(args.taxonomy_migration),
            inventory_output_path=args.inventory_output,
            route_samples_output_path=args.route_samples_output,
            sample_size_per_route=args.sample_size_per_route,
            seed=args.seed,
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
