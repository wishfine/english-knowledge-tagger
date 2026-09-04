"""Build exact-label full source packets for low-quality label remediation."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping

from .sft_labels import parse_sft_output_labels


SCHEMA_VERSION = "low-quality-label-full-source-packet-v1"
POLICY_SCHEMA_VERSION = "p0-terminal-label-policy-v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _legacy_label(canonical_label: str) -> str:
    """Render a teacher canonical path as the historical source label."""
    rendered = canonical_label.replace("->", "@")
    rendered = rendered.replace("知识点@词法", "知识点@语法词法")
    rendered = rendered.replace("知识点@句法", "知识点@语法句法")
    if not rendered.startswith("知识点@"):
        raise ValueError(f"canonical label must begin with 知识点: {canonical_label!r}")
    return rendered


def _filename(index: int, legacy_label: str) -> str:
    # A rendered label may contain '/' but it must remain one flat file.
    return f"劣质-{index:03d}-{legacy_label.replace('/', '／')}.jsonl"


def _load_policy(path: Path) -> tuple[str, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"policy is not valid JSON: {path}") from error
    if not isinstance(payload, Mapping) or payload.get("schema_version") != POLICY_SCHEMA_VERSION:
        raise ValueError(f"policy schema_version must be {POLICY_SCHEMA_VERSION!r}")
    raw_labels = payload.get("labels")
    if not isinstance(raw_labels, list) or not raw_labels:
        raise ValueError("policy labels must be a non-empty list")
    labels: list[str] = []
    for index, label in enumerate(raw_labels, 1):
        if not isinstance(label, str) or not label.strip().startswith("知识点->"):
            raise ValueError(f"policy labels[{index}] must be a canonical 知识点-> path")
        labels.append(label.strip())
    if len(labels) != len(set(labels)):
        raise ValueError("policy labels must be unique")
    return tuple(labels)


def _normalise_exclusions(exclude_labels: Iterable[str]) -> set[str]:
    result: set[str] = set()
    for label in exclude_labels:
        if not isinstance(label, str) or not label.strip():
            raise ValueError("excluded labels must be non-empty strings")
        value = label.strip()
        if value.startswith("知识点->"):
            result.add(value)
            result.add(_legacy_label(value))
        elif value.startswith("知识点@"):
            result.add(value)
        else:
            raise ValueError(f"excluded label must begin with 知识点-> or 知识点@: {value!r}")
    return result


def build_low_quality_label_full_packets(
    source_path: Path,
    *,
    policy_path: Path,
    output_dir: Path,
    exclude_labels: Iterable[str] = (),
) -> dict[str, object]:
    """Stream a source once and copy every matching row into per-label files.

    This is deliberately a source packet builder, not a DS runner: rows are
    copied byte-for-byte, including all historical labels and source fields.
    A row carrying multiple target labels is copied to each corresponding file.
    """
    if not source_path.is_file():
        raise FileNotFoundError(f"source is not a file: {source_path}")
    if not policy_path.is_file():
        raise FileNotFoundError(f"policy is not a file: {policy_path}")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"refusing to write into non-empty output directory: {output_dir}")

    canonical_labels = _load_policy(policy_path)
    excluded = _normalise_exclusions(exclude_labels)
    selected = tuple(
        canonical for canonical in canonical_labels
        if canonical not in excluded and _legacy_label(canonical) not in excluded
    )
    if not selected:
        raise ValueError("all policy labels are excluded")
    legacy_by_canonical = {canonical: _legacy_label(canonical) for canonical in selected}
    legacy_labels = tuple(legacy_by_canonical.values())
    if len(legacy_labels) != len(set(legacy_labels)):
        raise ValueError("canonical labels collide after historical rendering")

    output_dir.mkdir(parents=True, exist_ok=False)
    handles: dict[str, object] = {}
    counts: dict[str, int] = {label: 0 for label in legacy_labels}
    source_records = 0
    source_label_hits = 0
    source_digest = hashlib.sha256()
    try:
        for index, legacy_label in enumerate(legacy_labels, 1):
            path = output_dir / _filename(index, legacy_label)
            handles[legacy_label] = path.open("xb")
        with source_path.open("rb") as source:
            for source_line, raw_line in enumerate(source, 1):
                source_digest.update(raw_line)
                if not raw_line.strip():
                    continue
                try:
                    record = json.loads(raw_line)
                except json.JSONDecodeError as error:
                    raise ValueError(f"source line {source_line}: invalid JSON") from error
                if not isinstance(record, Mapping):
                    raise ValueError(f"source line {source_line}: JSONL row must be an object")
                source_records += 1
                parsed = parse_sft_output_labels(record.get("output"))
                if parsed is None:
                    continue
                historical_labels, _ = parsed
                matches = [label for label in legacy_labels if label in historical_labels]
                source_label_hits += len(matches)
                for label in matches:
                    handles[label].write(raw_line)  # type: ignore[union-attr]
                    counts[label] += 1
    finally:
        for handle in handles.values():
            handle.close()  # type: ignore[union-attr]

    labels = []
    for index, canonical in enumerate(selected, 1):
        legacy = legacy_by_canonical[canonical]
        path = output_dir / _filename(index, legacy)
        labels.append({
            "index": index,
            "canonical_label": canonical,
            "verify_label": legacy,
            "filename": path.name,
            "records": counts[legacy],
            "sha256": _sha256(path),
            "status": "pending_full_discriminator",
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "source_path": str(source_path),
        "source_sha256": source_digest.hexdigest(),
        "source_records": source_records,
        "source_label_hits": source_label_hits,
        "policy_path": str(policy_path),
        "policy_sha256": _sha256(policy_path),
        "excluded_labels": sorted(excluded),
        "labels": len(labels),
        "total_packet_records": sum(counts.values()),
        "label_records": labels,
        "output_dir": str(output_dir),
    }
