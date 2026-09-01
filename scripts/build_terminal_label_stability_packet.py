#!/usr/bin/env python3
"""Build a fixed-split D0/D1/D2 terminal-label stability packet."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook
from english_knowledge_tagger.knowledge_taxonomy_migration import (
    load_knowledge_taxonomy_migration,
)
from english_knowledge_tagger.terminal_label_stability import (
    build_terminal_label_stability_packet,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--materialized", type=Path, required=True)
    parser.add_argument("--pseudo-gold", type=Path, required=True)
    parser.add_argument("--verify-label", required=True)
    parser.add_argument("--teacher-csv", type=Path, required=True)
    parser.add_argument("--definition-overrides", type=Path, required=True)
    parser.add_argument("--taxonomy-migration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--seed", default="definition-stability-v1")
    args = parser.parse_args()
    if args.output == args.report:
        parser.error("--output and --report must differ")
    if args.report.exists():
        parser.error(f"refusing to overwrite existing report: {args.report}")
    try:
        rulebook = load_knowledge_rulebook(
            args.teacher_csv, overrides_path=args.definition_overrides
        )
        migration = load_knowledge_taxonomy_migration(args.taxonomy_migration)
        report = build_terminal_label_stability_packet(
            args.materialized,
            pseudo_gold_path=args.pseudo_gold,
            verify_label=args.verify_label,
            rulebook=rulebook,
            migration=migration,
            output_path=args.output,
            seed=args.seed,
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
