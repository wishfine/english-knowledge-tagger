#!/usr/bin/env python3
"""Materialize one DS-positive packet JSONL per processed knowledge label."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.knowledge_taxonomy_migration import (
    load_knowledge_taxonomy_migration,
)
from english_knowledge_tagger.materialize_processed_label_packets import (
    materialize_processed_label_packets,
)


EXCLUDED_LABELS = (
    "知识点@语法词法@动词时态@一般过去时@动词过去式变化规则",
    "知识点@语法词法@非谓语动词@动名词@动名词的结构@动名词的一般式",
    "知识点@语法词法@形容词与副词@副词的用法@副词修饰副词",
    "知识点@语法词法@非谓语动词@动词不定式@动词不定式的结构@动词不定式的被动式",
    "知识点@词汇@近/反义词@同/近义词",
    "知识点@语法词法@动词时态@一般将来时@一般将来时的定义/判定@be going to",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-db", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True, help="v3 source JSONL")
    parser.add_argument("--taxonomy-migration", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expected-label-count", type=int, default=138)
    args = parser.parse_args()
    if args.report.exists():
        parser.error(f"refusing to overwrite existing report: {args.report}")
    try:
        migration = load_knowledge_taxonomy_migration(args.taxonomy_migration)
        report = materialize_processed_label_packets(
            snapshot_db=args.snapshot_db,
            source_path=args.source,
            output_dir=args.output_dir,
            migration=migration,
            excluded_labels=EXCLUDED_LABELS,
            expected_label_count=args.expected_label_count,
        )
    except (FileExistsError, FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
