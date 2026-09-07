#!/usr/bin/env python3
"""Delete routed originals and rename remaining files in 未处理label."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.cleanup_unprocessed_label_files import (
    apply_cleanup_plan,
    plan_cleanup,
)


def main() -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--freeze-manifest", type=Path, required=True)
    parser.add_argument("--routing-manifest", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="delete/rename; default is dry-run")
    parser.add_argument("--plan-output", type=Path)
    args = parser.parse_args()
    try:
        plan = plan_cleanup(args.directory, args.freeze_manifest, args.routing_manifest)
        if args.apply:
            apply_cleanup_plan(args.directory, plan)
    except (FileExistsError, FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    text = json.dumps({**plan, "apply": args.apply}, ensure_ascii=False, indent=2) + "\n"
    print(text, end="")
    if args.plan_output is not None:
        if args.plan_output.exists():
            parser.error(f"refusing to overwrite plan: {args.plan_output}")
        args.plan_output.parent.mkdir(parents=True, exist_ok=True)
        args.plan_output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

