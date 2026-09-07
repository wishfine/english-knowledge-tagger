#!/usr/bin/env python3
"""Build the reproducible four-pool label freeze manifest."""

from __future__ import annotations

import argparse
from pathlib import Path

from english_knowledge_tagger.label_pool_freeze import build_label_pool_freeze


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status-ledger", type=Path, required=True)
    parser.add_argument("--low-quality-ledger", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    parser.add_argument("--expected-label-count", type=int, default=384)
    args = parser.parse_args()
    payload = build_label_pool_freeze(
        status_ledger=args.status_ledger,
        low_quality_ledger=args.low_quality_ledger,
        output_json=args.output_json,
        output_markdown=args.output_markdown,
        expected_label_count=args.expected_label_count,
    )
    print(
        {
            "schema_version": payload["schema_version"],
            "freeze_id": payload["freeze_id"],
            "pool_counts": payload["pool_counts"],
            "output_json": str(args.output_json),
            "output_markdown": str(args.output_markdown),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

