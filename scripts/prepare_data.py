#!/usr/bin/env python3
"""Validate labeled JSONL and create content-grouped train/validation splits."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.data import content_hash, load_records, load_taxonomy, split_records
from english_knowledge_tagger.swift_data import to_swift_sft_row


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="labeled source JSONL outside Git")
    parser.add_argument("--taxonomy", type=Path, required=True, help="versioned knowledge-point taxonomy JSON")
    parser.add_argument("--output-dir", type=Path, required=True, help="directory for prepared split JSONL")
    parser.add_argument("--validation-ratio", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    taxonomy = load_taxonomy(args.taxonomy)
    records = load_records(args.input, taxonomy)
    train, validation = split_records(records, args.validation_ratio, args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output_dir / "train.jsonl", [asdict(record) for record in train])
    write_jsonl(args.output_dir / "validation.jsonl", [asdict(record) for record in validation])
    write_jsonl(args.output_dir / "swift_train.jsonl", [to_swift_sft_row(record) for record in train])
    write_jsonl(
        args.output_dir / "swift_validation.jsonl",
        [to_swift_sft_row(record) for record in validation],
    )
    label_counts = Counter(label for record in records for label in record.knowledge_points)
    manifest = {
        "schema_version": "v1",
        "source_path": str(args.input),
        "source_sha256": digest_file(args.input),
        "taxonomy_path": str(args.taxonomy),
        "taxonomy_sha256": digest_file(args.taxonomy),
        "seed": args.seed,
        "validation_ratio": args.validation_ratio,
        "total_records": len(records),
        "unique_content_hashes": len({content_hash(record) for record in records}),
        "train_records": len(train),
        "validation_records": len(validation),
        "training_formats": {
            "native": ["train.jsonl", "validation.jsonl"],
            "ms_swift": ["swift_train.jsonl", "swift_validation.jsonl"],
        },
        "label_counts": dict(sorted(label_counts.items())),
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
