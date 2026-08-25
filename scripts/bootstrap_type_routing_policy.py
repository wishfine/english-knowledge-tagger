#!/usr/bin/env python3
"""Create a complete, all-unmapped type-routing policy skeleton from inventory JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.type_routing import bootstrap_type_routing_policy


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.output.exists():
        parser.error(f"refusing to overwrite existing output: {args.output}")
    try:
        inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        parser.error(f"inventory is not valid JSON: {error}")
    if not isinstance(inventory, dict):
        parser.error("inventory root must be an object")

    policy = bootstrap_type_routing_policy(inventory)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"inventory": str(args.inventory), "output": str(args.output), "rule_count": len(policy["rules"])},
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
