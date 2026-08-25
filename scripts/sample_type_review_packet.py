#!/usr/bin/env python3
"""Create a blind, stratified packet for question-type policy review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.type_review_packet import build_type_review_packet


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--per-route", type=int, default=5)
    parser.add_argument("--include-legacy-labels", action="store_true")
    parser.add_argument("--scope")
    parser.add_argument("--declared-type-structure")
    parser.add_argument("--declared-type-name")
    args = parser.parse_args()

    if args.output.exists() or args.report.exists():
        parser.error("refusing to overwrite an existing packet or report")
    route_values = (args.scope, args.declared_type_structure, args.declared_type_name)
    if any(route_values) and not all(route_values):
        parser.error(
            "--scope, --declared-type-structure and --declared-type-name must be supplied together"
        )
    target_route = tuple(value.strip() for value in route_values) if all(route_values) else None
    try:
        report = build_type_review_packet(
            args.input,
            output_path=args.output,
            per_route=args.per_route,
            include_legacy_labels=args.include_legacy_labels,
            target_route=target_route,
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
