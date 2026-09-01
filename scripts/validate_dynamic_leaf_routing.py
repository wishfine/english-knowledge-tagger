#!/usr/bin/env python3
"""Run one repeat of sibling-only or dynamic hybrid leaf correction."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.candidate_labeling import LabelingServiceConfig
from english_knowledge_tagger.dynamic_leaf_routing import (
    DynamicLeafChoiceClient,
    build_dynamic_leaf_neighborhood,
    resolve_dynamic_leaf,
    search_dynamic_tree_candidate,
)
from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook
from english_knowledge_tagger.knowledge_taxonomy_tree import KnowledgeTaxonomyTree
from english_knowledge_tagger.knowledge_tree_choice import KnowledgeTreeChoiceClient


DEFAULT_ENDPOINT = "http://172.22.0.35:9102/v1/chat/completions"


def _load(path: Path, *, limit: int | None):
    rows = []
    seen = set()
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if limit is not None and len(rows) >= limit:
                break
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"input line {line_number}: invalid JSON") from error
            if not isinstance(row, dict) or row.get("schema_version") != "dynamic-leaf-task-v1":
                raise ValueError(f"input line {line_number}: unexpected schema_version")
            review_id = row.get("review_id")
            if not isinstance(review_id, str) or not review_id.strip() or review_id in seen:
                raise ValueError(f"input line {line_number}: invalid or duplicate review_id")
            seen.add(review_id)
            rows.append(row)
    return rows


def _endpoint_index(row: Mapping[str, object], *, run_name: str, count: int) -> int:
    digest = hashlib.sha256(
        f"{run_name}|{row.get('question_id')}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "big") % count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--teacher-csv", type=Path, required=True)
    parser.add_argument("--definition-overrides", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--endpoint", action="append")
    parser.add_argument("--model", default="DeepSeek-V4-Flash")
    parser.add_argument("--mode", choices=("siblings", "dynamic"), required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--page-size", type=int, default=4)
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument("--max-backtracks", type=int, default=2)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--api-key-env", default="ENGLISH_TAGGER_DS_V4_API_KEY")
    args = parser.parse_args()
    if args.output == args.report or args.output.exists() or args.report.exists():
        parser.error("refusing invalid or existing output paths")
    if args.page_size <= 0 or args.max_steps <= 0 or args.max_backtracks < 0:
        parser.error("routing budgets are invalid")
    if not 1 <= args.concurrency <= 128:
        parser.error("--concurrency must be between 1 and 128")
    endpoints = args.endpoint or [
        os.getenv("ENGLISH_TAGGER_DS_V4_ENDPOINT", DEFAULT_ENDPOINT)
    ]
    try:
        tasks = _load(args.input, limit=args.limit)
        rulebook = load_knowledge_rulebook(
            args.teacher_csv, overrides_path=args.definition_overrides
        )
        tree = KnowledgeTaxonomyTree.from_rulebook(rulebook)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    configs = [
        LabelingServiceConfig(
            endpoint=endpoint,
            model=args.model,
            timeout_seconds=args.timeout_seconds,
            api_key=os.getenv(args.api_key_env) or None,
        )
        for endpoint in endpoints
    ]
    leaf_clients = [DynamicLeafChoiceClient(config) for config in configs]
    branch_clients = [
        KnowledgeTreeChoiceClient(config, tree, enable_thinking=False) for config in configs
    ]

    def one(task):
        index = _endpoint_index(task, run_name=args.run_name, count=len(endpoints))
        question = task.get("question_text")
        target = task.get("historical_label")
        if not isinstance(question, str) or not isinstance(target, str):
            return {
                "schema_version": "dynamic-leaf-routing-evidence-v1",
                "review_id": task.get("review_id"),
                "question_id": task.get("question_id"),
                "status": "error",
                "error": "task question_text and historical_label must be strings",
                "run_name": args.run_name,
                "mode": args.mode,
            }
        try:
            if args.mode == "siblings":
                neighborhood = build_dynamic_leaf_neighborhood(
                    rulebook,
                    target_label=target,
                    question_text=question,
                    confusion_counts={},
                    soft_route_compatible=set(),
                    hard_excluded=frozenset(task.get("hard_excluded") or ()),
                    include_escape_candidates=False,
                )
                result = resolve_dynamic_leaf(
                    neighborhood,
                    choose=lambda page: leaf_clients[index].choose(
                        page, question_text=question
                    ),
                    page_size=args.page_size,
                    max_pages=args.max_steps,
                )
            else:
                raw_confusions = task.get("confusion_counts") or {}
                if not isinstance(raw_confusions, dict):
                    raise ValueError("task confusion_counts must be an object")
                result = search_dynamic_tree_candidate(
                    tree,
                    rulebook=rulebook,
                    target_label=target,
                    question_text=question,
                    confusion_counts={str(k): int(v) for k, v in raw_confusions.items()},
                    soft_route_compatible=set(task.get("soft_route_compatible") or ()),
                    hard_excluded=frozenset(task.get("hard_excluded") or ()),
                    choose_branch=branch_clients[index].choose,
                    choose_leaf=lambda page: leaf_clients[index].choose(
                        page, question_text=question
                    ),
                    page_size=args.page_size,
                    max_steps=args.max_steps,
                    max_backtracks=args.max_backtracks,
                )
            return {
                "schema_version": "dynamic-leaf-routing-evidence-v1",
                "review_id": task.get("review_id"),
                "question_id": task.get("question_id"),
                "parent_id": task.get("parent_id"),
                "historical_label": target,
                "status": result.status,
                "candidate_label": result.candidate_label,
                "trace": list(result.trace),
                "call_count": len(result.trace),
                "run_name": args.run_name,
                "mode": args.mode,
                "endpoint": endpoints[index],
                "model": args.model,
                "enable_thinking": False,
            }
        except (OSError, RuntimeError, ValueError) as error:
            return {
                "schema_version": "dynamic-leaf-routing-evidence-v1",
                "review_id": task.get("review_id"),
                "question_id": task.get("question_id"),
                "status": "error",
                "error": str(error),
                "run_name": args.run_name,
                "mode": args.mode,
                "endpoint": endpoints[index],
            }

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(one, tasks))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        for row in results:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    calls = [row["call_count"] for row in results if isinstance(row.get("call_count"), int)]
    report = {
        "schema_version": "dynamic-leaf-routing-run-report-v1",
        "input": str(args.input),
        "output": str(args.output),
        "run_name": args.run_name,
        "mode": args.mode,
        "processed": len(results),
        "status_counts": dict(sorted(Counter(row["status"] for row in results).items())),
        "mean_call_count": sum(calls) / len(calls) if calls else None,
        "endpoints": endpoints,
        "model": args.model,
        "enable_thinking": False,
        "page_size": args.page_size,
        "max_steps": args.max_steps,
        "max_backtracks": args.max_backtracks,
        "concurrency": args.concurrency,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
