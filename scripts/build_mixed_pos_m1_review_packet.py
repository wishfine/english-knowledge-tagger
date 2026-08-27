#!/usr/bin/env python3
"""Create a blind human/Gemini review packet for mixed-POS label M1."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook
from english_knowledge_tagger.low_quality_label_review_packets import (
    build_mixed_pos_m1_review_packet,
)


def _canonical_path(rendered_label: str) -> str:
    return "知识点->" + rendered_label.removeprefix("知识点@").replace("@", "->")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--teacher-csv", type=Path, required=True)
    parser.add_argument("--verify-label", required=True)
    parser.add_argument("--blind-output", type=Path, required=True)
    parser.add_argument("--audit-index", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--seed", required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error(f"refusing to overwrite existing report: {args.report}")
    try:
        canonical_path = _canonical_path(args.verify_label)
        definition_record = load_knowledge_rulebook(args.teacher_csv).records.get(canonical_path)
        if definition_record is None or definition_record.status != "active":
            raise ValueError(f"teacher CSV has no active terminal definition for {canonical_path}")
        report = build_mixed_pos_m1_review_packet(
            args.input,
            verify_label=args.verify_label,
            teacher_definition=definition_record.target_definition,
            blind_output_path=args.blind_output,
            audit_index_path=args.audit_index,
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
