"""Delete routed originals and rename the remaining unprocessed label files."""

from __future__ import annotations

import json
from pathlib import Path
import uuid
from typing import Any

from .label_pool_freeze import _safe_label


SCHEMA_VERSION = "unprocessed-label-cleanup-v1"
ROUTING_SCHEMA_VERSION = "eligible-unprocessed-routing-v1"
_EXTENSIONS = {".jsonl", ".json"}


def _load_freeze(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "label-pool-freeze-v1":
        raise ValueError("freeze manifest schema_version is invalid")
    result: dict[str, dict[str, Any]] = {}
    for row in payload.get("labels", []):
        if not isinstance(row, dict) or not isinstance(row.get("legacy_label"), str):
            raise ValueError("freeze manifest has malformed label row")
        result[row["legacy_label"]] = row
    if not result:
        raise ValueError("freeze manifest contains no labels")
    return result


def _load_routing(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != ROUTING_SCHEMA_VERSION:
        raise ValueError("routing manifest schema_version is invalid")
    processed = payload.get("processed_labels")
    issue = payload.get("issue_labels")
    if not isinstance(processed, list) or not isinstance(issue, list):
        raise ValueError("routing manifest must contain label lists")
    routed = {str(label).strip() for label in processed + issue if str(label).strip()}
    if not routed:
        raise ValueError("routing manifest contains no labels")
    return routed


def _label_from_filename(name: str, labels: set[str]) -> str | None:
    stem = name.rsplit(".", 1)[0] if "." in name else name
    candidates = sorted(((label, _safe_label(label)) for label in labels), key=lambda pair: len(pair[1]), reverse=True)
    for label, safe in candidates:
        if stem == safe or stem.endswith("-" + safe):
            return label
    return None


def plan_cleanup(directory: Path, freeze_manifest: Path, routing_manifest: Path) -> dict[str, Any]:
    """Build a dry-run cleanup plan without touching the directory."""
    if not directory.is_dir():
        raise FileNotFoundError(directory)
    freeze = _load_freeze(freeze_manifest)
    routed = _load_routing(routing_manifest)
    labels = set(freeze)
    found_routed: set[str] = set()
    actions: list[dict[str, str]] = []
    unmatched: list[str] = []
    target_names: set[str] = set()
    ignored_paths = {freeze_manifest.resolve(), routing_manifest.resolve()}

    for path in sorted(directory.iterdir(), key=lambda value: value.name):
        if not path.is_file() or path.suffix not in _EXTENSIONS or path.name.startswith("."):
            continue
        if path.resolve() in ignored_paths:
            continue
        label = _label_from_filename(path.name, labels)
        if label is None:
            unmatched.append(path.name)
            continue
        if label in routed:
            found_routed.add(label)
            actions.append({"action": "delete", "label": label, "source": path.name})
            continue
        target = f"{freeze[label]['target_basename']}{path.suffix}"
        if target != path.name:
            target_names.add(target)
            actions.append({"action": "rename", "label": label, "source": path.name, "target": target})

    rename_targets = [row["target"] for row in actions if row["action"] == "rename"]
    if len(rename_targets) != len(set(rename_targets)):
        raise ValueError("cleanup plan contains duplicate rename targets")
    existing = {path.name for path in directory.iterdir() if path.is_file()}
    sources = {row["source"] for row in actions}
    collisions = (set(rename_targets) & existing) - sources
    if collisions:
        raise FileExistsError("rename target already exists: " + ", ".join(sorted(collisions)))

    return {
        "schema_version": SCHEMA_VERSION,
        "directory": str(directory),
        "routed_labels": sorted(routed),
        "missing_routed_labels": sorted(routed - found_routed),
        "unmatched_files": unmatched,
        "counts": {
            "delete": sum(row["action"] == "delete" for row in actions),
            "rename": sum(row["action"] == "rename" for row in actions),
            "unmatched": len(unmatched),
        },
        "actions": actions,
    }


def apply_cleanup_plan(directory: Path, plan: dict[str, Any]) -> None:
    """Apply a preflighted plan; renames use temporary names."""
    if plan.get("directory") != str(directory):
        raise ValueError("cleanup plan directory does not match target directory")
    actions = list(plan.get("actions", []))
    deletes = [directory / row["source"] for row in actions if row["action"] == "delete"]
    renames = [row for row in actions if row["action"] == "rename"]
    for path in deletes:
        if not path.is_file():
            raise FileNotFoundError(path)
    for row in renames:
        if not (directory / row["source"]).is_file():
            raise FileNotFoundError(directory / row["source"])

    for path in deletes:
        path.unlink()

    token = uuid.uuid4().hex
    temporary: list[tuple[Path, Path]] = []
    for index, row in enumerate(renames):
        source = directory / row["source"]
        target = directory / row["target"]
        temp = directory / f".cleanup-unprocessed-{token}-{index:04d}.tmp"
        source.rename(temp)
        temporary.append((temp, target))
    for temp, target in temporary:
        temp.rename(target)
