#!/usr/bin/env python3
"""Build independent blind post-sweep packets from a merged final snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.final_post_sweep_sampler import build_final_post_sweep_packets


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-db", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--exclude-jsonl", type=Path)
    parser.add_argument("--exclude-label", action="append", default=[])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sample-size", type=int, default=60)
    parser.add_argument("--seed", required=True)
    args = parser.parse_args()
    try:
        report = build_final_post_sweep_packets(
            snapshot_db=args.snapshot_db,
            source_path=args.source,
            output_dir=args.output_dir,
            exclude_jsonl_path=args.exclude_jsonl,
            sample_size=args.sample_size,
            seed=args.seed,
            excluded_labels=args.exclude_label,
        )
    except (FileExistsError, FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
