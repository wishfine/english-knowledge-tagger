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
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.candidate_labeling import LabelingServiceConfig, LabelingServiceError
from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook
from english_knowledge_tagger.knowledge_taxonomy_tree import KnowledgeTaxonomyTree
from english_knowledge_tagger.knowledge_tree_choice import (
    PROMPT_VERSION,
    KnowledgeTreeChoiceClient,
)
from english_knowledge_tagger.knowledge_tree_tasks import (
    RESULT_SCHEMA_VERSION,
    route_knowledge_tree_task,
)


DEFAULT_ENDPOINT = "http://172.22.0.35:6636/v1/chat/completions"


def _error_output(row: dict[str, Any], error: Exception, *, max_steps: int, max_backtracks: int) -> dict[str, Any]:
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
) -> dict[str, Any]:
    try:
        result = route_knowledge_tree_task(
            row,
            client=client,
            tree=tree,
            max_steps=max_steps,
            max_backtracks=max_backtracks,
        )
        return {**result, "model": model, "prompt_version": PROMPT_VERSION}
    except (ValueError, LabelingServiceError) as error:
        return {
            **_error_output(row, error, max_steps=max_steps, max_backtracks=max_backtracks),
            "model": model,
            "prompt_version": PROMPT_VERSION,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--teacher-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--endpoint", default=os.getenv("ENGLISH_TAGGER_DS_V4_ENDPOINT", DEFAULT_ENDPOINT))
    parser.add_argument("--model", default="ds-v4-flash")
    parser.add_argument("--limit", type=int, required=True)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument("--max-backtracks", type=int, default=2)
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
    futures = {}
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        for index, row, parse_error in queued_rows:
            if parse_error is not None:
                results[index] = _error_output(
                    row,
                    parse_error,
                    max_steps=args.max_steps,
                    max_backtracks=args.max_backtracks,
                )
                continue
            futures[
                executor.submit(
                    _route_one,
                    row,
                    client=client,
                    tree=tree,
                    model=args.model,
                    max_steps=args.max_steps,
                    max_backtracks=args.max_backtracks,
                )
            ] = index
        for future, index in futures.items():
            results[index] = future.result()

    counts: Counter[str] = Counter()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        for index in range(len(queued_rows)):
            row = results[index]
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            counts[str(row["status"])] += 1
    print(
        json.dumps(
            {
                "input": str(args.input),
                "output": str(args.output),
                "processed": len(queued_rows),
                "status_counts": dict(sorted(counts.items())),
                "model": args.model,
                "concurrency": args.concurrency,
                "max_steps": args.max_steps,
                "max_backtracks": args.max_backtracks,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
