#!/usr/bin/env python3
"""Validate non-releasing route guidance for a frozen candidate manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.candidate_route_guidance import (
    build_candidate_route_guidance_report,
    load_candidate_route_guidance,
)
from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guidance", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--teacher-csv", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error(f"refusing to overwrite existing report: {args.report}")
    try:
        guidance = load_candidate_route_guidance(
            args.guidance,
            manifest_path=args.manifest,
            rulebook=load_knowledge_rulebook(args.teacher_csv),
        )
        report = build_candidate_route_guidance_report(guidance)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
