#!/usr/bin/env python3
"""Create tree-routing replace/add tasks from existing knowledge-label audit artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.knowledge_candidate_policy import load_knowledge_candidate_policy
from english_knowledge_tagger.knowledge_tree_tasks import build_knowledge_tree_tasks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--review-packet", type=Path, required=True)
    parser.add_argument("--validation-packet", type=Path, required=True)
    parser.add_argument("--validation-verdicts", type=Path, required=True)
    parser.add_argument("--candidate-policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    if args.output.exists() or args.report.exists():
        parser.error("refusing to overwrite an existing knowledge tree task output or report")
    try:
        report = build_knowledge_tree_tasks(
            args.source,
            review_packet_path=args.review_packet,
            validation_packet_path=args.validation_packet,
            validation_verdict_path=args.validation_verdicts,
            candidate_policy=load_knowledge_candidate_policy(args.candidate_policy),
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
