#!/usr/bin/env python3
"""Validate historical knowledge labels with DS-V4; output candidates only."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
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
from english_knowledge_tagger.knowledge_validation_timing import summarize_validation_timing


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
    target_is_type_allowed = row.get("target_is_type_allowed", True)
    if not isinstance(target_is_type_allowed, bool):
        raise ValueError(f"line {line_number}: target_is_type_allowed must be a boolean")
    return KnowledgeValidationRequest(
        review_id=_nonempty_string(row, "review_id", line_number=line_number),
        question_context=_nonempty_string(row, "question_context", line_number=line_number),
        legacy_label=_nonempty_string(
            row,
            "canonical_label" if row.get("canonical_label") is not None else "legacy_label",
            line_number=line_number,
        ),
        target_definition=_nonempty_string(row, "target_definition", line_number=line_number),
        alternatives=_alternatives(row, line_number=line_number),
        max_output_labels=candidate_pool["max_output_labels"],
        target_is_type_allowed=target_is_type_allowed,
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
        "canonical_label": row.get("canonical_label", row.get("legacy_label")),
        "taxonomy_mapping": row.get("taxonomy_mapping"),
        "taxonomy_status": row.get("taxonomy_status"),
        "candidate_pool": row.get("candidate_pool"),
        "target_is_type_allowed": row.get("target_is_type_allowed", True),
        "knowledge_policy": row.get("knowledge_policy", "unresolved"),
        "validation_action": row.get("validation_action", "validate_with_model"),
    }


def _candidate_output(base: dict[str, Any], result: Any) -> dict[str, Any]:
    return {
        **base,
        "validation": {
            "verdict": result.verdict,
            "candidate_coverage": result.candidate_coverage,
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


def _skipped_output(
    base: dict[str, Any],
    *,
    reason: str,
    recommended_final_knowledge_labels: list[str] | None,
) -> dict[str, Any]:
    return {
        **base,
        "validation": {
            "verdict": None,
            "candidate_coverage": None,
            "best_label": None,
            "evidence": None,
            "reason": None,
            "parse_error": reason,
        },
        "raw_response": "",
        "status": "skipped",
        "skip_reason": reason,
        "recommended_final_knowledge_labels": recommended_final_knowledge_labels,
    }


def _error_output(base: dict[str, Any], error: Exception) -> dict[str, Any]:
    return {
        **base,
        "validation": {
            "verdict": None,
            "candidate_coverage": None,
            "best_label": None,
            "evidence": None,
            "reason": None,
            "parse_error": str(error),
        },
        "raw_response": "",
        "status": "error",
        "error": str(error),
    }


def _with_timing(
    result: dict[str, Any], *, queue_elapsed_ms: float | None, task_elapsed_ms: float
) -> dict[str, Any]:
    """Attach uniform worker measurements without changing any validation verdict."""
    return {
        **result,
        "queue_elapsed_ms": queue_elapsed_ms,
        "task_elapsed_ms": task_elapsed_ms,
        "model_call_elapsed_ms": result.get("model_call_elapsed_ms"),
        "prompt_chars": result.get("prompt_chars"),
        "response_chars": result.get("response_chars"),
    }


def _validate_row(
    client: KnowledgeValidationClient,
    row: dict[str, Any],
    *,
    line_number: int,
    source_path: Path,
    sleep_seconds: float,
    submitted_ns: int,
) -> tuple[dict[str, Any], str]:
    """Validate one row in a worker and return an output row plus its outcome class."""
    worker_started_ns = time.perf_counter_ns()
    queue_elapsed_ms = (worker_started_ns - submitted_ns) / 1_000_000
    base = _base_output(row, source_path=source_path)
    output: dict[str, Any]
    outcome: str
    try:
        if row.get("validation_action") == "skip_policy_forbidden":
            output = _skipped_output(
                base,
                reason="policy_forbidden",
                recommended_final_knowledge_labels=[],
            )
            outcome = "skipped"
        elif row.get("validation_action") == "skip_policy_unresolved":
            output = _skipped_output(
                base,
                reason="policy_unresolved",
                recommended_final_knowledge_labels=None,
            )
            outcome = "skipped"
        elif row.get("taxonomy_status") != "known":
            output = _skipped_output(
                base,
                reason="taxonomy_status_not_known",
                recommended_final_knowledge_labels=None,
            )
            outcome = "skipped"
        else:
            result = client.validate(_request_from_row(row, line_number=line_number))
            output = _candidate_output(base, result)
            output.update(
                {
                    "model_call_elapsed_ms": result.model_call_elapsed_ms,
                    "prompt_chars": result.prompt_chars,
                    "response_chars": result.response_chars,
                }
            )
            outcome = "candidate"
    except (ValueError, LabelingServiceError) as error:
        output = _error_output(base, error)
        outcome = "error"
    finally:
        if sleep_seconds:
            time.sleep(sleep_seconds)
    task_elapsed_ms = (time.perf_counter_ns() - worker_started_ns) / 1_000_000
    return (
        _with_timing(
            output,
            queue_elapsed_ms=queue_elapsed_ms,
            task_elapsed_ms=task_elapsed_ms,
        ),
        outcome,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, help="Optional JSON timing report; must not already exist.")
    parser.add_argument(
        "--endpoint", default=os.getenv("ENGLISH_TAGGER_DS_V4_ENDPOINT", DEFAULT_ENDPOINT)
    )
    parser.add_argument("--model", default="ds-v4-flash")
    parser.add_argument("--limit", type=int, required=True)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument("--api-key-env", default="ENGLISH_TAGGER_DS_V4_API_KEY")
    args = parser.parse_args()

    if args.limit <= 0:
        parser.error("--limit must be positive")
    if not 1 <= args.concurrency <= 128:
        parser.error("--concurrency must be between 1 and 128")
    if args.sleep_seconds < 0:
        parser.error("--sleep-seconds must be non-negative")
    if args.concurrency > 1 and args.sleep_seconds:
        parser.error("--sleep-seconds must be 0 when --concurrency is greater than 1")
    if args.output.exists():
        parser.error(f"refusing to overwrite existing output: {args.output}")
    if args.report is not None and args.report.exists():
        parser.error(f"refusing to overwrite existing report: {args.report}")
    if args.report is not None and args.report == args.output:
        parser.error("--report must differ from --output")

    client = KnowledgeValidationClient(
        LabelingServiceConfig(
            endpoint=args.endpoint,
            model=args.model,
            timeout_seconds=args.timeout_seconds,
            api_key=os.getenv(args.api_key_env) or None,
        )
    )
    queued_rows: list[tuple[int, int, dict[str, Any], Exception | None]] = []
    with args.input.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if len(queued_rows) >= args.limit:
                break
            if not line.strip():
                continue
            row: dict[str, Any] = {}
            error: Exception | None = None
            try:
                parsed = json.loads(line)
                if not isinstance(parsed, dict):
                    raise ValueError(f"line {line_number}: JSONL row must be an object")
                row = parsed
            except (json.JSONDecodeError, ValueError) as caught:
                error = caught
            queued_rows.append((len(queued_rows), line_number, row, error))

    processed = len(queued_rows)
    candidates = 0
    skipped = 0
    errors = 0
    results: dict[int, tuple[dict[str, Any], str]] = {}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    batch_started_ns = time.perf_counter_ns()
    futures = {}
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        for index, line_number, row, parse_error in queued_rows:
            if parse_error is not None:
                results[index] = (
                    _with_timing(
                        _error_output(_base_output(row, source_path=args.input), parse_error),
                        queue_elapsed_ms=None,
                        task_elapsed_ms=0.0,
                    ),
                    "error",
                )
                continue
            submitted_ns = time.perf_counter_ns()
            futures[
                executor.submit(
                    _validate_row,
                    client,
                    row,
                    line_number=line_number,
                    source_path=args.input,
                    sleep_seconds=args.sleep_seconds,
                    submitted_ns=submitted_ns,
                )
            ] = index
        for future, index in futures.items():
            results[index] = future.result()
    wall_elapsed_ms = (time.perf_counter_ns() - batch_started_ns) / 1_000_000

    with args.output.open("x", encoding="utf-8") as output:
        for index in range(processed):
            result_row, outcome = results[index]
            output.write(json.dumps(result_row, ensure_ascii=False, sort_keys=True) + "\n")
            if outcome == "candidate":
                candidates += 1
            elif outcome == "skipped":
                skipped += 1
            else:
                errors += 1

    report_path: str | None = None
    if args.report is not None:
        timing_report = summarize_validation_timing(
            (results[index][0] for index in range(processed)),
            wall_elapsed_ms=wall_elapsed_ms,
            concurrency=args.concurrency,
        )
        report = {
            **timing_report,
            "input": str(args.input),
            "output": str(args.output),
            "model": args.model,
            "limit": args.limit,
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
                "processed": processed,
                "candidate": candidates,
                "skipped": skipped,
                "error": errors,
                "model": args.model,
                "concurrency": args.concurrency,
                "wall_elapsed_ms": wall_elapsed_ms,
                "report": report_path,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
