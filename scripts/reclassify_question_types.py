#!/usr/bin/env python3
"""Sample legacy type categories and discover candidate types with streamed DS responses."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterator, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.type_reclassification import (
    PROMPT_VERSION,
    RESULT_SCHEMA_VERSION,
    SAMPLE_SCHEMA_VERSION,
    QuestionTypeClient,
    QuestionTypeServiceConfig,
    QuestionTypeServiceError,
    build_type_reclassification_sample,
)


DEFAULT_ENDPOINTS = (
    "http://172.22.0.35:9102/v1/chat/completions",
    "http://172.22.0.35:9103/v1/chat/completions",
)
DEFAULT_PROMPT = PROJECT_ROOT / "configs" / "prompts" / "question-type-discovery-v1.txt"


def _packet_rows(path: Path, *, limit: int | None) -> Iterator[dict[str, Any]]:
    emitted = 0
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if limit is not None and emitted >= limit:
                return
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"sample line {line_number}: invalid JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"sample line {line_number}: JSONL row must be an object")
            if row.get("schema_version") != SAMPLE_SCHEMA_VERSION:
                raise ValueError(f"sample line {line_number}: unexpected schema_version")
            if not isinstance(row.get("review_id"), str) or not row["review_id"].strip():
                raise ValueError(f"sample line {line_number}: review_id must be non-empty")
            if not isinstance(row.get("input"), str):
                raise ValueError(f"sample line {line_number}: input must be a string")
            emitted += 1
            yield row


def _completed_review_ids(path: Path) -> set[str]:
    completed: set[str] = set()
    if not path.exists():
        return completed
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"result line {line_number}: invalid JSON") from error
            if not isinstance(row, Mapping) or not isinstance(row.get("review_id"), str):
                raise ValueError(f"result line {line_number}: invalid result row")
            completed.add(row["review_id"])
    return completed


def _classify_one(
    packet_row: Mapping[str, Any],
    *,
    client: QuestionTypeClient,
    endpoint: str,
    prompt_sha256: str,
) -> tuple[dict[str, Any], str]:
    base = {
        **packet_row,
        "schema_version": RESULT_SCHEMA_VERSION,
        "endpoint": endpoint,
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": prompt_sha256,
    }
    try:
        result = client.classify(packet_row["input"])
        return (
            {
                **base,
                "status": "candidate",
                **result.discovery,
                "raw_response": result.raw_response,
                "request_id": result.request_id,
                "model": result.model,
            },
            "candidate",
        )
    except (QuestionTypeServiceError, ValueError) as error:
        return (
            {
                **base,
                "status": "error",
                "candidate_type_label": None,
                "error": str(error),
            },
            "error",
        )


def _write_report(path: Path | None, report: Mapping[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sample_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.report.exists():
        parser.error("refusing to overwrite an existing sample report")
    try:
        report = build_type_reclassification_sample(
            args.input,
            output_path=args.output,
            per_type=args.per_type,
            seed=args.seed,
        )
        _write_report(args.report, report)
    except (FileExistsError, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


def run_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.limit is None and not args.allow_full:
        parser.error("full classifier runs require --allow-full; otherwise provide --limit")
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    if not 1 <= args.per_endpoint_concurrency <= 64:
        parser.error("--per-endpoint-concurrency must be between 1 and 64")
    if args.max_retries <= 0:
        parser.error("--max-retries must be positive")
    if args.max_tokens <= 0:
        parser.error("--max-tokens must be positive")
    if args.output.exists() and not args.resume:
        parser.error("result output already exists; use --resume to continue it")
    if args.report is not None and args.report.exists() and not args.resume:
        parser.error("result report already exists; use --resume to replace its summary")

    endpoints = args.endpoint or list(DEFAULT_ENDPOINTS)
    if not all(isinstance(endpoint, str) and endpoint.strip() for endpoint in endpoints):
        parser.error("--endpoint values must be non-empty")
    try:
        base_prompt = args.prompt.read_text(encoding="utf-8")
        if not base_prompt.strip():
            raise ValueError("classifier prompt must be non-empty")
        prompt_sha256 = hashlib.sha256(base_prompt.encode("utf-8")).hexdigest()
        completed = _completed_review_ids(args.output) if args.resume else set()
        clients = [
            QuestionTypeClient(
                QuestionTypeServiceConfig(
                    endpoint=endpoint,
                    model=args.model,
                    max_tokens=args.max_tokens,
                    temperature=0,
                    timeout_seconds=args.timeout_seconds,
                    api_key=os.getenv(args.api_key_env) or None,
                ),
                base_prompt=base_prompt,
                max_retries=args.max_retries,
            )
            for endpoint in endpoints
        ]

        args.output.parent.mkdir(parents=True, exist_ok=True)
        counters: Counter[str] = Counter()
        candidate_type_counts: Counter[str] = Counter()
        total_workers = len(endpoints) * args.per_endpoint_concurrency
        max_pending = total_workers * 4
        mode = "a" if args.resume else "x"
        with args.output.open(mode, encoding="utf-8") as output, ExitStack() as stack:
            executors = [
                stack.enter_context(
                    ThreadPoolExecutor(max_workers=args.per_endpoint_concurrency)
                )
                for _ in endpoints
            ]
            pending: set[Future[tuple[dict[str, Any], str]]] = set()

            def drain() -> None:
                if not pending:
                    return
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    pending.remove(future)
                    output_row, status = future.result()
                    output.write(
                        json.dumps(output_row, ensure_ascii=False, sort_keys=True) + "\n"
                    )
                    output.flush()
                    counters[status] += 1
                    if status == "candidate":
                        candidate_type_counts[output_row["candidate_type_label"]] += 1

            submitted = 0
            for packet_row in _packet_rows(args.input, limit=args.limit):
                if packet_row["review_id"] in completed:
                    counters["skipped_completed"] += 1
                    continue
                endpoint_index = submitted % len(endpoints)
                pending.add(
                    executors[endpoint_index].submit(
                        _classify_one,
                        packet_row,
                        client=clients[endpoint_index],
                        endpoint=endpoints[endpoint_index],
                        prompt_sha256=prompt_sha256,
                    )
                )
                submitted += 1
                if len(pending) >= max_pending:
                    drain()
            while pending:
                drain()
    except (OSError, ValueError) as error:
        parser.error(str(error))

    report = {
        "schema_version": "question-type-discovery-run-report-v1",
        "input_path": str(args.input),
        "output_path": str(args.output),
        "prompt_path": str(args.prompt),
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": prompt_sha256,
        "model": args.model,
        "endpoints": endpoints,
        "stream": True,
        "per_endpoint_concurrency": args.per_endpoint_concurrency,
        "total_concurrency": len(endpoints) * args.per_endpoint_concurrency,
        "submitted": submitted,
        "candidate": counters["candidate"],
        "error": counters["error"],
        "skipped_completed": counters["skipped_completed"],
        "candidate_type_counts": dict(sorted(candidate_type_counts.items())),
    }
    _write_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    sample = subparsers.add_parser("sample", help="sample up to N rows per current type label")
    sample.add_argument("--input", type=Path, required=True)
    sample.add_argument("--output", type=Path, required=True)
    sample.add_argument("--report", type=Path, required=True)
    sample.add_argument("--per-type", type=int, default=1000)
    sample.add_argument("--seed", type=int, default=20260828)
    sample.set_defaults(func=sample_command)

    run = subparsers.add_parser("run", help="discover types for sampled packets with streamed SSE")
    run.add_argument("--input", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--report", type=Path)
    run.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    run.add_argument("--endpoint", action="append")
    run.add_argument("--model", default="DeepSeek-V4-Flash")
    run.add_argument("--per-endpoint-concurrency", type=int, default=15)
    run.add_argument("--timeout-seconds", type=float, default=60.0)
    run.add_argument("--max-tokens", type=int, default=1024)
    run.add_argument("--max-retries", type=int, default=3)
    run.add_argument("--api-key-env", default="ENGLISH_TAGGER_DS_V4_API_KEY")
    run.add_argument("--limit", type=int)
    run.add_argument("--allow-full", action="store_true")
    run.add_argument("--resume", action="store_true")
    run.set_defaults(func=run_command)

    args = parser.parse_args()
    args.func(args, parser)


if __name__ == "__main__":
    main()
