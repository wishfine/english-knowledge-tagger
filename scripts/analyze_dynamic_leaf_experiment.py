#!/usr/bin/env python3
"""Apply the three-run dynamic resolver and candidate-verifier release gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.dynamic_leaf_experiment import (
    summarize_dynamic_leaf_experiment,
)


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


def _named(value: str, *, flag: str):
    name, separator, raw_path = value.partition("=")
    if not separator or not name.strip() or not raw_path.strip():
        raise ValueError(f"{flag} must use NAME=PATH")
    return name.strip(), Path(raw_path.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--resolver-run", action="append", required=True)
    parser.add_argument("--verifier-run", action="append", required=True)
    parser.add_argument("--root-baseline-mean-calls", type=float)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite existing output: {args.output}")
    try:
        resolver_named = tuple(
            _named(value, flag="--resolver-run") for value in args.resolver_run
        )
        verifier_named = tuple(
            _named(value, flag="--verifier-run") for value in args.verifier_run
        )
        if len(resolver_named) != 3 or len({name for name, _ in resolver_named}) != 3:
            raise ValueError("exactly three uniquely named resolver runs are required")
        if len(verifier_named) != 3 or len({name for name, _ in verifier_named}) != 3:
            raise ValueError("exactly three uniquely named verifier runs are required")
        report = summarize_dynamic_leaf_experiment(
            _jsonl(args.tasks),
            resolver_runs=tuple((name, _jsonl(path)) for name, path in resolver_named),
            verifier_runs=tuple((name, _jsonl(path)) for name, path in verifier_named),
            root_baseline_mean_calls=args.root_baseline_mean_calls,
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
