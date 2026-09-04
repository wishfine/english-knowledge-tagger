#!/usr/bin/env python3
"""Build the complete 384-label status ledger from the calibration and manifests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.knowledge_label_status_ledger import (
    build_knowledge_label_status_ledger,
)


QUALITY_EXCLUDED = (
    "知识点@语法词法@动词时态@一般过去时@动词过去式变化规则",
    "知识点@语法词法@非谓语动词@动名词@动名词的结构@动名词的一般式",
    "知识点@语法词法@形容词与副词@副词的用法@副词修饰副词",
    "知识点@语法词法@非谓语动词@动词不定式@动词不定式的结构@动词不定式的被动式",
)

POST_SWEEP_HOLD = (
    "知识点@词汇@近/反义词@同/近义词",
    "知识点@语法词法@动词时态@一般将来时@一般将来时的定义/判定@be going to",
)

TAXONOMY_RECONCILED = {
    "知识点@语法词法@动词@情态动词@can@can/can't表示推测":
        "知识点->词法->动词->情态动词->can->can't表示否定推测",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-sample-ledger", type=Path, required=True)
    parser.add_argument("--candidate-manifest", type=Path, action="append", required=True)
    parser.add_argument("--taxonomy-migration", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error(f"refusing to overwrite existing report: {args.report}")
    try:
        report = build_knowledge_label_status_ledger(
            full_sample_ledger=args.full_sample_ledger,
            candidate_manifests=tuple(args.candidate_manifest),
            taxonomy_migration=args.taxonomy_migration,
            output=args.output,
            quality_excluded=QUALITY_EXCLUDED,
            post_sweep_hold=POST_SWEEP_HOLD,
            taxonomy_reconciled=TAXONOMY_RECONCILED,
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
