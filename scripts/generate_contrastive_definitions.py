#!/usr/bin/env python3
"""Generate three D3 definition candidates from definition-train rows only."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.candidate_labeling import LabelingServiceConfig
from english_knowledge_tagger.contrastive_definition import (
    PROMPT_VERSION,
    ContrastiveDefinitionClient,
    build_contrastive_definition_task,
)


DEFAULT_ENDPOINT = "http://172.22.0.35:9102/v1/chat/completions"


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON: {path}") from error


def _jsonl(path: Path):
    rows = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path} line {line_number}: invalid JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"{path} line {line_number}: row must be an object")
            rows.append(row)
    return tuple(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--ambiguity-manifest", type=Path, required=True)
    parser.add_argument("--canonical-label", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--endpoint")
    parser.add_argument("--model", default="DeepSeek-V4-Flash")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--api-key-env", default="ENGLISH_TAGGER_DS_V4_API_KEY")
    args = parser.parse_args()
    if args.output == args.report:
        parser.error("--output and --report must differ")
    if args.output.exists() or args.report.exists():
        parser.error("refusing to overwrite existing output or report")
    endpoint = args.endpoint or os.getenv("ENGLISH_TAGGER_DS_V4_ENDPOINT", DEFAULT_ENDPOINT)
    try:
        task = build_contrastive_definition_task(
            _jsonl(args.packet),
            ambiguity_manifest=_json(args.ambiguity_manifest),
            canonical_label=args.canonical_label,
        )
        client = ContrastiveDefinitionClient(
            LabelingServiceConfig(
                endpoint=endpoint,
                model=args.model,
                timeout_seconds=args.timeout_seconds,
                api_key=os.getenv(args.api_key_env) or None,
                max_tokens=2048,
            )
        )
        result = client.generate(task)
    except (OSError, ValueError, RuntimeError) as error:
        parser.error(str(error))
    payload = {
        "schema_version": "contrastive-definition-candidates-v1",
        "prompt_version": PROMPT_VERSION,
        "canonical_label": args.canonical_label,
        "legacy_label": task["legacy_label"],
        "source_packet": str(args.packet),
        "ambiguity_manifest": str(args.ambiguity_manifest),
        "candidates": [
            {
                "candidate_id": item.candidate_id,
                "definition_text": item.definition_text,
                "positive_criteria": item.positive_criteria,
                "neighbor_exclusions": list(item.neighbor_exclusions),
                "insufficient_rule": item.insufficient_rule,
                "co_label_rule": item.co_label_rule,
                "appearance_dependency_rule": item.appearance_dependency_rule,
            }
            for item in result.candidates
        ],
    }
    report = {
        "schema_version": "contrastive-definition-generation-report-v1",
        "canonical_label": args.canonical_label,
        "candidate_count": len(result.candidates),
        "train_example_counts": task["train_example_counts"],
        "elapsed_ms": result.elapsed_ms,
        "prompt_chars": result.prompt_chars,
        "endpoint": endpoint,
        "model": args.model,
        "enable_thinking": False,
        "output": str(args.output),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
