"""One-pass materialization of final discriminator packets for candidate labels."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from .candidate_route_guidance import (
    CandidateRouteGuidance,
    LabelRouteGuidance,
    load_candidate_route_guidance,
)
from .final_label_discriminator import (
    FINAL_PACKET_SCHEMA_VERSION,
    FINAL_PROMPT_VERSION,
    clean_final_label_question,
)
from .knowledge_rulebook import KnowledgeRulebook
from .mentor_direct_rollout import load_mentor_label_definitions
from .sft_labels import parse_sft_output_labels


BATCH_SCHEMA_VERSION = "candidate-final-packet-batch-v1"
_TYPE_METADATA = re.compile(r"(?m)^\s*题型(结构|名称)为：([^\r\n]*)")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _route_key(record: Mapping[str, Any]) -> dict[str, str | None]:
    input_text = record.get("input")
    parsed = {
        match.group(1): match.group(2).strip()
        for match in _TYPE_METADATA.finditer(input_text if isinstance(input_text, str) else "")
    }
    return {
        "scope": "child" if record.get("is_sub_question") is True else "parent",
        "declared_type_structure": parsed.get("结构") or None,
        "declared_type_name": parsed.get("名称") or None,
    }


def _route_name(route_key: Mapping[str, str | None]) -> str:
    return " × ".join(
        (
            route_key["scope"] or "<missing>",
            route_key["declared_type_structure"] or "<missing>",
            route_key["declared_type_name"] or "<missing>",
        )
    )


def _required_identity(record: Mapping[str, Any]) -> tuple[str, str, bool] | None:
    question_id = record.get("question_id")
    parent_id = record.get("parent_id")
    is_sub_question = record.get("is_sub_question")
    if (
        not isinstance(question_id, str)
        or not question_id.strip()
        or not isinstance(parent_id, str)
        or not parent_id.strip()
        or not isinstance(is_sub_question, bool)
    ):
        return None
    return question_id.strip(), parent_id.strip(), is_sub_question


def _packet_filename(index: int, legacy_label: str) -> str:
    digest = hashlib.sha256(legacy_label.encode("utf-8")).hexdigest()[:12]
    return f"{index:03d}-{digest}.final.packet.jsonl"


def _initial_counts(guidance: LabelRouteGuidance, relative_path: str) -> dict[str, object]:
    return {
        "canonical_label": guidance.canonical_label,
        "guidance_mode": guidance.mode,
        "allowed_routes": list(guidance.allowed_routes),
        "packet_relative_path": relative_path,
        "matching_source_records": 0,
        "selected_packet_records": 0,
        "hard_route_hold_records": 0,
        "input_incomplete_hold_records": 0,
        "identity_invalid_hold_records": 0,
        "route_counts": Counter(),
        "selected_route_counts": Counter(),
        "hard_route_hold_route_counts": Counter(),
    }


def _serialise_counts(counts: Mapping[str, object]) -> dict[str, object]:
    counter_keys = ("route_counts", "selected_route_counts", "hard_route_hold_route_counts")
    result = {key: value for key, value in counts.items() if key not in counter_keys}
    for key in counter_keys:
        result[key] = dict(sorted(counts[key].items()))  # type: ignore[index,union-attr]
    return result


def _validate_definitions(
    guidance: CandidateRouteGuidance, *, label_definitions_path: Path
) -> tuple[dict[str, Mapping[str, Any]], str]:
    definitions = load_mentor_label_definitions(label_definitions_path)
    missing = sorted(set(guidance.labels) - set(definitions))
    if missing:
        raise ValueError(
            "candidate final packet batch has labels missing from label definitions: "
            + ", ".join(missing)
        )
    return definitions, _sha256(label_definitions_path)


def build_candidate_final_packet_batch(
    source_path: Path,
    *,
    manifest_path: Path,
    guidance_path: Path,
    rulebook: KnowledgeRulebook,
    label_definitions_path: Path,
    output_dir: Path,
) -> dict[str, object]:
    """Build every candidate packet in one scan without changing source JSONL."""
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing output directory: {output_dir}")
    guidance = load_candidate_route_guidance(
        guidance_path, manifest_path=manifest_path, rulebook=rulebook
    )
    _, definitions_sha256 = _validate_definitions(
        guidance, label_definitions_path=label_definitions_path
    )

    packets_dir = output_dir / "packets"
    output_dir.mkdir(parents=True)
    packets_dir.mkdir()
    ordered_labels = tuple(guidance.labels)
    counts: dict[str, dict[str, object]] = {}
    writers: dict[str, Any] = {}
    source_records = 0
    source_candidate_hits = 0
    source_hasher = hashlib.sha256()
    try:
        for index, legacy_label in enumerate(ordered_labels, 1):
            relative_path = str(Path("packets") / _packet_filename(index, legacy_label))
            counts[legacy_label] = _initial_counts(
                guidance.mode_for(legacy_label), relative_path
            )
            writers[legacy_label] = (output_dir / relative_path).open("x", encoding="utf-8")

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
                parsed_labels = parse_sft_output_labels(record.get("output"))
                if parsed_labels is None:
                    continue
                historical_labels, _ = parsed_labels
                matching_labels = tuple(label for label in ordered_labels if label in historical_labels)
                if not matching_labels:
                    continue
                source_candidate_hits += len(matching_labels)
                route_key = _route_key(record)
                route = _route_name(route_key)
                identity = _required_identity(record)
                question_text: str | None
                try:
                    question_text = clean_final_label_question(record.get("input"))
                except ValueError:
                    question_text = None
                for legacy_label in matching_labels:
                    label_counts = counts[legacy_label]
                    label_counts["matching_source_records"] += 1  # type: ignore[operator]
                    label_counts["route_counts"][route] += 1  # type: ignore[index,operator]
                    route_guidance = guidance.mode_for(legacy_label)
                    if (
                        route_guidance.mode == "hard_exclusive"
                        and route not in route_guidance.allowed_routes
                    ):
                        label_counts["hard_route_hold_records"] += 1  # type: ignore[operator]
                        label_counts["hard_route_hold_route_counts"][route] += 1  # type: ignore[index,operator]
                        continue
                    if identity is None:
                        label_counts["identity_invalid_hold_records"] += 1  # type: ignore[operator]
                        continue
                    if question_text is None:
                        label_counts["input_incomplete_hold_records"] += 1  # type: ignore[operator]
                        continue
                    question_id, parent_id, is_sub_question = identity
                    packet_path = output_dir / label_counts["packet_relative_path"]  # type: ignore[operator]
                    packet_row = {
                        "schema_version": FINAL_PACKET_SCHEMA_VERSION,
                        "review_id": f"{FINAL_PROMPT_VERSION}:{source_line}:{legacy_label}",
                        "question_id": question_id,
                        "parent_id": parent_id,
                        "source_line": source_line,
                        "is_sub_question": is_sub_question,
                        "route_key": route_key,
                        "verify_label": legacy_label,
                        "question_text": question_text,
                        "source_packet_path": str(packet_path),
                        "source_path": str(source_path),
                        "label_definitions_path": str(label_definitions_path),
                        "label_definitions_sha256": definitions_sha256,
                    }
                    writers[legacy_label].write(
                        json.dumps(packet_row, ensure_ascii=False, sort_keys=True) + "\n"
                    )
                    label_counts["selected_packet_records"] += 1  # type: ignore[operator]
                    label_counts["selected_route_counts"][route] += 1  # type: ignore[index,operator]
    finally:
        for writer in writers.values():
            writer.close()

    index = {
        "schema_version": BATCH_SCHEMA_VERSION,
        "purpose": "non_releasing_final_discriminator_packet_materialization",
        "prompt_version": FINAL_PROMPT_VERSION,
        "source_path": str(source_path),
        "source_sha256": source_hasher.hexdigest(),
        "source_records": source_records,
        "source_candidate_hits": source_candidate_hits,
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha256(manifest_path),
        "guidance_path": str(guidance_path),
        "guidance_sha256": _sha256(guidance_path),
        "label_definitions_path": str(label_definitions_path),
        "label_definitions_sha256": definitions_sha256,
        "labels": {label: _serialise_counts(details) for label, details in counts.items()},
    }
    index_path = output_dir / "batch.index.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "schema_version": "candidate-final-packet-batch-report-v1",
        "output_dir": str(output_dir),
        "index_path": str(index_path),
        "candidate_labels": len(counts),
        "source_records": source_records,
        "source_candidate_hits": source_candidate_hits,
        "selected_packet_records": sum(
            int(details["selected_packet_records"]) for details in counts.values()
        ),
    }
