"""Route per-label result files into processed or issue directories.

Routing is label-driven and dry-run by default at the CLI.  Files are resolved
by the complete historical label embedded in their filename, then renamed to
the frozen pool name in the destination directory.
"""

from __future__ import annotations

import json
from pathlib import Path
import uuid
from typing import Any, Iterable

from .rename_pool_label_files import _label_from_name, _load_manifest


ROUTING_SCHEMA_VERSION = "post-sweep-15-routing-v1"


def _routing_labels(path: Path) -> tuple[list[str], list[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != ROUTING_SCHEMA_VERSION:
        raise ValueError(f"routing manifest schema_version must be {ROUTING_SCHEMA_VERSION}")
    processed = payload.get("processed_labels")
    issue = payload.get("issue_labels")
    if not isinstance(processed, list) or not isinstance(issue, list):
        raise ValueError("routing manifest must contain processed_labels and issue_labels lists")
    processed = [str(value).strip() for value in processed if str(value).strip()]
    issue = [str(value).strip() for value in issue if str(value).strip()]
    if not processed or not issue:
        raise ValueError("both routing label lists must be non-empty")
    if set(processed) & set(issue):
        raise ValueError("a label cannot be in both processed_labels and issue_labels")
    return processed, issue


def plan_routes(
    *,
    source_dir: Path,
    processed_dir: Path,
    issue_dir: Path,
    manifest_path: Path,
    processed_labels: Iterable[str],
    issue_labels: Iterable[str],
) -> list[dict[str, str]]:
    """Build a complete source-to-destination plan without touching files."""
    if not source_dir.is_dir():
        raise FileNotFoundError(source_dir)
    manifest = _load_manifest(manifest_path)
    processed = {label.strip() for label in processed_labels if label.strip()}
    issue = {label.strip() for label in issue_labels if label.strip()}
    if not processed or not issue:
        raise ValueError("both processed_labels and issue_labels must be non-empty")
    if processed & issue:
        raise ValueError("a label cannot be in both destinations")
    selected = processed | issue
    missing_manifest = sorted(selected - set(manifest))
    if missing_manifest:
        raise ValueError("routing labels absent from freeze manifest: " + ", ".join(missing_manifest))

    found: dict[str, Path] = {}
    for path in sorted(source_dir.iterdir(), key=lambda value: value.name):
        if not path.is_file() or path.name.startswith("."):
            continue
        label = _label_from_name(path.name)
        if label not in selected:
            continue
        if label in found:
            raise ValueError(f"multiple source files found for label: {label}")
        found[label] = path

    missing_files = sorted(selected - set(found))
    if missing_files:
        raise FileNotFoundError("source files not found for labels: " + ", ".join(missing_files))

    plan: list[dict[str, str]] = []
    for label in sorted(selected):
        source = found[label]
        destination_dir = processed_dir if label in processed else issue_dir
        target = destination_dir / f"{manifest[label]['target_basename']}{source.suffix}"
        plan.append(
            {
                "label": label,
                "source": str(source),
                "target": str(target),
                "destination": "processed" if label in processed else "issue",
            }
        )

    source_paths = {Path(item["source"]) for item in plan}
    target_paths = [Path(item["target"]) for item in plan]
    if len(target_paths) != len(set(target_paths)):
        raise ValueError("routing plan contains duplicate targets")
    collisions = [
        str(path)
        for path in target_paths
        if path.exists() and path not in source_paths
    ]
    if collisions:
        raise FileExistsError("target already exists: " + ", ".join(sorted(collisions)))
    return plan


def apply_route_plan(plan: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    """Apply a preflighted route plan via temporary source names."""
    rows = list(plan)
    sources = [Path(item["source"]) for item in rows]
    targets = [Path(item["target"]) for item in rows]
    if len({path for path in sources}) != len(sources):
        raise ValueError("routing plan contains duplicate sources")
    if len({path for path in targets}) != len(targets):
        raise ValueError("routing plan contains duplicate targets")
    if any(not path.is_file() for path in sources):
        missing = [str(path) for path in sources if not path.is_file()]
        raise FileNotFoundError(", ".join(missing))
    source_set = set(sources)
    collisions = [
        str(path)
        for path in targets
        if path.exists() and path not in source_set
    ]
    if collisions:
        raise FileExistsError("target already exists: " + ", ".join(sorted(collisions)))

    token = uuid.uuid4().hex
    temporary: list[Path | None] = []
    for index, (source, target) in enumerate(zip(sources, targets)):
        if source == target:
            temporary.append(None)
            continue
        temp = source.parent / f".route-label-{token}-{index:04d}.tmp"
        if temp.exists():
            raise FileExistsError(temp)
        source.rename(temp)
        temporary.append(temp)
    for temp, target in zip(temporary, targets):
        if temp is None:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        temp.rename(target)
    return rows


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--processed-dir", type=Path, required=True)
    parser.add_argument("--issue-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--routing-manifest", type=Path)
    parser.add_argument("--processed-label", action="append", default=[])
    parser.add_argument("--issue-label", action="append", default=[])
    parser.add_argument("--apply", action="store_true", help="actually move/rename; default is dry-run")
    parser.add_argument("--map-output", type=Path)
    args = parser.parse_args()

    if args.routing_manifest is not None:
        if args.processed_label or args.issue_label:
            parser.error("use --routing-manifest or explicit label options, not both")
        processed, issue = _routing_labels(args.routing_manifest)
    else:
        processed, issue = args.processed_label, args.issue_label
    try:
        plan = plan_routes(
            source_dir=args.source_dir,
            processed_dir=args.processed_dir,
            issue_dir=args.issue_dir,
            manifest_path=args.manifest,
            processed_labels=processed,
            issue_labels=issue,
        )
        if args.apply:
            apply_route_plan(plan)
    except (FileExistsError, FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    payload: dict[str, Any] = {
        "apply": args.apply,
        "source_dir": str(args.source_dir),
        "processed_dir": str(args.processed_dir),
        "issue_dir": str(args.issue_dir),
        "count": len(plan),
        "routes": plan,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    print(text, end="")
    if args.map_output is not None:
        if args.map_output.exists():
            parser.error(f"refusing to overwrite map: {args.map_output}")
        args.map_output.parent.mkdir(parents=True, exist_ok=True)
        args.map_output.write_text(text, encoding="utf-8")
    return 0

