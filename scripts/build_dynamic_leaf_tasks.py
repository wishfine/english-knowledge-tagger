#!/usr/bin/env python3
"""Build dynamic-leaf tasks from three unanimous non-target direct runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.candidate_route_guidance import (
    load_candidate_route_guidance,
)
from english_knowledge_tagger.dynamic_leaf_experiment import build_dynamic_leaf_tasks
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


def _named(value: str):
    name, separator, raw_path = value.partition("=")
    if not separator or not name.strip() or not raw_path.strip():
        raise ValueError("--direct-run must use NAME=PATH")
    return name.strip(), Path(raw_path.strip())


def _teacher_gold(path: Path | None):
    if path is None:
        return None
    result = {}
    for row in _jsonl(path):
        if row.get("adjudication_status") != "approved":
            continue
        question_id = row.get("question_id")
        labels = row.get("all_teacher_gold_labels") or row.get("gold_labels")
        if not isinstance(question_id, str) or not isinstance(labels, list):
            raise ValueError("teacher correction row is malformed")
        normalized = tuple(str(label) for label in labels)
        existing = result.get(question_id)
        if existing is not None and existing != normalized:
            raise ValueError(f"teacher corrections conflict for question_id {question_id}")
        result[question_id] = normalized
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--direct-run", action="append", required=True)
    parser.add_argument("--ambiguity-manifest", type=Path, required=True)
    parser.add_argument("--definition-selection", type=Path, required=True)
    parser.add_argument("--teacher-corrections", type=Path)
    parser.add_argument("--route-guidance", type=Path)
    parser.add_argument("--candidate-manifest", type=Path)
    parser.add_argument("--teacher-csv", type=Path)
    parser.add_argument("--definition-overrides", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hold-output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    outputs = (args.output, args.hold_output, args.report)
    if len(set(outputs)) != len(outputs):
        parser.error("output paths must be distinct")
    if any(path.exists() for path in outputs):
        parser.error("refusing to overwrite existing output")
    try:
        named = tuple(_named(value) for value in args.direct_run)
        if len(named) != 3 or len({name for name, _ in named}) != 3:
            raise ValueError("exactly three uniquely named --direct-run values are required")
        selection = _json(args.definition_selection)
        raw_selected = selection.get("labels") if isinstance(selection, dict) else None
        if not isinstance(raw_selected, dict):
            raise ValueError("definition selection labels must be an object")
        selected = {
            label: item["definition_variant"]
            for label, item in raw_selected.items()
            if isinstance(item, dict)
            and item.get("status") == "selected"
            and isinstance(item.get("definition_variant"), str)
        }
        guidance = None
        guidance_args = (args.route_guidance, args.candidate_manifest, args.teacher_csv)
        if any(guidance_args):
            if not all(guidance_args):
                raise ValueError(
                    "route guidance requires --route-guidance, --candidate-manifest and --teacher-csv"
                )
            rulebook = load_knowledge_rulebook(
                args.teacher_csv, overrides_path=args.definition_overrides
            )
            guidance = load_candidate_route_guidance(
                args.route_guidance,
                manifest_path=args.candidate_manifest,
                rulebook=rulebook,
            )
        tasks, holds, report = build_dynamic_leaf_tasks(
            _jsonl(args.packet),
            direct_runs=tuple((name, _jsonl(path)) for name, path in named),
            ambiguity_manifest=_json(args.ambiguity_manifest),
            selected_variant_by_label=selected,
            teacher_gold_by_question=_teacher_gold(args.teacher_corrections),
            route_guidance=guidance,
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    for path, rows in ((args.output, tasks), (args.hold_output, holds)):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as output:
            for row in rows:
                output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    report = {
        **report,
        "packet": str(args.packet),
        "direct_runs": {name: str(path) for name, path in named},
        "ambiguity_manifest": str(args.ambiguity_manifest),
        "definition_selection": str(args.definition_selection),
        "output": str(args.output),
        "hold_output": str(args.hold_output),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
