#!/usr/bin/env python3
"""Evaluate prediction JSONL against a prepared gold JSONL split."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.data import DataContractError, load_records, load_taxonomy, normalize_text
from english_knowledge_tagger.metrics import multilabel_metrics


def load_predictions(path: Path, taxonomy: frozenset[str]) -> dict[str, list[str]]:
    predictions: dict[str, list[str]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload: Any = json.loads(line)
        except json.JSONDecodeError as error:
            raise DataContractError(f"prediction line {line_number}: invalid JSON: {error.msg}") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("id"), str):
            raise DataContractError(f"prediction line {line_number}: id must be a string")
        labels = payload.get("knowledge_points")
        if not isinstance(labels, list) or any(not isinstance(label, str) for label in labels):
            raise DataContractError(f"prediction line {line_number}: knowledge_points must be a string array")
        identifier = normalize_text(payload["id"])
        if not identifier or identifier in predictions:
            raise DataContractError(f"prediction line {line_number}: id must be non-empty and unique")
        normalized_labels = sorted({normalize_text(label) for label in labels if normalize_text(label)})
        unknown = sorted(set(normalized_labels) - taxonomy)
        if unknown:
            raise DataContractError(f"prediction line {line_number}: labels not in taxonomy: {', '.join(unknown)}")
        predictions[identifier] = normalized_labels
    return predictions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-file", type=Path, required=True)
    parser.add_argument("--prediction-file", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--output-file", type=Path, required=True)
    args = parser.parse_args()

    taxonomy = load_taxonomy(args.taxonomy)
    gold_records = load_records(args.gold_file, taxonomy)
    predictions = load_predictions(args.prediction_file, taxonomy)
    gold_ids = {record.id for record in gold_records}
    prediction_ids = set(predictions)
    if gold_ids != prediction_ids:
        missing, extra = sorted(gold_ids - prediction_ids), sorted(prediction_ids - gold_ids)
        raise DataContractError(f"prediction IDs differ from gold; missing={missing[:5]}, extra={extra[:5]}")

    scores = multilabel_metrics(
        [record.knowledge_points for record in gold_records],
        [predictions[record.id] for record in gold_records],
    )
    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    args.output_file.write_text(json.dumps(scores, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(scores, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
