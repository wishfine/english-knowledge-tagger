#!/usr/bin/env python3
"""Compare dynamic leaf candidate budgets against approved teacher corrections offline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.dynamic_leaf_coverage import summarize_dynamic_leaf_coverage
from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON: {path}") from error


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


def _baseline(path: Path | None):
    if path is None:
        return None
    result = {}
    for row in _jsonl(path):
        question_id = row.get("question_id")
        target = row.get("canonical_label")
        alternatives = row.get("alternative_labels")
        if not isinstance(question_id, str) or not isinstance(target, str):
            raise ValueError("baseline packet row is missing question_id/canonical_label")
        if not isinstance(alternatives, list):
            raise ValueError("baseline packet alternative_labels must be a list")
        labels = {
            str(item["label"])
            for item in alternatives
            if isinstance(item, dict) and isinstance(item.get("label"), str)
        }
        identity = (question_id, target)
        if identity in result and result[identity] != labels:
            raise ValueError("baseline packet contains conflicting duplicate identity")
        result[identity] = labels
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teacher-csv", type=Path, required=True)
    parser.add_argument("--definition-overrides", type=Path)
    parser.add_argument("--corrections", type=Path, required=True)
    parser.add_argument("--ambiguity-manifest", type=Path, required=True)
    parser.add_argument("--baseline-packet", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite existing output: {args.output}")
    try:
        report = summarize_dynamic_leaf_coverage(
            load_knowledge_rulebook(
                args.teacher_csv, overrides_path=args.definition_overrides
            ),
            corrections=_jsonl(args.corrections),
            ambiguity_manifest=_json(args.ambiguity_manifest),
            baseline_candidates=_baseline(args.baseline_packet),
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
