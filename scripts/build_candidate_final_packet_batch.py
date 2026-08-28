#!/usr/bin/env python3
"""Materialize one final discriminator packet per candidate label in one source scan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.candidate_final_packet_batch import (
    build_candidate_final_packet_batch,
)
from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--guidance", type=Path, required=True)
    parser.add_argument("--teacher-csv", type=Path, required=True)
    parser.add_argument("--label-definitions", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error(f"refusing to overwrite existing report: {args.report}")
    try:
        report = build_candidate_final_packet_batch(
            args.source,
            manifest_path=args.manifest,
            guidance_path=args.guidance,
            rulebook=load_knowledge_rulebook(args.teacher_csv),
            label_definitions_path=args.label_definitions,
            output_dir=args.output_dir,
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
