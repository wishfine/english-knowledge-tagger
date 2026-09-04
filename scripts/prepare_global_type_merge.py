#!/usr/bin/env python3
"""Flatten stage-2 candidate clusters into one label-blind global merge packet."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from english_knowledge_tagger.global_type_merge import (
    GlobalTypeMergeError,
    build_global_merge_packet,
    write_global_merge_packet,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage2-root", type=Path, required=True)
    parser.add_argument("--progress", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    if not args.stage2_root.is_dir():
        parser.error(f"stage2 root does not exist or is not a directory: {args.stage2_root}")
    if args.output_root.exists():
        parser.error("output root already exists; choose a new directory")
    progress = args.progress or (args.stage2_root / "progress.json")
    if not progress.exists():
        progress = None
    try:
        packet = build_global_merge_packet(args.stage2_root, progress_path=progress)
        report = write_global_merge_packet(packet, args.output_root)
    except (GlobalTypeMergeError, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
