#!/usr/bin/env python3
"""Run one repeat of the experimental three-way terminal-label discriminator."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.candidate_labeling import (
    LabelingServiceConfig,
    LabelingServiceError,
)
from english_knowledge_tagger.terminal_label_stability import (
    EVIDENCE_SCHEMA_VERSION,
    PACKET_SCHEMA_VERSION,
    PROMPT_VERSION,
    TerminalLabelStabilityClient,
)


DEFAULT_ENDPOINT = "http://172.22.0.35:9102/v1/chat/completions"


def _load_rows(path: Path, *, limit: int | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
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
            if not isinstance(row, Mapping) or row.get("schema_version") != PACKET_SCHEMA_VERSION:
                raise ValueError(f"input line {line_number}: unexpected schema_version")
            review_id = row.get("review_id")
            if not isinstance(review_id, str) or not review_id.strip():
                raise ValueError(f"input line {line_number}: review_id must be non-empty")
            if review_id in seen:
                raise ValueError(f"input line {line_number}: duplicate review_id")
            seen.add(review_id)
            rows.append(dict(row))
    return rows


def _endpoint_index(row: Mapping[str, Any], *, run_name: str, count: int) -> int:
    question_id = row.get("question_id")
    digest = hashlib.sha256(f"{run_name}|{question_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--endpoint", action="append")
    parser.add_argument("--model", default="DeepSeek-V4-Flash")
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--api-key-env", default="ENGLISH_TAGGER_DS_V4_API_KEY")
    args = parser.parse_args()
    if args.output == args.report:
        parser.error("--output and --report must differ")
    if args.output.exists() or args.report.exists():
        parser.error("refusing to overwrite existing output or report")
    if not args.run_name.strip():
        parser.error("--run-name must be non-empty")
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    if not 1 <= args.concurrency <= 128:
        parser.error("--concurrency must be between 1 and 128")
    endpoints = args.endpoint or [
        os.getenv("ENGLISH_TAGGER_DS_V4_ENDPOINT", DEFAULT_ENDPOINT)
    ]
    if not all(isinstance(item, str) and item.strip() for item in endpoints):
        parser.error("--endpoint values must be non-empty")
    try:
        rows = _load_rows(args.input, limit=args.limit)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    clients = [
        TerminalLabelStabilityClient(
            LabelingServiceConfig(
                endpoint=endpoint,
                model=args.model,
                timeout_seconds=args.timeout_seconds,
                api_key=os.getenv(args.api_key_env) or None,
            )
        )
        for endpoint in endpoints
    ]

    def one(row: Mapping[str, Any]) -> dict[str, Any]:
        index = _endpoint_index(row, run_name=args.run_name, count=len(endpoints))
        base = {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "review_id": row.get("review_id"),
            "source_review_id": row.get("source_review_id"),
            "question_id": row.get("question_id"),
            "parent_id": row.get("parent_id"),
            "canonical_label": row.get("canonical_label"),
            "definition_variant": row.get("definition_variant"),
            "split": row.get("split"),
            "route_key": row.get("route_key"),
            "run_name": args.run_name,
            "endpoint": endpoints[index],
            "model": args.model,
            "prompt_version": PROMPT_VERSION,
            "enable_thinking": False,
        }
        try:
            result = clients[index].classify(row)
        except (LabelingServiceError, OSError, ValueError) as error:
            return {**base, "status": "error", "error": str(error)}
        return {
            **base,
            "status": "candidate",
            "decision": result.decision,
            "confidence": result.confidence,
            "criterion_evidence": list(result.criterion_evidence),
            "missing_context": list(result.missing_context),
            "raw_response": result.raw_response,
            "elapsed_ms": result.elapsed_ms,
            "prompt_chars": result.prompt_chars,
        }

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(one, rows))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        for row in results:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    report = {
        "schema_version": "terminal-label-stability-run-report-v1",
        "input": str(args.input),
        "output": str(args.output),
        "run_name": args.run_name,
        "model": args.model,
        "endpoints": endpoints,
        "enable_thinking": False,
        "processed": len(results),
        "concurrency": args.concurrency,
        "status_counts": dict(sorted(Counter(row["status"] for row in results).items())),
        "decision_counts": dict(
            sorted(
                Counter(
                    row["decision"]
                    for row in results
                    if row.get("status") == "candidate"
                ).items()
            )
        ),
        "confidence_counts": dict(
            sorted(
                Counter(
                    row["confidence"]
                    for row in results
                    if row.get("status") == "candidate"
                ).items()
            )
        ),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
