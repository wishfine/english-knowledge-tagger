#!/usr/bin/env python3
"""Select a passing D3 definition that beats the best D0-D2 dev baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.contrastive_definition import select_contrastive_definition


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--definitions", type=Path, required=True)
    parser.add_argument("--canonical-label", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite existing output: {args.output}")
    try:
        analysis = json.loads(args.analysis.read_text(encoding="utf-8"))
        definitions = json.loads(args.definitions.read_text(encoding="utf-8"))
        selection = select_contrastive_definition(
            analysis, canonical_label=args.canonical_label
        )
        if selection.get("status") == "selected":
            candidates = definitions.get("candidates")
            if not isinstance(candidates, list):
                raise ValueError("definitions candidates must be a list")
            selected = next(
                (
                    item
                    for item in candidates
                    if isinstance(item, dict)
                    and item.get("candidate_id") == selection["definition_variant"]
                ),
                None,
            )
            if selected is None:
                raise ValueError("selected definition is absent from definitions file")
            selection = {**selection, "definition_text": selected.get("definition_text")}
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(selection, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(selection, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
