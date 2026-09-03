"""Build a bounded, stratified final-label packet for input-status pilots."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from .candidate_final_packet_batch import _route_key
from .final_label_discriminator import (
    FINAL_PACKET_SCHEMA_VERSION,
    clean_final_label_question,
)
from .input_completeness import classify_input_completeness
from .mentor_direct_rollout import load_mentor_label_definitions
from .sft_labels import parse_sft_output_labels


PILOT_MANIFEST_SCHEMA_VERSION = "input-status-pilot-label-manifest-v1"
PILOT_INDEX_SCHEMA_VERSION = "input-status-pilot-packet-index-v1"
PILOT_PROMPT_VERSION = "final-label-discriminator-v2-input-status"
def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _required_identity(row: Mapping[str, Any]) -> tuple[str, str, bool] | None:
    question_id = row.get("question_id")
    parent_id = row.get("parent_id")
    is_sub_question = row.get("is_sub_question")
    if (
        not isinstance(question_id, str)
        or not question_id.strip()
        or not isinstance(parent_id, str)
        or not parent_id.strip()
        or not isinstance(is_sub_question, bool)
    ):
        return None
    return question_id.strip(), parent_id.strip(), is_sub_question


def _slug(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()[:12]


def _rank(seed: str, label: str, source_line: int) -> int:
    raw = f"{seed}\x1f{label}\x1f{source_line}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")


def _offer(values: list[tuple[int, dict[str, Any]]], item: tuple[int, dict[str, Any]], limit: int) -> None:
    values.append(item)
    values.sort(key=lambda value: value[0])
    del values[limit:]


def _load_labels(path: Path) -> list[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"pilot label manifest is not valid JSON: {path}") from error
    if not isinstance(payload, Mapping) or payload.get("schema_version") != PILOT_MANIFEST_SCHEMA_VERSION:
        raise ValueError("pilot label manifest has unexpected schema_version")
    labels = payload.get("labels")
    if not isinstance(labels, list) or not labels:
        raise ValueError("pilot label manifest labels must be a non-empty list")
    cleaned = []
    for index, label in enumerate(labels, 1):
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"pilot label manifest labels[{index}] must be a non-empty string")
        cleaned.append(label.strip())
    if len(cleaned) != len(set(cleaned)):
        raise ValueError("pilot label manifest labels must be unique")
    return cleaned


def build_input_status_pilot_packets(
    source_path: Path,
    *,
    manifest_path: Path,
    label_definitions_path: Path,
    output_dir: Path,
    max_per_label: int = 24,
    max_per_status: int = 4,
    seed: str = "input-status-pilot-v1",
) -> dict[str, object]:
    """Scan the source once and write at most ``max_per_label`` rows per label.

    Rows are sampled deterministically and stratified by the local input
    completeness status. This is an audit packet only; the source and labels
    are never modified.
    """
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite pilot packet directory: {output_dir}")
    if max_per_label <= 0 or max_per_status <= 0:
        raise ValueError("max_per_label and max_per_status must be positive")
    if not seed.strip():
        raise ValueError("seed must be non-empty")

    labels = _load_labels(manifest_path)
    definitions = load_mentor_label_definitions(label_definitions_path)
    definitions_sha256 = _sha256(label_definitions_path)
    missing_definitions = sorted(set(labels) - set(definitions))
    if missing_definitions:
        raise ValueError("pilot labels missing from label definitions: " + ", ".join(missing_definitions))

    output_dir.mkdir(parents=True)
    label_set = set(labels)
    output_paths = {label: output_dir / f"{_slug(label)}.input-status.packet.jsonl" for label in labels}
    per_label: dict[str, dict[str, Any]] = {
        label: {
            "matching_source_records": 0,
            "selected_records": 0,
            "skipped_identity": 0,
            "skipped_input": 0,
            "precheck_status_counts": Counter(),
            "by_status": {status: [] for status in (
                "complete",
                "analysis_supported",
                "parent_context_only",
                "audio_or_image_missing",
                "sibling_mapping_ambiguous",
                "insufficient",
            )},
            "global": [],
        }
        for label in labels
    }

    source_hasher = hashlib.sha256()
    source_records = 0
    source_candidate_hits = 0
    with source_path.open("rb") as source:
        for source_line, raw_line in enumerate(source, 1):
            source_hasher.update(raw_line)
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
            matching = tuple(label for label in labels if label in historical_labels)
            if not matching:
                continue
            source_candidate_hits += len(matching)
            identity = _required_identity(record)
            route_key = _route_key(record)
            for label in matching:
                stats = per_label[label]
                stats["matching_source_records"] += 1
                if identity is None:
                    stats["skipped_identity"] += 1
                    continue
                try:
                    question_text = clean_final_label_question(record.get("input"))
                except (TypeError, ValueError):
                    stats["skipped_input"] += 1
                    continue
                question_id, parent_id, is_sub_question = identity
                packet = {
                    "schema_version": FINAL_PACKET_SCHEMA_VERSION,
                    "review_id": f"{PILOT_PROMPT_VERSION}:{source_line}:{label}",
                    "question_id": question_id,
                    "parent_id": parent_id,
                    "source_line": source_line,
                    "is_sub_question": is_sub_question,
                    "route_key": route_key,
                    "verify_label": label,
                    "question_text": question_text,
                    "input_precheck": classify_input_completeness({
                        "is_sub_question": is_sub_question,
                        "route_key": route_key,
                        "question_text": question_text,
                    }),
                    "source_packet_path": str(output_paths[label]),
                    "source_path": str(source_path),
                    "label_definitions_path": str(label_definitions_path),
                    "label_definitions_sha256": definitions_sha256,
                }
                status = packet["input_precheck"]["status"]
                stats["precheck_status_counts"][status] += 1
                ranked = (_rank(seed, label, source_line), packet)
                _offer(stats["by_status"][status], ranked, max_per_status)
                _offer(stats["global"], ranked, max_per_label)

    index_labels: dict[str, dict[str, object]] = {}
    selected_total = 0
    for label in labels:
        stats = per_label[label]
        selected_by_line: dict[int, dict[str, Any]] = {}
        for status in stats["by_status"]:
            for _, packet in stats["by_status"][status]:
                selected_by_line[packet["source_line"]] = packet
        if len(selected_by_line) > max_per_label:
            selected_by_line = dict(sorted(selected_by_line.items())[:max_per_label])
        if len(selected_by_line) < max_per_label:
            for _, packet in stats["global"]:
                selected_by_line.setdefault(packet["source_line"], packet)
                if len(selected_by_line) >= max_per_label:
                    break
        selected = sorted(selected_by_line.values(), key=lambda packet: packet["source_line"])
        with output_paths[label].open("x", encoding="utf-8") as output:
            for packet in selected:
                output.write(json.dumps(packet, ensure_ascii=False, sort_keys=True) + "\n")
        stats["selected_records"] = len(selected)
        selected_total += len(selected)
        index_labels[label] = {
            "packet_path": str(output_paths[label]),
            "matching_source_records": stats["matching_source_records"],
            "selected_records": len(selected),
            "skipped_identity": stats["skipped_identity"],
            "skipped_input": stats["skipped_input"],
            "precheck_status_counts": dict(sorted(stats["precheck_status_counts"].items())),
        }

    index = {
        "schema_version": PILOT_INDEX_SCHEMA_VERSION,
        "purpose": "non_releasing_input_status_pilot",
        "prompt_version": PILOT_PROMPT_VERSION,
        "source_path": str(source_path),
        "source_sha256": source_hasher.hexdigest(),
        "source_records": source_records,
        "source_candidate_hits": source_candidate_hits,
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha256(manifest_path),
        "label_definitions_path": str(label_definitions_path),
        "label_definitions_sha256": definitions_sha256,
        "max_per_label": max_per_label,
        "max_per_status": max_per_status,
        "labels": index_labels,
    }
    index_path = output_dir / "pilot.index.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "schema_version": "input-status-pilot-packet-report-v1",
        "output_dir": str(output_dir),
        "index_path": str(index_path),
        "labels": len(labels),
        "source_records": source_records,
        "source_candidate_hits": source_candidate_hits,
        "selected_records": selected_total,
    }
