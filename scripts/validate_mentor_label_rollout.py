#!/usr/bin/env python3
"""Run the calibrated mentor-direct-v1 verifier over one full-label packet."""

from __future__ import annotations

import argparse
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterator, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.candidate_labeling import LabelingServiceConfig, LabelingServiceError
from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook
from english_knowledge_tagger.knowledge_taxonomy_migration import load_knowledge_taxonomy_migration
from english_knowledge_tagger.mentor_direct_rollout import (
    MentorDirectClient,
    MentorDirectRequest,
    load_mentor_label_definitions,
    mentor_error_to_evidence,
    mentor_result_to_evidence,
)


DEFAULT_ENDPOINT = "http://172.22.0.35:6636/v1/chat/completions"


def _packet_rows(path: Path, *, limit: int | None) -> Iterator[tuple[int, dict[str, Any]]]:
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
                raise ValueError(f"packet line {line_number}: invalid JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"packet line {line_number}: JSONL row must be an object")
            emitted += 1
            yield line_number, row


def _verify_one(
    packet_row: Mapping[str, Any],
    *,
    client: MentorDirectClient,
    rulebook: Any,
    migration: Any,
    model: str,
) -> tuple[dict[str, Any], str]:
    try:
        result = client.verify(MentorDirectRequest(packet_row=packet_row))
        return (
            mentor_result_to_evidence(
                packet_row, result=result, rulebook=rulebook, migration=migration
            ),
            "candidate",
        )
    except (LabelingServiceError, ValueError) as error:
        return (
            mentor_error_to_evidence(
                packet_row,
                error=error,
                rulebook=rulebook,
                migration=migration,
                model=model,
            ),
            "error",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--label-definitions", type=Path, required=True)
    parser.add_argument("--teacher-csv", type=Path, required=True)
    parser.add_argument("--taxonomy-migration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--endpoint", default=os.getenv("ENGLISH_TAGGER_DS_V4_ENDPOINT", DEFAULT_ENDPOINT)
    )
    parser.add_argument("--model", default="ds-v4-flash")
    parser.add_argument("--concurrency", type=int, default=64)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--allow-full", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--api-key-env", default="ENGLISH_TAGGER_DS_V4_API_KEY")
    args = parser.parse_args()
    if args.output.exists() or (args.report is not None and args.report.exists()):
        parser.error("refusing to overwrite an existing verifier output or report")
    if args.limit is None and not args.allow_full:
        parser.error("full verifier runs require --allow-full; otherwise provide --limit")
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    if not 1 <= args.concurrency <= 128:
        parser.error("--concurrency must be between 1 and 128")
    try:
        rulebook = load_knowledge_rulebook(args.teacher_csv)
        migration = load_knowledge_taxonomy_migration(args.taxonomy_migration)
        client = MentorDirectClient(
            LabelingServiceConfig(
                endpoint=args.endpoint,
                model=args.model,
                timeout_seconds=args.timeout_seconds,
                api_key=os.getenv(args.api_key_env) or None,
            ),
            label_definitions=load_mentor_label_definitions(args.label_definitions),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        processed = 0
        candidate = 0
        error_count = 0
        max_pending = args.concurrency * 4
        with args.output.open("x", encoding="utf-8") as output, ThreadPoolExecutor(
            max_workers=args.concurrency
        ) as pool:
            pending: deque[Future[tuple[dict[str, Any], str]]] = deque()
            for _, packet_row in _packet_rows(args.input, limit=args.limit):
                pending.append(
                    pool.submit(
                        _verify_one,
                        packet_row,
                        client=client,
                        rulebook=rulebook,
                        migration=migration,
                        model=args.model,
                    )
                )
                if len(pending) >= max_pending:
                    output_row, status = pending.popleft().result()
                    output.write(json.dumps(output_row, ensure_ascii=False, sort_keys=True) + "\n")
                    processed += 1
                    candidate += status == "candidate"
                    error_count += status == "error"
            while pending:
                output_row, status = pending.popleft().result()
                output.write(json.dumps(output_row, ensure_ascii=False, sort_keys=True) + "\n")
                processed += 1
                candidate += status == "candidate"
                error_count += status == "error"
    except (OSError, ValueError) as failure:
        parser.error(str(failure))
    report = {
        "schema_version": "mentor-label-rollout-verdict-report-v1",
        "input": str(args.input),
        "output": str(args.output),
        "model": args.model,
        "prompt_version": "mentor-direct-v1",
        "concurrency": args.concurrency,
        "processed": processed,
        "candidate": candidate,
        "error": error_count,
    }
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
