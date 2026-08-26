#!/usr/bin/env python3
"""Assemble conservative silver question candidates from positive label evidence."""

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
from english_knowledge_tagger.silver_question_assembly import assemble_silver_questions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--silver-evidence", type=Path, required=True)
    parser.add_argument("--teacher-csv", type=Path, required=True)
    parser.add_argument("--taxonomy-migration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hold-output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.hold_output.exists() or args.report.exists():
        parser.error("refusing to overwrite an existing silver assembly output or report")
    try:
        report = assemble_silver_questions(
            source_path=args.source,
            silver_evidence_path=args.silver_evidence,
            rulebook=load_knowledge_rulebook(args.teacher_csv),
            migration=load_knowledge_taxonomy_migration(args.taxonomy_migration),
            output_path=args.output,
            hold_output_path=args.hold_output,
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
