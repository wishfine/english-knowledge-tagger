#!/usr/bin/env python3
"""Profile and stratify samples from cleaned_final_enhanced_v2.jsonl."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.enhanced_source_audit import profile_enhanced_source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--sample-per-bucket", type=int, default=3)
    parser.add_argument("--seed", default="enhanced-source-audit-v1")
    parser.add_argument("--progress-every", type=int, default=100_000)
    args = parser.parse_args()

    if args.output_report.exists() or args.index.exists() or args.samples.exists():
        parser.error("refusing to overwrite an existing audit output")
    if not args.input.is_file():
        parser.error(f"input is not a readable file: {args.input}")
    try:
        report = profile_enhanced_source(
            args.input,
            index_path=args.index,
            sample_output_path=args.samples,
            sample_per_bucket=args.sample_per_bucket,
            seed=args.seed,
            progress_every=args.progress_every,
            progress_callback=lambda count: print(
                json.dumps({"processed_valid_records": count}),
                file=sys.stderr,
                flush=True,
            ),
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))

    args.output_report.parent.mkdir(parents=True, exist_ok=True)
    args.output_report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "input": str(args.input),
                "output_report": str(args.output_report),
                "index": str(args.index),
                "samples": str(args.samples),
                "valid_records": report["valid_records"],
                "scope_counts": report["scope_counts"],
                "type_bucket_count": report["type_bucket_count"],
                "shape_bucket_count": report["shape_bucket_count"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
