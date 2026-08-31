#!/usr/bin/env python3
"""Route bounded knowledge-point tree tasks through DS-V4; output candidates only."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.candidate_labeling import LabelingServiceConfig, LabelingServiceError
from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook
from english_knowledge_tagger.knowledge_taxonomy_tree import KnowledgeTaxonomyTree
from english_knowledge_tagger.knowledge_tree_choice import (
    PROMPT_VERSION,
    TERMINAL_DEFINITION_MODES,
    KnowledgeTreeChoiceClient,
)
from english_knowledge_tagger.knowledge_tree_tasks import (
    RESULT_SCHEMA_VERSION,
    route_knowledge_tree_task,
)
from english_knowledge_tagger.knowledge_tree_timing import summarize_tree_timing


DEFAULT_ENDPOINT = "http://172.22.0.35:6636/v1/chat/completions"


def _error_output(
    row: dict[str, Any],
    error: Exception,
    *,
    max_steps: int,
    max_backtracks: int,
    terminal_definition_mode: str,
    conversion_structured_guard: bool,
    queue_elapsed_ms: float | None = None,
    task_elapsed_ms: float | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "task_id": row.get("task_id"),
        "source_line": row.get("source_line"),
        "question_id": row.get("question_id"),
        "parent_id": row.get("parent_id"),
        "is_sub_question": row.get("is_sub_question"),
        "route_key": row.get("route_key"),
        "knowledge_policy": row.get("knowledge_policy"),
        "allowed_knowledge_prefixes": row.get("allowed_knowledge_prefixes"),
        "trigger_kinds": row.get("trigger_kinds"),
        "triggers": row.get("triggers"),
        "status": "error",
        "candidate_label": None,
        "trace": [],
        "max_steps": max_steps,
        "max_backtracks": max_backtracks,
        "terminal_definition_mode": terminal_definition_mode,
        "conversion_structured_guard": conversion_structured_guard,
        "queue_elapsed_ms": queue_elapsed_ms,
        "task_elapsed_ms": task_elapsed_ms,
        "error": str(error),
    }


def _route_one(
    row: dict[str, Any],
    *,
    client: KnowledgeTreeChoiceClient,
    tree: KnowledgeTaxonomyTree,
    model: str,
    max_steps: int,
    max_backtracks: int,
    terminal_definition_mode: str,
    conversion_structured_guard: bool,
    submitted_ns: int,
) -> dict[str, Any]:
    worker_started_ns = time.perf_counter_ns()
    queue_elapsed_ms = (worker_started_ns - submitted_ns) / 1_000_000
    try:
        result = route_knowledge_tree_task(
            row,
            client=client,
            tree=tree,
            max_steps=max_steps,
            max_backtracks=max_backtracks,
        )
        return {
            **result,
            "model": model,
            "prompt_version": PROMPT_VERSION + ("-structured-guard" if conversion_structured_guard else ""),
            "terminal_definition_mode": terminal_definition_mode,
            "conversion_structured_guard": conversion_structured_guard,
            "queue_elapsed_ms": queue_elapsed_ms,
        }
    except (ValueError, LabelingServiceError) as error:
        task_elapsed_ms = (time.perf_counter_ns() - worker_started_ns) / 1_000_000
        return {
            **_error_output(
                row,
                error,
                max_steps=max_steps,
                max_backtracks=max_backtracks,
                terminal_definition_mode=terminal_definition_mode,
                conversion_structured_guard=conversion_structured_guard,
                queue_elapsed_ms=queue_elapsed_ms,
                task_elapsed_ms=task_elapsed_ms,
            ),
            "model": model,
            "prompt_version": PROMPT_VERSION + ("-structured-guard" if conversion_structured_guard else ""),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--teacher-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--report",
        type=Path,
        help="Optional JSON timing report; must not already exist.",
    )
    parser.add_argument("--endpoint", default=os.getenv("ENGLISH_TAGGER_DS_V4_ENDPOINT", DEFAULT_ENDPOINT))
    parser.add_argument("--model", default="ds-v4-flash")
    parser.add_argument("--limit", type=int, required=True)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument("--max-backtracks", type=int, default=2)
    parser.add_argument(
        "--terminal-definition-mode",
        choices=sorted(TERMINAL_DEFINITION_MODES),
        default="compressed",
    )
    parser.add_argument(
        "--conversion-negative-constraint",
        action="store_true",
        help="Apply the versioned no-derived-form rule only when conversion is a terminal choice.",
    )
    parser.add_argument(
        "--conversion-structured-guard",
        action="store_true",
        help="Require an internal task/form/mixed-evidence check before choosing conversion.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument("--api-key-env", default="ENGLISH_TAGGER_DS_V4_API_KEY")
    args = parser.parse_args()

    if args.limit <= 0:
        parser.error("--limit must be positive")
    if not 1 <= args.concurrency <= 128:
        parser.error("--concurrency must be between 1 and 128")
    if args.max_steps <= 0:
        parser.error("--max-steps must be positive")
    if args.max_backtracks < 0:
        parser.error("--max-backtracks must be non-negative")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    if args.output.exists():
        parser.error(f"refusing to overwrite existing output: {args.output}")
    if args.report is not None and args.report.exists():
        parser.error(f"refusing to overwrite existing report: {args.report}")
    if args.report is not None and args.report == args.output:
        parser.error("--report must differ from --output")

    try:
        tree = KnowledgeTaxonomyTree.from_rulebook(load_knowledge_rulebook(args.teacher_csv))
    except (OSError, ValueError) as error:
        parser.error(str(error))
    client = KnowledgeTreeChoiceClient(
        LabelingServiceConfig(
            endpoint=args.endpoint,
            model=args.model,
            timeout_seconds=args.timeout_seconds,
            api_key=os.getenv(args.api_key_env) or None,
        ),
        tree,
        terminal_definition_mode=args.terminal_definition_mode,
        conversion_negative_constraint=args.conversion_negative_constraint,
        conversion_structured_guard=args.conversion_structured_guard,
    )

    queued_rows: list[tuple[int, dict[str, Any], Exception | None]] = []
    with args.input.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if len(queued_rows) >= args.limit:
                break
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
                if not isinstance(parsed, dict):
                    raise ValueError(f"line {line_number}: JSONL row must be an object")
                queued_rows.append((len(queued_rows), parsed, None))
            except (json.JSONDecodeError, ValueError) as error:
                queued_rows.append((len(queued_rows), {}, error))

    results: dict[int, dict[str, Any]] = {}
    batch_started_ns = time.perf_counter_ns()
    futures = {}
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        for index, row, parse_error in queued_rows:
            if parse_error is not None:
                results[index] = _error_output(
                    row,
                    parse_error,
                    max_steps=args.max_steps,
                    max_backtracks=args.max_backtracks,
                    terminal_definition_mode=args.terminal_definition_mode,
                    conversion_structured_guard=args.conversion_structured_guard,
                    task_elapsed_ms=0.0,
                )
                continue
            submitted_ns = time.perf_counter_ns()
            futures[
                executor.submit(
                    _route_one,
                    row,
                    client=client,
                    tree=tree,
                    model=args.model,
                    max_steps=args.max_steps,
                    max_backtracks=args.max_backtracks,
                    terminal_definition_mode=args.terminal_definition_mode,
                    conversion_structured_guard=args.conversion_structured_guard,
                    submitted_ns=submitted_ns,
                )
            ] = index
        for future, index in futures.items():
            results[index] = future.result()
    wall_elapsed_ms = (time.perf_counter_ns() - batch_started_ns) / 1_000_000

    counts: Counter[str] = Counter()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        for index in range(len(queued_rows)):
            row = results[index]
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            counts[str(row["status"])] += 1
    report_path: str | None = None
    if args.report is not None:
        timing_report = summarize_tree_timing(
            (results[index] for index in range(len(queued_rows))),
            wall_elapsed_ms=wall_elapsed_ms,
            concurrency=args.concurrency,
        )
        report = {
            **timing_report,
            "input": str(args.input),
            "output": str(args.output),
            "model": args.model,
            "max_steps": args.max_steps,
            "max_backtracks": args.max_backtracks,
            "terminal_definition_mode": args.terminal_definition_mode,
            "conversion_structured_guard": args.conversion_structured_guard,
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        report_path = str(args.report)
    print(
        json.dumps(
            {
                "input": str(args.input),
                "output": str(args.output),
                "processed": len(queued_rows),
                "status_counts": dict(sorted(counts.items())),
                "model": args.model,
                "concurrency": args.concurrency,
                "wall_elapsed_ms": wall_elapsed_ms,
                "report": report_path,
                "max_steps": args.max_steps,
                "max_backtracks": args.max_backtracks,
                "terminal_definition_mode": args.terminal_definition_mode,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
