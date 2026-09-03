#!/usr/bin/env python3
"""Build bounded, stratified packets for the input-status pilot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.input_status_pilot_packet import build_input_status_pilot_packets


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--label-definitions", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--max-per-label", type=int, default=24)
    parser.add_argument("--max-per-status", type=int, default=4)
    parser.add_argument("--seed", default="input-status-pilot-v1")
    args = parser.parse_args()
    if args.report.exists():
        parser.error(f"refusing to overwrite existing report: {args.report}")
    try:
        report = build_input_status_pilot_packets(
            args.source,
            manifest_path=args.manifest,
            label_definitions_path=args.label_definitions,
            output_dir=args.output_dir,
            max_per_label=args.max_per_label,
            max_per_status=args.max_per_status,
            seed=args.seed,
        )
    except (FileExistsError, OSError, ValueError) as error:
        parser.error(str(error))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
