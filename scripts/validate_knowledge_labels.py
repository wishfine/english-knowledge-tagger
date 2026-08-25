#!/usr/bin/env python3
"""Validate historical knowledge labels with DS-V4; output candidates only."""

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

from english_knowledge_tagger.candidate_labeling import LabelingServiceConfig, LabelingServiceError
from english_knowledge_tagger.knowledge_validation import (
    KnowledgeValidationClient,
    KnowledgeValidationRequest,
    ValidationAlternative,
)


DEFAULT_ENDPOINT = "http://172.22.0.35:6636/v1/chat/completions"


def _nonempty_string(row: dict[str, Any], field: str, *, line_number: int) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"line {line_number}: {field} must be a non-empty string")
    return value.strip()


def _alternatives(row: dict[str, Any], *, line_number: int) -> tuple[ValidationAlternative, ...]:
    raw = row.get("alternative_labels")
    if not isinstance(raw, list):
        raise ValueError(f"line {line_number}: alternative_labels must be a list")
    alternatives: list[ValidationAlternative] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"line {line_number}: alternative_labels[{index}] must be an object")
        label = item.get("label")
        definition = item.get("definition")
        if not isinstance(label, str) or not label.strip() or not isinstance(definition, str):
            raise ValueError(
                f"line {line_number}: alternative_labels[{index}] needs non-empty label and string definition"
            )
        alternatives.append(ValidationAlternative(label=label.strip(), definition=definition.strip()))
    return tuple(alternatives)


def _request_from_row(row: dict[str, Any], *, line_number: int) -> KnowledgeValidationRequest:
    candidate_pool = row.get("candidate_pool")
    if not isinstance(candidate_pool, dict) or not isinstance(candidate_pool.get("max_output_labels"), int):
        raise ValueError(f"line {line_number}: candidate_pool.max_output_labels must be an integer")
    return KnowledgeValidationRequest(
        review_id=_nonempty_string(row, "review_id", line_number=line_number),
        question_context=_nonempty_string(row, "question_context", line_number=line_number),
        legacy_label=_nonempty_string(row, "legacy_label", line_number=line_number),
        target_definition=_nonempty_string(row, "target_definition", line_number=line_number),
        alternatives=_alternatives(row, line_number=line_number),
        max_output_labels=candidate_pool["max_output_labels"],
    )


def _base_output(row: dict[str, Any], *, source_path: Path) -> dict[str, Any]:
    context = row.get("question_context") if isinstance(row.get("question_context"), str) else ""
    return {
        "review_id": row.get("review_id"),
        "question_id": row.get("question_id"),
        "parent_id": row.get("parent_id"),
        "is_sub_question": row.get("is_sub_question"),
        "source_line": row.get("source_line"),
        "source_path": str(source_path),
        "input_sha256": hashlib.sha256(context.encode("utf-8")).hexdigest(),
        "legacy_label": row.get("legacy_label"),
        "taxonomy_status": row.get("taxonomy_status"),
        "candidate_pool": row.get("candidate_pool"),
    }


def _candidate_output(base: dict[str, Any], result: Any) -> dict[str, Any]:
    return {
        **base,
        "validation": {
            "verdict": result.verdict,
            "best_label": result.best_label,
            "evidence": result.evidence,
            "reason": result.reason,
            "parse_error": result.error,
        },
        "raw_response": result.raw_response,
        "model": result.model,
        "prompt_version": result.prompt_version,
        "request_id": result.request_id,
        "status": result.status,
    }


def _skipped_output(base: dict[str, Any]) -> dict[str, Any]:
    return {
        **base,
        "validation": {
            "verdict": None,
            "best_label": None,
            "evidence": None,
            "reason": None,
            "parse_error": "taxonomy status is not known",
        },
        "raw_response": "",
        "status": "skipped",
    }


def _error_output(base: dict[str, Any], error: Exception) -> dict[str, Any]:
    return {
        **base,
        "validation": {
            "verdict": None,
            "best_label": None,
            "evidence": None,
            "reason": None,
            "parse_error": str(error),
        },
        "raw_response": "",
        "status": "error",
        "error": str(error),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--endpoint", default=os.getenv("ENGLISH_TAGGER_DS_V4_ENDPOINT", DEFAULT_ENDPOINT)
    )
    parser.add_argument("--model", default="ds-v4-flash")
    parser.add_argument("--limit", type=int, required=True)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument("--api-key-env", default="ENGLISH_TAGGER_DS_V4_API_KEY")
    args = parser.parse_args()

    if args.limit <= 0:
        parser.error("--limit must be positive")
    if args.sleep_seconds < 0:
        parser.error("--sleep-seconds must be non-negative")
    if args.output.exists():
        parser.error(f"refusing to overwrite existing output: {args.output}")

    client = KnowledgeValidationClient(
        LabelingServiceConfig(
            endpoint=args.endpoint,
            model=args.model,
            timeout_seconds=args.timeout_seconds,
            api_key=os.getenv(args.api_key_env) or None,
        )
    )
    processed = 0
    candidates = 0
    skipped = 0
    errors = 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.input.open("r", encoding="utf-8") as source, args.output.open(
        "x", encoding="utf-8"
    ) as output:
        for line_number, line in enumerate(source, 1):
            if processed >= args.limit:
                break
            if not line.strip():
                continue
            row: dict[str, Any] = {}
            try:
                parsed = json.loads(line)
                if not isinstance(parsed, dict):
                    raise ValueError(f"line {line_number}: JSONL row must be an object")
                row = parsed
                base = _base_output(row, source_path=args.input)
                if row.get("taxonomy_status") != "known":
                    result_row = _skipped_output(base)
                    skipped += 1
                else:
                    result = client.validate(_request_from_row(row, line_number=line_number))
                    result_row = _candidate_output(base, result)
                    candidates += 1
            except (ValueError, LabelingServiceError) as error:
                result_row = _error_output(_base_output(row, source_path=args.input), error)
                errors += 1
            output.write(json.dumps(result_row, ensure_ascii=False, sort_keys=True) + "\n")
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
                "skipped": skipped,
                "error": errors,
                "model": args.model,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
