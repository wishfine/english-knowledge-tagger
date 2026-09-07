"""Safely rename per-label files from a frozen pool manifest.

The tool resolves a file by its embedded historical label, never by its old
numeric index.  It is dry-run by default; applying a plan uses temporary names
first so index reorders cannot overwrite a sibling file.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import uuid
from typing import Any, Iterable


_NAME = re.compile(
    r"^(?P<pool>优质|次优|劣质|次次优)-(?P<index>\d{3})-(?P<label>.+?)(?P<suffix>\.(?:jsonl|json))$"
)
_UNESCAPE = str.maketrans(
    {
        "／": "/",
        "＼": "\\",
        "：": ":",
        "＊": "*",
        "？": "?",
        "＂": '"',
        "＜": "<",
        "＞": ">",
        "｜": "|",
    }
)


def _load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "label-pool-freeze-v1":
        raise ValueError("manifest schema_version must be label-pool-freeze-v1")
    rows = payload.get("labels")
    if not isinstance(rows, list) or not rows:
        raise ValueError("manifest labels must be a non-empty list")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("legacy_label"), str):
            raise ValueError("manifest contains a malformed label row")
        label = row["legacy_label"]
        if label in result:
            raise ValueError(f"manifest contains duplicate label: {label}")
        if not isinstance(row.get("target_basename"), str) or not row["target_basename"]:
            raise ValueError(f"manifest row has no target_basename: {label}")
        result[label] = row
    return result


def _label_from_name(name: str) -> str | None:
    match = _NAME.fullmatch(name)
    if match is None:
        return None
    return match.group("label").translate(_UNESCAPE)


def plan_renames(directory: Path, manifest_path: Path, *, allow_unmatched: bool = False) -> list[dict[str, str]]:
    """Return a deterministic source/target plan without touching files."""
    if not directory.is_dir():
        raise FileNotFoundError(directory)
    manifest = _load_manifest(manifest_path)
    plan: list[dict[str, str]] = []
    manifest_resolved = manifest_path.resolve()
    for path in sorted(directory.iterdir(), key=lambda value: value.name):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.resolve() == manifest_resolved:
            continue
        label = _label_from_name(path.name)
        if label is None:
            if allow_unmatched or path.suffix not in {".jsonl", ".json"}:
                continue
            raise ValueError(f"file name does not match pool-label format: {path.name}")
        row = manifest.get(label)
        if row is None:
            raise ValueError(f"file label is absent from freeze manifest: {label}")
        target = f"{row['target_basename']}{path.suffix}"
        if target != path.name:
            plan.append({"source": path.name, "target": target, "label": label})

    sources = {item["source"] for item in plan}
    targets = [item["target"] for item in plan]
    if len(targets) != len(set(targets)):
        raise ValueError("rename plan contains duplicate targets")
    existing = {path.name for path in directory.iterdir() if path.is_file()}
    collisions = (set(targets) & existing) - sources
    if collisions:
        raise FileExistsError(f"target already exists: {sorted(collisions)}")
    return plan


def apply_rename_plan(directory: Path, plan: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    """Apply a preflighted plan using temporary names and return the plan."""
    rows = list(plan)
    sources = [directory / item["source"] for item in rows]
    targets = [directory / item["target"] for item in rows]
    if len({path.name for path in sources}) != len(sources):
        raise ValueError("rename plan contains duplicate sources")
    if len({path.name for path in targets}) != len(targets):
        raise ValueError("rename plan contains duplicate targets")
    if any(not path.is_file() for path in sources):
        missing = [str(path) for path in sources if not path.is_file()]
        raise FileNotFoundError(", ".join(missing))
    source_names = {path.name for path in sources}
    collisions = [path.name for path in targets if path.exists() and path.name not in source_names]
    if collisions:
        raise FileExistsError(f"target already exists: {sorted(collisions)}")

    token = uuid.uuid4().hex
    temporary = [directory / f".pool-rename-{token}-{index:04d}.tmp" for index in range(len(rows))]
    for path in temporary:
        if path.exists():
            raise FileExistsError(path)
    for source, temp in zip(sources, temporary):
        source.rename(temp)
    for temp, target in zip(temporary, targets):
        temp.rename(target)
    return rows


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--allow-unmatched", action="store_true")
    parser.add_argument("--apply", action="store_true", help="actually rename files; default is dry-run")
    parser.add_argument("--map-output", type=Path)
    args = parser.parse_args()
    plan = plan_renames(args.directory, args.manifest, allow_unmatched=args.allow_unmatched)
    if args.apply:
        apply_rename_plan(args.directory, plan)
    payload = {"apply": args.apply, "directory": str(args.directory), "renames": plan, "count": len(plan)}
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    print(text, end="")
    if args.map_output is not None:
        args.map_output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
