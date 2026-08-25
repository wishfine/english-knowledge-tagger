#!/usr/bin/env python3
"""Call the internal DS-V4 service for review candidates; never mutates source JSONL."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.candidate_labeling import (
    CandidateLabelClient,
    LabelingRequest,
    LabelingServiceConfig,
    LabelingServiceError,
)


DEFAULT_ENDPOINT = "http://172.22.0.35:6636/v1/chat/completions"


def _nonempty_string(row: dict[str, Any], field: str, *, line_number: int) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"line {line_number}: {field} must be a non-empty string")
    return value


def _candidate_row(source: dict[str, Any], result: Any, *, source_path: Path) -> dict[str, Any]:
    return {
        "question_id": source.get("question_id"),
        "parent_id": source.get("parent_id"),
        "is_sub_question": source.get("is_sub_question"),
        "source_path": str(source_path),
        "input_sha256": hashlib.sha256(
            str(source.get("input", "")).encode("utf-8")
        ).hexdigest(),
        "original_output": source.get("output"),
        "candidate_labels": list(result.labels),
        "raw_response": result.raw_response,
        "unparsed_fragments": list(result.unparsed_fragments),
        "model": result.model,
        "prompt_version": result.prompt_version,
        "request_id": result.request_id,
        "status": result.status,
    }


def _error_row(source: dict[str, Any], error: Exception, *, source_path: Path) -> dict[str, Any]:
    return {
        "question_id": source.get("question_id"),
        "parent_id": source.get("parent_id"),
        "is_sub_question": source.get("is_sub_question"),
        "source_path": str(source_path),
        "input_sha256": hashlib.sha256(
            str(source.get("input", "")).encode("utf-8")
        ).hexdigest(),
        "original_output": source.get("output"),
        "candidate_labels": [],
        "raw_response": "",
        "unparsed_fragments": [],
        "status": "error",
        "error": str(error),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="review-packet JSONL; never modified")
    parser.add_argument("--output", type=Path, required=True, help="new candidate JSONL destination")
    parser.add_argument(
        "--endpoint",
        default=os.getenv("ENGLISH_TAGGER_DS_V4_ENDPOINT", DEFAULT_ENDPOINT),
        help="OpenAI-compatible /v1/chat/completions endpoint",
    )
    parser.add_argument("--model", default="ds-v4-flash")
    parser.add_argument("--content-field", default="input")
    parser.add_argument("--candidate-definitions-field", default="candidate_definitions")
    parser.add_argument("--limit", type=int, required=True, help="explicit batch size; protects against full-dataset calls")
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument("--api-key-env", default="ENGLISH_TAGGER_DS_V4_API_KEY")
    args = parser.parse_args()

    if args.limit <= 0:
        parser.error("--limit must be positive")
    if args.output.exists():
        parser.error(f"refusing to overwrite existing output: {args.output}")
    if args.sleep_seconds < 0:
        parser.error("--sleep-seconds must be non-negative")

    client = CandidateLabelClient(
        LabelingServiceConfig(
            endpoint=args.endpoint,
            model=args.model,
            timeout_seconds=args.timeout_seconds,
            api_key=os.getenv(args.api_key_env) or None,
        )
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    processed = 0
    candidates = 0
    errors = 0
    with args.input.open("r", encoding="utf-8") as source, args.output.open(
        "x", encoding="utf-8"
    ) as destination:
        for line_number, line in enumerate(source, start=1):
            if processed >= args.limit:
                break
            if not line.strip():
                continue
            row: dict[str, Any] = {}
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"line {line_number}: JSONL row must be an object")
                question_context = _nonempty_string(row, args.content_field, line_number=line_number)
                question_id = _nonempty_string(row, "question_id", line_number=line_number)
                definitions = row.get(args.candidate_definitions_field)
                if definitions is not None and not isinstance(definitions, str):
                    raise ValueError(
                        f"line {line_number}: {args.candidate_definitions_field} must be a string when provided"
                    )
                result = client.label(
                    LabelingRequest(
                        review_id=question_id,
                        question_context=question_context,
                        candidate_definitions=definitions,
                    )
                )
                output_row = _candidate_row(row, result, source_path=args.input)
                candidates += 1
            except (ValueError, LabelingServiceError) as error:
                output_row = _error_row(row, error, source_path=args.input)
                errors += 1
            destination.write(json.dumps(output_row, ensure_ascii=False, sort_keys=True) + "\n")
            processed += 1
            if args.sleep_seconds:
                time.sleep(args.sleep_seconds)

    print(
        json.dumps(
            {
                "input": str(args.input),
                "output": str(args.output),
                "processed": processed,
                "candidate": candidates,
                "error": errors,
                "model": args.model,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
