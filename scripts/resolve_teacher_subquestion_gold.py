#!/usr/bin/env python3
"""Resolve teacher parent-ID/subquestion-index gold to final source child records."""

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
from english_knowledge_tagger.teacher_subquestion_gold_resolution import (
    resolve_teacher_subquestion_gold,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--imported-gold", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--teacher-csv", type=Path, required=True)
    parser.add_argument("--taxonomy-migration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--corrections-output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.corrections_output.exists() or args.report.exists():
        parser.error("refusing to overwrite an existing teacher gold resolution output or report")
    try:
        report = resolve_teacher_subquestion_gold(
            args.imported_gold,
            source_path=args.source,
            rulebook=load_knowledge_rulebook(args.teacher_csv),
            migration=load_knowledge_taxonomy_migration(args.taxonomy_migration),
            output_path=args.output,
            corrections_output_path=args.corrections_output,
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
