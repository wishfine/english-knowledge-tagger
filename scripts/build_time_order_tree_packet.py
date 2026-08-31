#!/usr/bin/env python3
"""Build the fixed 60-remove plus 12-keep Order-1 tree packet."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from english_knowledge_tagger.time_order_tree_packet import build_time_order_tree_packet


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit-index", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--seed", required=True)
    args = parser.parse_args()
    if args.output == args.audit_index or args.report in {args.output, args.audit_index}:
        parser.error("--output, --audit-index and --report must be distinct")
    if args.output.exists() or args.audit_index.exists() or args.report.exists():
        parser.error("refusing to overwrite an existing packet, audit index or report")
    try:
        report = build_time_order_tree_packet(
            args.source,
            evidence_path=args.evidence,
            output_path=args.output,
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
