"""Measure frozen knowledge-candidate packet coverage against approved gold corrections.

The evaluator is deliberately offline-only: it reads packet and gold rows supplied by
the caller and returns a JSON-serialisable report.  It neither calls a model nor
rewrites any source data.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import math
from statistics import fmean
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "knowledge-candidate-budget-coverage-v1"
_LOCATIONS = (
    "historical_target",
    "sibling",
    "type_retrieval",
    "other_candidate",
    "absent",
)
_IMMUTABLE_PACKET_FIELDS = (
    "source_line",
    "question_id",
    "parent_id",
    "canonical_label",
    "legacy_label",
)


@dataclass(frozen=True)
class _Alternative:
    label: str
    source: str
    definition: str | None


@dataclass(frozen=True)
class _PacketRow:
    review_id: str
    source_line: int
    question_id: str
    parent_id: str
    canonical_label: str
    legacy_label: str | None
    target_parent_path: str
    alternatives: tuple[_Alternative, ...]
    target_definition: str | None

    @property
    def immutable_identity(self) -> tuple[object, ...]:
        return (
            self.source_line,
            self.question_id,
            self.parent_id,
            self.canonical_label,
            self.legacy_label,
        )

    @property
    def definition_chars(self) -> int | None:
        if self.target_definition is None or any(
            alternative.definition is None for alternative in self.alternatives
        ):
            return None
        return len(self.target_definition) + sum(
            len(alternative.definition or "") for alternative in self.alternatives
        )


@dataclass(frozen=True)
class _GoldRecord:
    record_number: int
    review_id: str | None
    source_line: int
    question_id: str
    parent_id: str
    child_rank: int | None
    declared_historical_labels: tuple[str, ...]
    gold_labels: tuple[str, ...]


def _require_string(value: object, *, field: str, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: {field} must be a non-empty string")
    return value.strip()


def _optional_string(value: object, *, field: str, source: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field=field, source=source)


def _positive_int(value: object, *, field: str, source: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{source}: {field} must be a positive integer")
    return value


def _taxonomy_parent(label: str, *, field: str, source: str) -> str:
    if not label.startswith("知识点->"):
        raise ValueError(f"{source}: {field} must use a canonical '知识点->' path")
    parent, separator, leaf = label.rpartition("->")
    if not separator or not parent or not leaf:
        raise ValueError(f"{source}: {field} must be a terminal knowledge path")
    return parent


def _canonical_label(value: object, *, field: str, source: str) -> str:
    label = _require_string(value, field=field, source=source)
    _taxonomy_parent(label, field=field, source=source)
    return label


def _definition(value: object, *, field: str, source: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{source}: {field} must be a string when present")
    return value


def _packet_row(raw_row: Mapping[str, Any], *, source: str) -> _PacketRow:
    review_id = _require_string(raw_row.get("review_id"), field="review_id", source=source)
    source_line = _positive_int(raw_row.get("source_line"), field="source_line", source=source)
    question_id = _require_string(raw_row.get("question_id"), field="question_id", source=source)
    parent_id = _require_string(raw_row.get("parent_id"), field="parent_id", source=source)
    canonical_label = _canonical_label(
        raw_row.get("canonical_label"), field="canonical_label", source=source
    )
    target_parent_path = _taxonomy_parent(
        canonical_label, field="canonical_label", source=source
    )
    legacy_label = _optional_string(raw_row.get("legacy_label"), field="legacy_label", source=source)
    raw_alternatives = raw_row.get("alternative_labels")
    if not isinstance(raw_alternatives, list):
        raise ValueError(f"{source}: alternative_labels must be a list")
    alternatives: list[_Alternative] = []
    seen_labels: set[str] = set()
    for index, raw_alternative in enumerate(raw_alternatives, 1):
        alternative_source = f"{source}: alternative_labels[{index}]"
        if not isinstance(raw_alternative, Mapping):
            raise ValueError(f"{alternative_source} must be an object")
        label = _canonical_label(raw_alternative.get("label"), field="label", source=alternative_source)
        if label == canonical_label:
            raise ValueError(f"{alternative_source}: canonical_label must not repeat in alternatives")
        if label in seen_labels:
            raise ValueError(f"{alternative_source}: duplicate alternative label: {label}")
        seen_labels.add(label)
        alternatives.append(
            _Alternative(
                label=label,
                source=_require_string(raw_alternative.get("source"), field="source", source=alternative_source),
                definition=_definition(raw_alternative.get("definition"), field="definition", source=alternative_source),
            )
        )
    return _PacketRow(
        review_id=review_id,
        source_line=source_line,
        question_id=question_id,
        parent_id=parent_id,
        canonical_label=canonical_label,
        legacy_label=legacy_label,
        target_parent_path=target_parent_path,
        alternatives=tuple(alternatives),
        target_definition=_definition(raw_row.get("target_definition"), field="target_definition", source=source),
    )


def _index_packet_rows(
    packet_name: str, rows: Sequence[Mapping[str, object]]
) -> dict[str, _PacketRow]:
    indexed: dict[str, _PacketRow] = {}
    for index, raw_row in enumerate(rows, 1):
        source = f"packet {packet_name} row {index}"
        if not isinstance(raw_row, Mapping):
            raise ValueError(f"{source}: row must be an object")
        row = _packet_row(raw_row, source=source)
        if row.review_id in indexed:
            raise ValueError(f"{source}: duplicate review_id {row.review_id}")
        indexed[row.review_id] = row
    return indexed


def _historical_labels(raw_row: Mapping[str, Any], *, source: str) -> tuple[str, ...]:
    labels: list[str] = []
    scalar = raw_row.get("historical_label")
    if scalar is not None:
        labels.append(_require_string(scalar, field="historical_label", source=source))
    plural = raw_row.get("historical_labels")
    if plural is not None:
        if not isinstance(plural, list):
            raise ValueError(f"{source}: historical_labels must be a list when present")
        labels.extend(
            _require_string(value, field=f"historical_labels[{index}]", source=source)
            for index, value in enumerate(plural, 1)
        )
    if len(set(labels)) != len(labels):
        raise ValueError(f"{source}: declared historical labels must not contain duplicates")
    return tuple(labels)


def _gold_labels(raw_row: Mapping[str, Any], *, source: str) -> tuple[str, ...]:
    raw_labels = raw_row.get("gold_labels")
    if not isinstance(raw_labels, list):
        raise ValueError(f"{source}: gold_labels must be a list")
    labels = tuple(
        _canonical_label(value, field=f"gold_labels[{index}]", source=source)
        for index, value in enumerate(raw_labels, 1)
    )
    if len(set(labels)) != len(labels):
        raise ValueError(f"{source}: gold_labels must not contain duplicates")
    return labels


def _approved_gold_records(rows: Sequence[Mapping[str, object]]) -> tuple[list[_GoldRecord], int]:
    approved: list[_GoldRecord] = []
    skipped_unapproved = 0
    for index, raw_row in enumerate(rows, 1):
        source = f"gold row {index}"
        if not isinstance(raw_row, Mapping):
            raise ValueError(f"{source}: row must be an object")
        status = _require_string(
            raw_row.get("adjudication_status"), field="adjudication_status", source=source
        )
        if status != "approved":
            skipped_unapproved += 1
            continue
        child_rank = raw_row.get("child_rank")
        approved.append(
            _GoldRecord(
                record_number=index,
                review_id=_optional_string(raw_row.get("review_id"), field="review_id", source=source),
                source_line=_positive_int(raw_row.get("source_line"), field="source_line", source=source),
                question_id=_require_string(raw_row.get("question_id"), field="question_id", source=source),
                parent_id=_require_string(raw_row.get("parent_id"), field="parent_id", source=source),
                child_rank=(
                    None
                    if child_rank is None
                    else _positive_int(child_rank, field="child_rank", source=source)
                ),
                declared_historical_labels=_historical_labels(raw_row, source=source),
                gold_labels=_gold_labels(raw_row, source=source),
            )
        )
    return approved, skipped_unapproved


def _same_question_identity(packet: _PacketRow, gold: _GoldRecord) -> bool:
    return (
        packet.source_line == gold.source_line
        and packet.question_id == gold.question_id
        and packet.parent_id == gold.parent_id
    )


def _matches_declared_historical_label(packet: _PacketRow, label: str) -> bool:
    return label == packet.canonical_label or label == packet.legacy_label


def _join_gold_to_packets(
    packets: Mapping[str, _PacketRow], gold_records: Sequence[_GoldRecord]
) -> dict[str, _GoldRecord]:
    by_question: dict[tuple[int, str, str], list[_PacketRow]] = defaultdict(list)
    for packet in packets.values():
        by_question[(packet.source_line, packet.question_id, packet.parent_id)].append(packet)
    joined: dict[str, _GoldRecord] = {}
    for gold in gold_records:
        source = f"gold row {gold.record_number}"
        identity_key = (gold.source_line, gold.question_id, gold.parent_id)
        question_packets = by_question.get(identity_key, [])
        if gold.review_id is not None:
            packet = packets.get(gold.review_id)
            if packet is None:
                raise ValueError(f"{source}: review_id does not exist in frozen packets: {gold.review_id}")
            if not _same_question_identity(packet, gold):
                raise ValueError(f"{source}: review_id disagrees with question_id, parent_id, or source_line")
            candidate_packets = [packet]
        else:
            candidate_packets = list(question_packets)
        if not candidate_packets:
            raise ValueError(f"{source}: no frozen packet matches question identity")
        if gold.declared_historical_labels:
            available_labels = {
                label
                for packet in question_packets
                for label in (packet.canonical_label, packet.legacy_label)
                if label is not None
            }
            missing_declared = set(gold.declared_historical_labels) - available_labels
            if missing_declared:
                raise ValueError(
                    f"{source}: declared historical labels are absent from frozen packets: "
                    f"{sorted(missing_declared)}"
                )
            candidate_packets = [
                packet
                for packet in candidate_packets
                if any(
                    _matches_declared_historical_label(packet, label)
                    for label in gold.declared_historical_labels
                )
            ]
            if not candidate_packets:
                raise ValueError(f"{source}: declared historical label does not match selected review_id")
        for packet in candidate_packets:
            if packet.review_id in joined:
                previous = joined[packet.review_id]
                raise ValueError(
                    f"{source}: packet review_id {packet.review_id} already has approved gold "
                    f"from gold row {previous.record_number}"
                )
            joined[packet.review_id] = gold
    return joined


def _numeric_summary(values: Sequence[int]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "mean": None, "min": None, "p50": None, "p95": None, "max": None}
    ordered = sorted(values)

    def percentile(percent: float) -> int:
        rank = max(1, math.ceil(percent * len(ordered)))
        return ordered[rank - 1]

    return {
        "count": len(ordered),
        "mean": fmean(ordered),
        "min": ordered[0],
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "max": ordered[-1],
    }


class _Metrics:
    def __init__(self) -> None:
        self._packet_review_ids: set[str] = set()
        self._primary_packet_review_ids: set[str] = set()
        self._drop_required_review_ids: set[str] = set()
        self._candidate_counts: list[int] = []
        self._definition_chars: list[int] = []
        self._definition_unavailable_rows = 0
        self._all_locations: Counter[str] = Counter()
        self._primary_locations: Counter[str] = Counter()

    def add_packet(self, packet: _PacketRow, *, primary_correction: bool, drop_required: bool) -> None:
        if packet.review_id in self._packet_review_ids:
            return
        self._packet_review_ids.add(packet.review_id)
        self._candidate_counts.append(len(packet.alternatives))
        definition_chars = packet.definition_chars
        if definition_chars is None:
            self._definition_unavailable_rows += 1
        else:
            self._definition_chars.append(definition_chars)
        if primary_correction:
            self._primary_packet_review_ids.add(packet.review_id)
        if drop_required:
            self._drop_required_review_ids.add(packet.review_id)

    def add_label(self, location: str, *, primary: bool) -> None:
        if location not in _LOCATIONS:
            raise ValueError(f"unsupported gold-label location: {location}")
        if primary:
            self._primary_locations[location] += 1
        else:
            self._all_locations[location] += 1

    def report(self) -> dict[str, object]:
        return {
            "matched_packet_rows": len(self._packet_review_ids),
            "primary_correction_packet_rows": len(self._primary_packet_review_ids),
            "drop_required_packet_rows": len(self._drop_required_review_ids),
            "candidate_count": _numeric_summary(self._candidate_counts),
            "total_choice_count": _numeric_summary([count + 1 for count in self._candidate_counts]),
            "prompt_definition_chars": {
                "available_row_count": len(self._definition_chars),
                "unavailable_row_count": self._definition_unavailable_rows,
                **_numeric_summary(self._definition_chars),
            },
            "all_gold_label_coverage": _coverage_report(self._all_locations),
            "primary_correction_label_coverage": _coverage_report(self._primary_locations),
            "all_gold_label_instances": sum(self._all_locations.values()),
            "primary_correction_label_instances": sum(self._primary_locations.values()),
        }


def _coverage_report(counts: Mapping[str, int]) -> dict[str, object]:
    normalized = {location: counts.get(location, 0) for location in _LOCATIONS}
    total = sum(normalized.values())
    return {
        "label_instances": total,
        "counts": normalized,
        "rates": {
            location: (normalized[location] / total if total else None)
            for location in _LOCATIONS
        },
    }


def _gold_label_location(packet: _PacketRow, gold_label: str) -> str:
    if gold_label == packet.canonical_label:
        return "historical_target"
    for alternative in packet.alternatives:
        if alternative.label != gold_label:
            continue
        if alternative.source == "sibling":
            return "sibling"
        if alternative.source == "type_retrieval":
            return "type_retrieval"
        return "other_candidate"
    return "absent"


def _nested_reports(
    groups: Mapping[object, Mapping[str, _Metrics]]
) -> dict[str, object]:
    report: dict[str, object] = {}
    for raw_group, by_packet in sorted(groups.items(), key=lambda item: str(item[0])):
        if isinstance(raw_group, tuple):
            key = " × ".join(raw_group)
            dimensions: dict[str, str] = {
                "historical_target_parent": raw_group[0],
                "gold_parent": raw_group[1],
            }
        else:
            key = str(raw_group)
            dimensions = {}
        report[key] = {**dimensions, "packets": {name: metric.report() for name, metric in sorted(by_packet.items())}}
    return report


def analyze_candidate_budget_coverage(
    packet_sets: Mapping[str, Sequence[Mapping[str, object]]],
    gold_rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Compare >=2 frozen packet variants against approved multi-label gold sets.

    Gold rows use exact ``question_id``, ``parent_id`` and ``source_line`` identity.
    A question-level gold row can match every historical-label packet for that
    question.  If supplied, ``review_id``, ``historical_label`` and
    ``historical_labels`` further constrain the join using exact packet values.
    """
    if len(packet_sets) < 2:
        raise ValueError("candidate-budget coverage requires at least two named packet sets")
    if any(not isinstance(name, str) or not name.strip() for name in packet_sets):
        raise ValueError("every packet set requires a non-empty name")
    packet_indexes = {
        name: _index_packet_rows(name, rows)
        for name, rows in packet_sets.items()
    }
    first_name = next(iter(packet_indexes))
    reference = packet_indexes[first_name]
    expected_review_ids = set(reference)
    for packet_name, indexed in packet_indexes.items():
        if set(indexed) != expected_review_ids:
            raise ValueError(
                f"packet {packet_name} does not contain the same review_ids as packet {first_name}"
            )
        for review_id, reference_row in reference.items():
            if indexed[review_id].immutable_identity != reference_row.immutable_identity:
                raise ValueError(
                    f"packet {packet_name} disagrees on immutable identity for review_id {review_id}"
                )

    approved_gold, skipped_unapproved = _approved_gold_records(gold_rows)
    joined_gold = _join_gold_to_packets(reference, approved_gold)
    global_metrics = {name: _Metrics() for name in packet_indexes}
    by_historical_parent: dict[str, dict[str, _Metrics]] = defaultdict(dict)
    by_gold_parent: dict[str, dict[str, _Metrics]] = defaultdict(dict)
    by_parent_pair: dict[tuple[str, str], dict[str, _Metrics]] = defaultdict(dict)

    for review_id, gold in joined_gold.items():
        reference_packet = reference[review_id]
        gold_set = frozenset(gold.gold_labels)
        primary_correction = gold_set != frozenset({reference_packet.canonical_label})
        correction_labels = tuple(
            label for label in gold.gold_labels if label != reference_packet.canonical_label
        )
        drop_required = not gold.gold_labels
        labels_by_gold_parent: dict[str, list[str]] = defaultdict(list)
        for label in gold.gold_labels:
            labels_by_gold_parent[_taxonomy_parent(label, field="gold_labels", source="joined gold")].append(label)

        for packet_name, packet_rows in packet_indexes.items():
            packet = packet_rows[review_id]
            metric = global_metrics[packet_name]
            metric.add_packet(
                packet,
                primary_correction=primary_correction,
                drop_required=drop_required,
            )
            historical_metric = by_historical_parent[reference_packet.target_parent_path].setdefault(
                packet_name, _Metrics()
            )
            historical_metric.add_packet(
                packet,
                primary_correction=primary_correction,
                drop_required=drop_required,
            )
            for label in gold.gold_labels:
                location = _gold_label_location(packet, label)
                metric.add_label(location, primary=False)
                historical_metric.add_label(location, primary=False)
            for label in correction_labels:
                location = _gold_label_location(packet, label)
                metric.add_label(location, primary=True)
                historical_metric.add_label(location, primary=True)
            for gold_parent, labels in labels_by_gold_parent.items():
                primary_labels = [
                    label for label in labels if label != reference_packet.canonical_label
                ]
                gold_metric = by_gold_parent[gold_parent].setdefault(packet_name, _Metrics())
                pair_metric = by_parent_pair[(reference_packet.target_parent_path, gold_parent)].setdefault(
                    packet_name, _Metrics()
                )
                for group_metric in (gold_metric, pair_metric):
                    group_metric.add_packet(
                        packet,
                        primary_correction=bool(primary_labels),
                        drop_required=False,
                    )
                    for label in labels:
                        group_metric.add_label(_gold_label_location(packet, label), primary=False)
                    for label in primary_labels:
                        group_metric.add_label(_gold_label_location(packet, label), primary=True)

    primary_packet_rows = sum(
        frozenset(gold.gold_labels) != frozenset({reference[review_id].canonical_label})
        for review_id, gold in joined_gold.items()
    )
    primary_label_instances = sum(
        len([label for label in gold.gold_labels if label != reference[review_id].canonical_label])
        for review_id, gold in joined_gold.items()
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "packet_names": list(packet_indexes),
        "frozen_packet_review_ids": len(reference),
        "approved_gold_records": len(approved_gold),
        "skipped_unapproved_gold_records": skipped_unapproved,
        "matched_packet_rows": len(joined_gold),
        "primary_correction_packet_rows": primary_packet_rows,
        "primary_correction_label_instances": primary_label_instances,
        "gold_rows_with_child_rank": sum(record.child_rank is not None for record in approved_gold),
        "packets": {name: metric.report() for name, metric in global_metrics.items()},
        "by_historical_target_parent": _nested_reports(by_historical_parent),
        "by_gold_parent": _nested_reports(by_gold_parent),
        "by_historical_target_parent_and_gold_parent": _nested_reports(by_parent_pair),
    }
