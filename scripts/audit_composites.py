#!/usr/bin/env python3
"""Audit parent/child label inheritance in a large composite-question JSONL file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.composite_audit import audit_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="source JSONL to audit")
    parser.add_argument("--output", type=Path, required=True, help="JSON report destination")
    parser.add_argument(
        "--index",
        type=Path,
        required=True,
        help="new persistent SQLite parent index; fails rather than overwriting an existing file",
    )
    parser.add_argument(
        "--discourse-knowledge-id",
        action="append",
        default=[],
        help="knowledge-point ID to remove for the discourse-only child-label statistic; repeatable",
    )
    args = parser.parse_args()

    report = audit_jsonl(
        args.input,
        index_path=args.index,
        discourse_knowledge_ids=set(args.discourse_knowledge_id),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "index": str(args.index),
                "records": report["records"],
                "knowledge_parent_child": report["knowledge_parent_child"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
