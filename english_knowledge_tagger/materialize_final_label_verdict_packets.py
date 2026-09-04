"""Materialize full-label DS verdict packets with v3 source records."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "final-label-verdict-packet-v1"
_PACKET_INDEX = re.compile(r"^(\d{3})-")


def _identity(row: Mapping[str, object]) -> tuple[str, str, bool] | None:
    question_id = row.get("question_id")
    parent_id = row.get("parent_id")
    is_sub_question = row.get("is_sub_question")
    if not isinstance(question_id, str) or not question_id.strip():
        return None
    if not isinstance(parent_id, str) or not parent_id.strip():
        return None
    if not isinstance(is_sub_question, bool):
        return None
    return question_id.strip(), parent_id.strip(), is_sub_question


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_label_filename(index: int, label: str) -> str:
    return f"劣质-{index:03d}-{label.replace('/', '／')}.jsonl"


def _read_packet_label(path: Path) -> str:
    with path.open(encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, Mapping) or not isinstance(row.get("verify_label"), str):
                raise ValueError(f"packet has no verify_label: {path}")
            return row["verify_label"].strip()
    raise ValueError(f"packet is empty: {path}")


def _packet_index(path: Path) -> int | None:
    match = _PACKET_INDEX.match(path.name)
    return int(match.group(1)) if match else None


def _write(handle: Any, row: Mapping[str, object]) -> None:
    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def materialize_final_label_verdict_packets(
    *,
    packet_dir: Path,
    evidence_dir: Path,
    source_path: Path,
    processed_dir: Path,
    issue_dir: Path,
    processed_labels: Iterable[str],
    issue_labels: Iterable[str],
    report_path: Path,
) -> dict[str, object]:
    """Join every DS verdict to its v3 source row without modifying source files."""
    if not packet_dir.is_dir():
        raise FileNotFoundError(f"packet directory not found: {packet_dir}")
    if not evidence_dir.is_dir():
        raise FileNotFoundError(f"evidence directory not found: {evidence_dir}")
    if not source_path.is_file():
        raise FileNotFoundError(f"v3 source not found: {source_path}")
    if report_path.exists():
        raise FileExistsError(f"refusing to overwrite report: {report_path}")

    processed_values = tuple(processed_labels)
    issue_values = tuple(issue_labels)
    destinations: dict[str, Path] = {}
    for label in processed_values:
        destinations[label.strip()] = processed_dir
    for label in issue_values:
        value = label.strip()
        if value in destinations:
            raise ValueError(f"label appears in both destinations: {value}")
        destinations[value] = issue_dir
    if not destinations:
        raise ValueError("at least one destination label is required")
    if any(not label.startswith("知识点@") for label in destinations):
        raise ValueError("destination labels must be rendered 知识点@ labels")

    packet_paths = sorted(packet_dir.glob("*.final.packet.jsonl"))
    if not packet_paths:
        raise ValueError(f"no .final.packet.jsonl files found in {packet_dir}")
    packet_by_label: dict[str, Path] = {}
    packet_order: dict[str, int] = {}
    evidence_by_identity: dict[tuple[str, str, bool], list[dict[str, object]]] = defaultdict(list)
    counts: dict[str, Counter[str]] = {label: Counter() for label in destinations}
    evidence_files: dict[str, Path] = {}

    for packet_path in packet_paths:
        label = _read_packet_label(packet_path)
        if label not in destinations:
            continue
        if label in packet_by_label:
            raise ValueError(f"duplicate packet label: {label}")
        packet_by_label[label] = packet_path
        packet_order[label] = _packet_index(packet_path) or 0
        evidence_path = evidence_dir / f"{packet_path.name.removesuffix('.final.packet.jsonl')}.evidence.jsonl"
        if not evidence_path.is_file():
            raise FileNotFoundError(f"evidence file not found for {label}: {evidence_path}")
        evidence_files[label] = evidence_path

        with evidence_path.open(encoding="utf-8") as evidence_source:
            for line_number, line in enumerate(evidence_source, 1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, Mapping):
                    raise ValueError(f"{evidence_path} line {line_number}: row must be an object")
                evidence = dict(row)
                evidence_label = evidence.get("legacy_label") or evidence.get("verify_label")
                if evidence_label is not None and evidence_label != label:
                    raise ValueError(
                        f"{evidence_path} line {line_number}: label differs from packet label"
                    )
                evidence["legacy_label"] = label
                identity = _identity(evidence)
                if identity is None:
                    counts[label]["evidence_identity_invalid"] += 1
                    continue
                evidence["_materialize_label"] = label
                evidence_by_identity[identity].append(evidence)
                counts[label]["evidence_records"] += 1
                status = str(evidence.get("status") or "missing")
                counts[label][f"status:{status}"] += 1
                if evidence.get("llm_match") is True:
                    counts[label]["match_true"] += 1
                elif evidence.get("llm_match") is False:
                    counts[label]["match_false"] += 1
                else:
                    counts[label]["match_null"] += 1

    missing_labels = sorted(set(destinations) - set(packet_by_label))
    if missing_labels:
        raise ValueError("requested labels have no packet: " + ", ".join(missing_labels))

    for label, directory in destinations.items():
        directory.mkdir(parents=True, exist_ok=True)
    output_paths: dict[str, Path] = {}
    used_indices: set[int] = set()
    next_index = 1
    for label in sorted(destinations):
        index = packet_order[label]
        if index <= 0 or index in used_indices:
            while next_index in used_indices:
                next_index += 1
            index = next_index
        used_indices.add(index)
        output_path = destinations[label] / _safe_label_filename(index, label)
        if output_path.exists():
            raise FileExistsError(f"refusing to overwrite packet: {output_path}")
        output_paths[label] = output_path

    handles = {label: path.open("x", encoding="utf-8") for label, path in output_paths.items()}
    seen_source: set[tuple[str, str, bool]] = set()
    source_records = 0
    source_digest = hashlib.sha256()
    missing_identities: set[tuple[str, str, bool]] = set(evidence_by_identity)
    duplicate_identities: set[tuple[str, str, bool]] = set()
    try:
        with source_path.open("rb") as source:
            for source_line, raw_line in enumerate(source, 1):
                source_digest.update(raw_line)
                if not raw_line.strip():
                    continue
                source_records += 1
                source_row = json.loads(raw_line)
                if not isinstance(source_row, Mapping):
                    raise ValueError(f"source line {source_line}: row must be an object")
                identity = _identity(source_row)
                if identity is None or identity not in evidence_by_identity:
                    continue
                if identity in seen_source:
                    duplicate_identities.add(identity)
                    continue
                seen_source.add(identity)
                missing_identities.discard(identity)
                for evidence in evidence_by_identity[identity]:
                    label = str(evidence["_materialize_label"])
                    evidence_payload = dict(evidence)
                    evidence_payload.pop("_materialize_label", None)
                    output_row = {
                        "schema_version": SCHEMA_VERSION,
                        "status": evidence.get("status") or "missing",
                        "llm_match": evidence.get("llm_match"),
                        "confidence": evidence.get("confidence"),
                        "reason": evidence.get("reason"),
                        "verify_label": label,
                        "canonical_label": evidence.get("canonical_label"),
                        "question_id": identity[0],
                        "parent_id": identity[1],
                        "is_sub_question": identity[2],
                        "source_version": "v3",
                        "ds_source_version": "v2",
                        "source_line_v3": source_line,
                        "source_path_v3": str(source_path),
                        "evidence": evidence_payload,
                        "source_record": dict(source_row),
                    }
                    _write(handles[label], output_row)
                    counts[label]["joined_records"] += 1
    finally:
        for handle in handles.values():
            handle.close()

    holds_path = report_path.with_suffix(".holds.jsonl")
    if holds_path.exists():
        raise FileExistsError(f"refusing to overwrite holds: {holds_path}")
    holds_path.parent.mkdir(parents=True, exist_ok=True)
    with holds_path.open("x", encoding="utf-8") as holds:
        for identity in sorted(missing_identities):
            labels = sorted({str(row["_materialize_label"]) for row in evidence_by_identity[identity]})
            _write(holds, {
                "schema_version": "final-label-verdict-packet-hold-v1",
                "hold_reason": "v3_source_identity_missing",
                "question_id": identity[0],
                "parent_id": identity[1],
                "is_sub_question": identity[2],
                "labels": labels,
            })
        for identity in sorted(duplicate_identities):
            labels = sorted({str(row["_materialize_label"]) for row in evidence_by_identity[identity]})
            _write(holds, {
                "schema_version": "final-label-verdict-packet-hold-v1",
                "hold_reason": "v3_source_identity_duplicate",
                "question_id": identity[0],
                "parent_id": identity[1],
                "is_sub_question": identity[2],
                "labels": labels,
            })

    report = {
        "schema_version": "final-label-verdict-packets-report-v1",
        "packet_dir": str(packet_dir),
        "evidence_dir": str(evidence_dir),
        "source_path_v3": str(source_path),
        "source_sha256_v3": source_digest.hexdigest(),
        "source_records_v3": source_records,
        "ds_source_version": "v2",
        "materialized_source_version": "v3",
        "processed_labels": sorted(processed_values),
        "issue_labels": sorted(issue_values),
        "labels": {
            label: {
                "packet_path": str(packet_by_label[label]),
                "evidence_path": str(evidence_files[label]),
                "output_path": str(output_paths[label]),
                "counts": dict(sorted(counts[label].items())),
            }
            for label in sorted(destinations)
        },
        "total_evidence_records": sum(c["evidence_records"] for c in counts.values()),
        "total_joined_records": sum(c["joined_records"] for c in counts.values()),
        "missing_v3_identity_count": len(missing_identities),
        "duplicate_v3_identity_count": len(duplicate_identities),
        "holds_path": str(holds_path),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report
