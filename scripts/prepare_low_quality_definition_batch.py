#!/usr/bin/env python3
"""Validate a path manifest and prepare all reviewed definition packets offline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.low_quality_experiment_manifest import (
    load_low_quality_experiment_manifest,
    prepare_low_quality_definition_batch,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--seed", default="definition-stability-v1")
    args = parser.parse_args()
    try:
        report = prepare_low_quality_definition_batch(
            load_low_quality_experiment_manifest(args.manifest, check_paths=True),
            output_root=args.output_root,
            seed=args.seed,
        )
    except (FileExistsError, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
