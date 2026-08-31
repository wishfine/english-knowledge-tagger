#!/usr/bin/env python3
"""Run the conversion target gate over a label-blind conversion packet."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.candidate_labeling import LabelingServiceConfig, LabelingServiceError
from english_knowledge_tagger.conversion_gate import ConversionGateClient, PROMPT_VERSION


DEFAULT_ENDPOINT = "http://172.22.0.35:9102/v1/chat/completions"
PACKET_SCHEMA_VERSION = "conversion-relation-packet-v1"


def _load_rows(path: Path, *, limit: int | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
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
            if not isinstance(row, dict):
                raise ValueError(f"input line {line_number}: JSONL row must be an object")
            if row.get("schema_version") != PACKET_SCHEMA_VERSION:
                raise ValueError(
                    f"input line {line_number}: schema_version must be {PACKET_SCHEMA_VERSION!r}"
                )
            rows.append(row)
    return rows


def _evidence_row(
    task: Mapping[str, Any],
    *,
    endpoint: str,
    model: str,
    result: Any | None = None,
    error: Exception | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "schema_version": "conversion-gate-evidence-v1",
        "task_id": task.get("task_id"),
        "source_line": task.get("source_line"),
        "question_id": task.get("question_id"),
        "parent_id": task.get("parent_id"),
        "route_key": task.get("route_key"),
        "endpoint": endpoint,
        "model": model,
        "prompt_version": PROMPT_VERSION,
    }
    if error is not None:
        row.update({"status": "error", "error": str(error)})
        return row
    row.update(
        {
            "status": "candidate",
            "decision": result.decision,
            "confidence": result.confidence,
            "source_forms": list(result.source_forms),
            "target_forms": list(result.target_forms),
            "form_unchanged": result.form_unchanged,
            "pos_or_function_changed": result.pos_or_function_changed,
            "answer_depends_on_relation": result.answer_depends_on_relation,
            "evidence": result.evidence,
            "raw_response": result.raw_response,
            "elapsed_ms": result.elapsed_ms,
            "prompt_chars": result.prompt_chars,
        }
    )
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--endpoint", action="append")
    parser.add_argument("--model", default="DeepSeek-V4-Flash")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--api-key-env", default="ENGLISH_TAGGER_DS_V4_API_KEY")
    args = parser.parse_args()

    if args.output.exists() or args.report.exists():
        parser.error("refusing to overwrite an existing output or report")
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    if not 1 <= args.concurrency <= 128:
        parser.error("--concurrency must be between 1 and 128")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")

    endpoints = args.endpoint or [
        os.getenv("ENGLISH_TAGGER_DS_V4_ENDPOINT", DEFAULT_ENDPOINT)
    ]
    if not all(isinstance(endpoint, str) and endpoint.strip() for endpoint in endpoints):
        parser.error("--endpoint values must be non-empty")

    try:
        tasks = _load_rows(args.input, limit=args.limit)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    clients = [
        ConversionGateClient(
            LabelingServiceConfig(
                endpoint=endpoint,
                model=args.model,
                timeout_seconds=args.timeout_seconds,
                api_key=os.getenv(args.api_key_env) or None,
            )
        )
        for endpoint in endpoints
    ]

    def one(index_task: tuple[int, Mapping[str, Any]]) -> dict[str, Any]:
        index, task = index_task
        endpoint = endpoints[index % len(endpoints)]
        client = clients[index % len(clients)]
        try:
            result = client.classify(task)
            return _evidence_row(task, endpoint=endpoint, model=args.model, result=result)
        except (LabelingServiceError, ValueError) as error:
            return _evidence_row(task, endpoint=endpoint, model=args.model, error=error)

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(one, enumerate(tasks)))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        for row in results:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    status_counts = Counter(row.get("status", "missing") for row in results)
    decision_counts = Counter(
        row.get("decision", "missing") for row in results if row.get("status") == "candidate"
    )
    confidence_counts = Counter(
        row.get("confidence", "missing") for row in results if row.get("status") == "candidate"
    )
    report = {
        "schema_version": "conversion-gate-report-v1",
        "input": str(args.input),
        "output": str(args.output),
        "model": args.model,
        "endpoints": endpoints,
        "prompt_version": PROMPT_VERSION,
        "concurrency": args.concurrency,
        "processed": len(results),
        "status_counts": dict(sorted(status_counts.items())),
        "decision_counts": dict(sorted(decision_counts.items())),
        "confidence_counts": dict(sorted(confidence_counts.items())),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
