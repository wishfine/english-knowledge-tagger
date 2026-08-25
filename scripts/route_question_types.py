#!/usr/bin/env python3
"""Route a rendered SFT JSONL source with an exact, versioned type policy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.type_routing import load_type_routing_policy, route_sft_jsonl
from english_knowledge_tagger.type_rulebook import load_type_rulebook


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--teacher-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    if args.output.exists() or args.report.exists():
        parser.error("refusing to overwrite an existing route output or report")
    try:
        policy = load_type_routing_policy(args.policy)
        rulebook = load_type_rulebook(args.teacher_csv)
        report = route_sft_jsonl(
            args.input,
            output_path=args.output,
            policy=policy,
            rulebook=rulebook,
            limit=args.limit,
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
