#!/usr/bin/env python3
"""Apply sparse human-reviewed release policy to direct discriminator evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook
from english_knowledge_tagger.terminal_label_calibration_policy import (
    load_terminal_label_calibration_policy,
)
from english_knowledge_tagger.terminal_label_discriminator_gate import (
    gate_terminal_label_discriminator,
)


def _read_jsonl(path: Path) -> list[object]:
    rows: list[object] = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(f"input line {line_number}: invalid JSON") from error
    return rows


def _write_jsonl(path: Path, rows: tuple[dict[str, object], ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as target:
        for row in rows:
            target.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Normalised direct discriminator JSONL")
    parser.add_argument("--teacher-csv", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--silver-output", type=Path, required=True)
    parser.add_argument("--relabel-output", type=Path, required=True)
    parser.add_argument("--hold-output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    outputs = (args.silver_output, args.relabel_output, args.hold_output, args.report)
    if any(path.exists() for path in outputs):
        parser.error("refusing to overwrite an existing gate output or report")
    try:
        rulebook = load_knowledge_rulebook(args.teacher_csv)
        policy = load_terminal_label_calibration_policy(args.policy, rulebook=rulebook)
        result = gate_terminal_label_discriminator(
            _read_jsonl(args.input), policy=policy, rulebook=rulebook
        )
        _write_jsonl(args.silver_output, result.silver)
        _write_jsonl(args.relabel_output, result.relabel)
        _write_jsonl(args.hold_output, result.hold)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(result.report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result.report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
