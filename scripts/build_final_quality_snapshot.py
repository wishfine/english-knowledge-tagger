#!/usr/bin/env python3
"""Build an offline, unreleased quality snapshot from completed final evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.final_quality_snapshot import build_final_quality_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir",
        type=Path,
        action="append",
        required=True,
        help="completed final-discriminator run directory; repeat to merge multiple runs",
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--teacher-csv", type=Path, required=True)
    parser.add_argument("--taxonomy-migration", type=Path, required=True)
    parser.add_argument("--exclude-label", action="append", default=[])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = build_final_quality_snapshot(
            run_dirs=tuple(args.run_dir),
            source_path=args.source,
            output_dir=args.output_dir,
            excluded_labels=tuple(args.exclude_label),
            teacher_csv=args.teacher_csv,
            taxonomy_migration=args.taxonomy_migration,
        )
    except (FileExistsError, FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
