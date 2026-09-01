#!/usr/bin/env python3
"""Repair missing parent text context in a flattened enhanced JSONL source."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.parent_context_repair import (
    build_raw_index,
    enrich_enhanced_source,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--enhanced", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    paths = (args.index, args.output, args.audit, args.report, args.manifest)
    existing = [str(path) for path in paths if path.exists()]
    if existing:
        parser.error(f"refusing to overwrite existing outputs: {', '.join(existing)}")
    for path in (args.raw, args.enhanced):
        if not path.is_file():
            parser.error(f"input is not a readable file: {path}")

    raw_sha256 = _sha256(args.raw)
    source_sha256 = _sha256(args.enhanced)
    index_report = build_raw_index(args.raw, args.index)
    repair_report = enrich_enhanced_source(
        args.enhanced,
        args.index,
        args.output,
        args.audit,
        args.report,
        args.manifest,
        source_sha256=source_sha256,
        raw_sha256=raw_sha256,
    )

    report = {
        **repair_report,
        "raw_path": str(args.raw),
        "raw_sha256": raw_sha256,
        "source_sha256": source_sha256,
        "raw_index_report": index_report,
    }
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
