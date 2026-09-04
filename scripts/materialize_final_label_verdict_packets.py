#!/usr/bin/env python3
"""Join full DS verdicts to v3 source rows and route per-label result packets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.materialize_final_label_verdict_packets import (
    materialize_final_label_verdict_packets,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet-dir", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--source-v3", type=Path, required=True)
    parser.add_argument("--processed-dir", type=Path, required=True)
    parser.add_argument("--issue-dir", type=Path, required=True)
    parser.add_argument("--processed-label", action="append", default=[])
    parser.add_argument("--issue-label", action="append", default=[])
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = materialize_final_label_verdict_packets(
            packet_dir=args.packet_dir,
            evidence_dir=args.evidence_dir,
            source_path=args.source_v3,
            processed_dir=args.processed_dir,
            issue_dir=args.issue_dir,
            processed_labels=tuple(args.processed_label),
            issue_labels=tuple(args.issue_label),
            report_path=args.report,
        )
    except (FileExistsError, FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
