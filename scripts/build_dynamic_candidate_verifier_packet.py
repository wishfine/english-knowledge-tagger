#!/usr/bin/env python3
"""Build candidate verification rows for three-run unanimous dynamic leaves."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.dynamic_leaf_experiment import (
    build_dynamic_candidate_verifier_packet,
)
from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook


def _jsonl(path: Path):
    rows = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path} line {line_number}: invalid JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"{path} line {line_number}: row must be an object")
            rows.append(row)
    return tuple(rows)


def _named(value: str):
    name, separator, raw_path = value.partition("=")
    if not separator or not name.strip() or not raw_path.strip():
        raise ValueError("--resolver-run must use NAME=PATH")
    return name.strip(), Path(raw_path.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--resolver-run", action="append", required=True)
    parser.add_argument("--teacher-csv", type=Path, required=True)
    parser.add_argument("--definition-overrides", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite existing output: {args.output}")
    try:
        named = tuple(_named(value) for value in args.resolver_run)
        if len(named) != 3 or len({name for name, _ in named}) != 3:
            raise ValueError("exactly three uniquely named --resolver-run values are required")
        packet = build_dynamic_candidate_verifier_packet(
            _jsonl(args.tasks),
            resolver_runs=tuple((name, _jsonl(path)) for name, path in named),
            rulebook=load_knowledge_rulebook(
                args.teacher_csv, overrides_path=args.definition_overrides
            ),
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        for row in packet:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    report = {
        "schema_version": "dynamic-candidate-verifier-packet-report-v1",
        "tasks": str(args.tasks),
        "resolver_runs": {name: str(path) for name, path in named},
        "output": str(args.output),
        "records": len(packet),
    }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
