#!/usr/bin/env python3
"""Build blinded true and stratified false review packets for one P0 label."""

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
from english_knowledge_tagger.p0_direct_diagnosis import build_p0_direct_diagnosis_packets


def _legacy_path(rendered_label: str) -> str:
    return "知识点->" + rendered_label.removeprefix("知识点@").replace("@", "->")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--verify-label", required=True)
    parser.add_argument("--teacher-csv", type=Path, required=True)
    parser.add_argument("--taxonomy-migration", type=Path, required=True)
    parser.add_argument("--true-output", type=Path, required=True)
    parser.add_argument("--false-output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--false-sample-size", type=int, default=60)
    parser.add_argument("--false-boundary-question-id", action="append", default=[])
    parser.add_argument("--seed", required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error(f"refusing to overwrite existing report: {args.report}")
    try:
        migration = load_knowledge_taxonomy_migration(args.taxonomy_migration)
        taxonomy = migration.canonicalize(_legacy_path(args.verify_label))
        rulebook = load_knowledge_rulebook(args.teacher_csv)
        definition = rulebook.records.get(taxonomy.canonical_path)
        if definition is None or definition.status != "active":
            raise ValueError(
                f"teacher CSV has no active terminal definition for {taxonomy.canonical_path}"
            )
        report = build_p0_direct_diagnosis_packets(
            args.input,
            verify_label=args.verify_label,
            teacher_definition=definition.target_definition,
            migration=migration,
            true_output_path=args.true_output,
            false_output_path=args.false_output,
            audit_output_path=args.audit_output,
            false_sample_size=args.false_sample_size,
            false_boundary_question_ids=tuple(args.false_boundary_question_id),
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
