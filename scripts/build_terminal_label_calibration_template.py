#!/usr/bin/env python3
"""Write one manual calibration template row for every active terminal knowledge label."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teacher-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite existing output: {args.output}")
    try:
        rulebook = load_knowledge_rulebook(args.teacher_csv)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        for label, record in sorted(rulebook.records.items()):
            if record.status != "active":
                continue
            output.write(
                json.dumps(
                    {
                        "canonical_label": label,
                        "positive_disposition": "hold",
                        "negative_disposition": "hold",
                        "calibration_stage": "unreviewed",
                        "audit": {
                            "positive": {"retain": 0, "remove": 0, "uncertain": 0},
                            "negative": {"retain": 0, "remove": 0, "uncertain": 0},
                        },
                        "target_definition": record.target_definition,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
    print(json.dumps({"output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
