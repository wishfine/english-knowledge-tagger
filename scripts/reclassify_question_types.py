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
    SAMPLE_SCHEMA_VERSION,
    QuestionTypeClient,
    QuestionTypeServiceConfig,
    QuestionTypeServiceError,
    build_type_reclassification_sample,
    clean_question_input,
)


DEFAULT_ENDPOINTS = (
    "http://172.22.0.35:9102/v1/chat/completions",
    "http://172.22.0.35:9103/v1/chat/completions",
)
DEFAULT_PROMPT = (
    PROJECT_ROOT / "configs" / "prompts" / "question-major-type-discovery-v2.txt"
)


def _packet_rows(
    path: Path, *, limit: int | None, type_label: str
) -> Iterator[dict[str, Any]]:
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
            if row.get("is_sub_question") is not False:
                raise ValueError(
                    f"sample line {line_number}: only is_sub_question=false is eligible"
                )
            sampled_labels = row.get("sampled_type_labels")
            if not isinstance(sampled_labels, list) or any(
                not isinstance(label, str) or not label for label in sampled_labels
            ):
                raise ValueError(
                    f"sample line {line_number}: sampled_type_labels must be a string array"
                )
            if type_label not in sampled_labels:
                continue
            emitted += 1
            yield row


def _record_key(row: Mapping[str, Any]) -> tuple[Any, Any]:
    return row.get("source_line"), row.get("question_id")


def _completed_record_keys(path: Path) -> set[tuple[Any, Any]]:
    completed: set[tuple[Any, Any]] = set()
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
            if not isinstance(row, Mapping):
                raise ValueError(f"result line {line_number}: invalid result row")
            completed.add(_record_key(row))
    return completed


def _classify_one(
    packet_row: Mapping[str, Any],
    *,
    client: QuestionTypeClient,
) -> dict[str, Any]:
    base = {
        "question_id": packet_row.get("question_id"),
        "source_line": packet_row.get("source_line"),
        "input": clean_question_input(packet_row["input"]),
    }
    try:
        result = client.classify(packet_row["input"])
        return {
            **base,
            "status": "candidate",
            **result.discovery,
        }
    except (QuestionTypeServiceError, ValueError) as error:
        return {
            **base,
            "status": "error",
            "error": str(error),
        }


def _write_report(path: Path | None, report: Mapping[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _summarize_results(path: Path) -> dict[str, Any]:
    status_counts: Counter[str] = Counter()
    candidate_type_counts: Counter[str] = Counter()
    sufficiency_counts: Counter[str] = Counter()
    total_processed = 0
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"result line {line_number}: invalid JSON") from error
            if not isinstance(row, Mapping):
                raise ValueError(f"result line {line_number}: invalid result row")
            total_processed += 1
            status = row.get("status")
            if status not in {"candidate", "error"}:
                raise ValueError(f"result line {line_number}: invalid status")
            status_counts[status] += 1
            if status == "candidate":
                candidate_type = row.get("candidate_type_label")
                sufficiency = row.get("information_sufficiency")
                if isinstance(candidate_type, str) and candidate_type:
                    candidate_type_counts[candidate_type] += 1
                if isinstance(sufficiency, str) and sufficiency:
                    sufficiency_counts[sufficiency] += 1
    return {
        "total_processed": total_processed,
        "candidate": status_counts["candidate"],
        "error": status_counts["error"],
        "candidate_type_counts": dict(sorted(candidate_type_counts.items())),
        "information_sufficiency_counts": dict(sorted(sufficiency_counts.items())),
    }


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
    if not args.type_label.strip():
        parser.error("--type-label must be non-empty")
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
        completed = _completed_record_keys(args.output) if args.resume else set()
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
        source_paths: set[str] = set()
        source_instruction_counts: Counter[str] = Counter()
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
            pending: set[Future[dict[str, Any]]] = set()

            def drain() -> None:
                if not pending:
                    return
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    pending.remove(future)
                    output_row = future.result()
                    output.write(
                        json.dumps(output_row, ensure_ascii=False, sort_keys=True) + "\n"
                    )
                    output.flush()

            submitted = 0
            sample_count = 0
            for packet_row in _packet_rows(
                args.input, limit=args.limit, type_label=args.type_label
            ):
                sample_count += 1
                source_path = packet_row.get("source_path")
                if isinstance(source_path, str) and source_path:
                    source_paths.add(source_path)
                source_instruction = packet_row.get("instruction")
                if isinstance(source_instruction, str) and source_instruction:
                    source_instruction_counts[source_instruction] += 1
                if _record_key(packet_row) in completed:
                    continue
                endpoint_index = submitted % len(endpoints)
                pending.add(
                    executors[endpoint_index].submit(
                        _classify_one,
                        packet_row,
                        client=clients[endpoint_index],
                    )
                )
                submitted += 1
                if len(pending) >= max_pending:
                    drain()
            while pending:
                drain()
        if len(source_paths) > 1:
            raise ValueError("sample contains more than one source_path")
        if sample_count == 0:
            raise ValueError(f"sample contains no records for type label: {args.type_label}")
        result_summary = _summarize_results(args.output)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    report = {
        "schema_version": "question-major-type-discovery-run-report-v2",
        "current_type_label": args.type_label,
        "source_path": next(iter(source_paths), None),
        "source_instructions": [
            {"instruction": instruction, "record_count": count}
            for instruction, count in sorted(source_instruction_counts.items())
        ],
        "sample_path": str(args.input),
        "result_path": str(args.output),
        "classifier_prompt_path": str(args.prompt),
        "model": args.model,
        "endpoints": endpoints,
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": prompt_sha256,
        "stream": True,
        "max_tokens": args.max_tokens,
        "sample_count": sample_count,
        **result_summary,
    }
    _write_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    sample = subparsers.add_parser(
        "sample", help="sample up to N major questions per current type label"
    )
    sample.add_argument("--input", type=Path, required=True)
    sample.add_argument("--output", type=Path, required=True)
    sample.add_argument("--report", type=Path, required=True)
    sample.add_argument("--per-type", type=int, default=1000)
    sample.add_argument("--seed", type=int, default=20260828)
    sample.set_defaults(func=sample_command)

    run = subparsers.add_parser("run", help="discover types for sampled packets with streamed SSE")
    run.add_argument("--input", type=Path, required=True)
    run.add_argument("--type-label", required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--report", type=Path)
    run.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    run.add_argument("--endpoint", action="append")
    run.add_argument("--model", default="DeepSeek-V4-Flash")
    run.add_argument("--per-endpoint-concurrency", type=int, default=15)
    run.add_argument("--timeout-seconds", type=float, default=60.0)
    run.add_argument("--max-tokens", type=int, default=512)
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
