#!/usr/bin/env python3
"""Materialize validated cross-label global-cluster decisions."""

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
    materialize_global_merge,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    if args.output_root.exists():
        parser.error("output root already exists; choose a new directory")
    try:
        report = materialize_global_merge(args.packet, args.decisions, args.output_root)
    except (GlobalTypeMergeError, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
