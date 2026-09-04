#!/usr/bin/env python3
"""Build one full source JSONL packet per low-quality label."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.low_quality_full_packets import (
    build_low_quality_label_full_packets,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--p0-policy", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--exclude-label", action="append", default=[])
    args = parser.parse_args()
    if args.report.exists():
        parser.error(f"refusing to overwrite existing report: {args.report}")
    try:
        report = build_low_quality_label_full_packets(
            args.source,
            policy_path=args.p0_policy,
            output_dir=args.output_dir,
            exclude_labels=args.exclude_label,
        )
    except (FileExistsError, FileNotFoundError, OSError, ValueError) as error:
        parser.error(str(error))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
