"""Resolve blind human A/B reviews for a knowledge-tree definition ablation.

The review choice itself intentionally carries no meaning about a definition mode:
every reviewed row must be resolved through an explicit A/B mapping record.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Mapping, Sequence


_VALID_DECISIONS = {"A", "B", "both", "neither"}


@dataclass(frozen=True)
class _Option:
    mode: str
    label: str
    parent: str


@dataclass(frozen=True)
class _Mapping:
    option_a: _Option
    option_b: _Option


def _nonempty_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _field_values(row: Mapping[str, object], *, option: str, field: str) -> tuple[str, ...]:
    prefix = f"option_{option}"
    candidates: list[object] = [row.get(f"{prefix}_{field}")]
    if field == "label":
        candidates.extend(
            [row.get(f"{prefix}_candidate_label"), row.get(f"{prefix}_candidate_path")]
        )
    nested = row.get(prefix)
    if isinstance(nested, Mapping):
        candidates.append(nested.get(field))
        if field == "label":
            candidates.extend([nested.get("candidate_label"), nested.get("candidate_path")])
    return tuple(sorted({value for candidate in candidates if (value := _nonempty_string(candidate))}))


def _parent_path(label: str) -> str | None:
    parts = [part.strip() for part in label.split("->")]
    if len(parts) < 2 or any(not part for part in parts):
        return None
    return "->".join(parts[:-1])


def _parse_option(row: Mapping[str, object], *, option: str) -> tuple[_Option | None, str | None]:
    mode_values = _field_values(row, option=option, field="mode")
    label_values = _field_values(row, option=option, field="label")
    if len(mode_values) != 1:
        return None, f"option_{option}_mode must resolve to exactly one non-empty value"
    if len(label_values) != 1:
        return None, f"option_{option}_label must resolve to exactly one non-empty exact path"
    parent = _parent_path(label_values[0])
    if parent is None:
        return None, f"option_{option}_label must be a non-root hierarchical path"
    return _Option(mode=mode_values[0], label=label_values[0], parent=parent), None


def _mapping_from_row(row: Mapping[str, object]) -> tuple[_Mapping | None, str | None]:
    option_a, error_a = _parse_option(row, option="a")
    option_b, error_b = _parse_option(row, option="b")
    if error_a or error_b:
        return None, "; ".join(error for error in (error_a, error_b) if error is not None)
    assert option_a is not None and option_b is not None
    return _Mapping(option_a=option_a, option_b=option_b), None


def _error(review_id: str | None, code: str, message: str) -> dict[str, object]:
    result: dict[str, object] = {"code": code, "message": message}
    if review_id is not None:
        result["review_id"] = review_id
    return result


def _decision(value: object) -> str | None:
    raw = _nonempty_string(value)
    if raw is None:
        return None
    normalized = raw.lower()
    if normalized in {"a", "b"}:
        return normalized.upper()
    return normalized if normalized in _VALID_DECISIONS else None


def _option_summary(
    counts: Mapping[tuple[str, str, str], Counter[str]], *, mode: str
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    label_rows: list[dict[str, object]] = []
    parent_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for (entry_mode, label, parent), entry in counts.items():
        if entry_mode != mode:
            continue
        label_rows.append(
            {
                "candidate_label": label,
                "candidate_parent": parent,
                "correct_option_assignments": entry["correct"],
                "single_option_assignments": entry["single"],
                "both_option_assignments": entry["both"],
                "review_ids": sorted(entry.get("review_ids", set())),
            }
        )
        parent_counts[parent].update(
            {
                "correct": entry["correct"],
                "single": entry["single"],
                "both": entry["both"],
            }
        )
    label_rows.sort(key=lambda row: (-int(row["correct_option_assignments"]), str(row["candidate_label"])))
    parents = [
        {
            "candidate_parent": parent,
            "correct_option_assignments": entry["correct"],
            "single_option_assignments": entry["single"],
            "both_option_assignments": entry["both"],
        }
        for parent, entry in parent_counts.items()
    ]
    parents.sort(key=lambda row: (-int(row["correct_option_assignments"]), str(row["candidate_parent"])))
    return label_rows, parents


def summarize_definition_ablation_reviews(
    mapping_rows: Sequence[Mapping[str, object]], review_rows: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    """Resolve blind A/B decisions through explicit mapping rows and summarize their winners.

    Mapping rows must provide a ``review_id`` and both option values.  The flat
    schema is ``option_a_mode``, ``option_a_label``, ``option_b_mode`` and
    ``option_b_label``.  Nested ``option_a``/``option_b`` objects with
    ``mode`` and ``label`` are also accepted.  A/B never imply a mode by
    position; a missing or ambiguous mapping is left unresolved.
    """
    errors: list[dict[str, object]] = []
    mapping_candidates: dict[str, list[_Mapping | None]] = defaultdict(list)
    invalid_mapping_ids: set[str] = set()
    for line_number, row in enumerate(mapping_rows, 1):
        review_id = _nonempty_string(row.get("review_id"))
        if review_id is None:
            errors.append(
                _error(None, "mapping_missing_review_id", f"mapping row {line_number} has no review_id")
            )
            continue
        parsed, parse_error = _mapping_from_row(row)
        mapping_candidates[review_id].append(parsed)
        if parse_error is not None:
            invalid_mapping_ids.add(review_id)
            errors.append(_error(review_id, "invalid_mapping", parse_error))

    mappings: dict[str, _Mapping] = {}
    ambiguous_mapping_ids: set[str] = set()
    for review_id, candidates in sorted(mapping_candidates.items()):
        if len(candidates) != 1:
            ambiguous_mapping_ids.add(review_id)
            errors.append(
                _error(
                    review_id,
                    "duplicate_mapping",
                    "more than one mapping row exists; A/B mode assignment is ambiguous",
                )
            )
            continue
        if review_id not in invalid_mapping_ids and candidates[0] is not None:
            mappings[review_id] = candidates[0]

    review_candidates: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for line_number, row in enumerate(review_rows, 1):
        review_id = _nonempty_string(row.get("review_id"))
        if review_id is None:
            errors.append(
                _error(None, "review_missing_review_id", f"review row {line_number} has no review_id")
            )
            continue
        review_candidates[review_id].append(row)

    option_counts: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
    decision_counts: Counter[str] = Counter()
    resolved_details: list[dict[str, object]] = []
    resolved = 0
    correct_assignments = 0
    both_reviews = 0
    neither_reviews = 0
    single_reviews = 0
    for review_id, candidates in sorted(review_candidates.items()):
        if len(candidates) != 1:
            errors.append(
                _error(
                    review_id,
                    "duplicate_review",
                    "more than one human review exists; no decision was selected",
                )
            )
            continue
        row = candidates[0]
        decision = _decision(row.get("review_decision"))
        if decision is None:
            errors.append(
                _error(
                    review_id,
                    "invalid_review_decision",
                    "review_decision must be one of A, B, both, neither",
                )
            )
            continue
        if review_id in ambiguous_mapping_ids:
            errors.append(
                _error(
                    review_id,
                    "ambiguous_mapping",
                    "review cannot be resolved because its mapping has duplicate rows",
                )
            )
            continue
        if review_id in invalid_mapping_ids:
            errors.append(
                _error(
                    review_id,
                    "invalid_mapping",
                    "review cannot be resolved because its option mapping is invalid",
                )
            )
            continue
        mapping = mappings.get(review_id)
        if mapping is None:
            errors.append(
                _error(
                    review_id,
                    "missing_mapping",
                    "review has no explicit A/B mode-and-label mapping",
                )
            )
            continue

        decision_counts[decision] += 1
        resolved += 1
        selected: tuple[tuple[str, _Option], ...]
        if decision == "A":
            selected = (("A", mapping.option_a),)
            single_reviews += 1
        elif decision == "B":
            selected = (("B", mapping.option_b),)
            single_reviews += 1
        elif decision == "both":
            selected = (("A", mapping.option_a), ("B", mapping.option_b))
            both_reviews += 1
        else:
            selected = ()
            neither_reviews += 1

        selected_details: list[dict[str, str]] = []
        for option_name, option in selected:
            entry = option_counts[(option.mode, option.label, option.parent)]
            entry["correct"] += 1
            entry["both" if decision == "both" else "single"] += 1
            review_ids = entry.setdefault("review_ids", set())
            assert isinstance(review_ids, set)
            review_ids.add(review_id)
            correct_assignments += 1
            selected_details.append(
                {
                    "option": option_name,
                    "mode": option.mode,
                    "candidate_label": option.label,
                    "candidate_parent": option.parent,
                }
            )
        detail: dict[str, object] = {
            "review_id": review_id,
            "review_decision": decision,
            "selected_options": selected_details,
        }
        evidence = _nonempty_string(row.get("review_evidence"))
        if evidence is not None:
            detail["review_evidence"] = evidence
        resolved_details.append(detail)

    modes = sorted({mode for mode, _, _ in option_counts})
    by_mode: list[dict[str, object]] = []
    for mode in modes:
        label_rows, parent_rows = _option_summary(option_counts, mode=mode)
        by_mode.append(
            {
                "mode": mode,
                "correct_option_assignments": sum(
                    int(row["correct_option_assignments"]) for row in label_rows
                ),
                "single_option_assignments": sum(
                    int(row["single_option_assignments"]) for row in label_rows
                ),
                "both_option_assignments": sum(
                    int(row["both_option_assignments"]) for row in label_rows
                ),
                "candidate_labels": label_rows,
                "candidate_parents": parent_rows,
            }
        )

    return {
        "schema_version": "knowledge-tree-definition-review-analysis-v1",
        "mapping_rows": len(mapping_rows),
        "review_rows": len(review_rows),
        "resolved_reviews": resolved,
        "review_decision_counts": {
            decision: decision_counts[decision] for decision in ("A", "B", "both", "neither") if decision_counts[decision]
        },
        "correct_option_assignments": correct_assignments,
        "single_option_reviews": single_reviews,
        "both_reviews": both_reviews,
        "neither_reviews": neither_reviews,
        "by_mode": by_mode,
        "resolved_review_details": resolved_details,
        "unresolved_mapping_errors": errors,
    }
