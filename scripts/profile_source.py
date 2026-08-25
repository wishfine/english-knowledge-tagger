#!/usr/bin/env python3
"""Write a streaming data-quality profile for a raw or processed question JSONL file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.source_profile import profile_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="source JSONL to profile")
    parser.add_argument("--output", type=Path, required=True, help="destination JSON report")
    parser.add_argument(
        "--max-records",
        type=int,
        default=None,
        help="optional cap on valid object records for a fast sample profile",
    )
    args = parser.parse_args()

    report = profile_jsonl(args.input, max_records=args.max_records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "valid_records": report["valid_records"],
                "invalid_json_lines": report["invalid_json_lines"],
                "non_object_lines": report["non_object_lines"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
