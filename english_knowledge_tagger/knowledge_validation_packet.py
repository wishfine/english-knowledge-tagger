"""Build non-mutating validation packets for historical knowledge-point labels."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
from typing import Any, Mapping

from .knowledge_candidate_policy import KnowledgeCandidatePolicy, KnowledgeCandidateRule
from .knowledge_rulebook import KnowledgeRulebook
from .knowledge_taxonomy_migration import KnowledgeTaxonomyMigration
from .sft_labels import parse_sft_output_labels


_DECLARED_TYPE_METADATA = re.compile(r"(?m)^[ \t]*题型(?:结构|名称)为：[^\r\n]*(?:\r?\n|$)")


def _identifier(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _model_question_context(record: Mapping[str, Any]) -> str:
    """Remove source-declared type metadata after it has selected the candidate pool."""
    raw = record.get("input")
    if not isinstance(raw, str):
        return ""
    stripped = _DECLARED_TYPE_METADATA.sub("", raw)
    return re.sub(r"\n{3,}", "\n\n", stripped).strip()


def _canonical_knowledge_path(label: str) -> str:
    return "知识点->" + label.removeprefix("知识点@").replace("@", "->")


def _legacy_knowledge_paths(record: Mapping[str, Any]) -> tuple[str, ...]:
    parsed = parse_sft_output_labels(record.get("output"))
    if parsed is None:
        return ()
    knowledge_labels, _ = parsed
    return tuple(sorted(_canonical_knowledge_path(label) for label in knowledge_labels))


def _selected_routes(review_packet_path: Path) -> dict[int, tuple[str, str, str] | None]:
    selected: dict[int, tuple[str, str, str] | None] = {}
    with review_packet_path.open("r", encoding="utf-8") as packet:
        for packet_line, line in enumerate(packet, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"review packet line {packet_line} is not valid JSON") from error
            if not isinstance(row, dict) or not isinstance(row.get("source_line"), int):
                raise ValueError(f"review packet line {packet_line} must contain integer source_line")
            if row["source_line"] <= 0:
                raise ValueError(f"review packet line {packet_line} source_line must be positive")
            route_key = row.get("route_key")
            route: tuple[str, str, str] | None = None
            if isinstance(route_key, dict):
                values = (
                    route_key.get("scope"),
                    route_key.get("declared_type_structure"),
                    route_key.get("declared_type_name"),
                )
                if all(isinstance(value, str) and value.strip() for value in values):
                    route = (values[0].strip(), values[1].strip(), values[2].strip())
            if row["source_line"] in selected and selected[row["source_line"]] != route:
                raise ValueError(f"review packet has conflicting route_key for source_line {row['source_line']}")
            selected[row["source_line"]] = route
    return selected


def _validation_row(
    record: Mapping[str, Any],
    *,
    source_line: int,
    legacy_label: str,
    canonical_label: str,
    taxonomy_mapping_status: str,
    taxonomy_mapping_rule_id: str | None,
    rulebook: KnowledgeRulebook,
    candidate_rule: KnowledgeCandidateRule | None,
    shared_retrieved: tuple[Any, ...],
    shared_candidate_pool: Mapping[str, Any],
) -> dict[str, Any]:
    knowledge_policy = shared_candidate_pool["knowledge_policy"]
    validation_action = shared_candidate_pool["validation_action"]
    base: dict[str, Any] = {
        "schema_version": "knowledge-validation-packet-v1",
        "review_id": f"kp-validation:{_identifier(record.get('question_id')) or source_line}:{legacy_label}",
        "source_line": source_line,
        "question_id": _identifier(record.get("question_id")),
        "parent_id": _identifier(record.get("parent_id")),
        "is_sub_question": record.get("is_sub_question"),
        "question_context": _model_question_context(record),
        "legacy_label": legacy_label,
        "canonical_label": canonical_label,
        "taxonomy_mapping": {
            "status": taxonomy_mapping_status,
            "rule_id": taxonomy_mapping_rule_id,
        },
        "knowledge_policy": knowledge_policy,
        "validation_action": validation_action,
    }
    knowledge_record = rulebook.records.get(canonical_label)
    if knowledge_record is None:
        return {
            **base,
            "taxonomy_status": "unmapped_legacy_label",
            "target_definition": "",
            "alternative_labels": [],
            "candidate_pool": {"status": "not_applicable", "allowed_prefixes": []},
            "target_is_type_allowed": False,
        }
    if validation_action != "validate_with_model":
        return {
            **base,
            "taxonomy_status": "deprecated_legacy_label"
            if knowledge_record.status == "deprecated"
            else "known",
            "target_definition": "",
            "alternative_labels": [],
            "candidate_pool": dict(shared_candidate_pool),
            "target_is_type_allowed": False,
        }
    all_siblings = rulebook.direct_active_leaf_siblings(canonical_label)
    target_is_type_allowed = True
    if candidate_rule is not None:
        target_is_type_allowed = any(
            canonical_label == prefix or canonical_label.startswith(f"{prefix}->")
            for prefix in candidate_rule.allowed_knowledge_prefixes
        )
        type_allowed_siblings = tuple(
            candidate
            for candidate in all_siblings
            if any(
                candidate.path == prefix or candidate.path.startswith(f"{prefix}->")
                for prefix in candidate_rule.allowed_knowledge_prefixes
            )
        )
        if candidate_rule.sibling_selection == "all_direct_leaves":
            siblings = type_allowed_siblings
        else:
            sibling_limit = candidate_rule.max_sibling_candidates
            if sibling_limit is None:
                raise ValueError("limited sibling selection requires max_sibling_candidates")
            siblings = type_allowed_siblings[:sibling_limit]
    else:
        siblings = rulebook.nearby_active_records(canonical_label, limit=8)
    sibling_paths = frozenset(candidate.path for candidate in siblings)
    retrieved = tuple(
        candidate
        for candidate in shared_retrieved
        if candidate.path != canonical_label and candidate.path not in sibling_paths
    )
    return {
        **base,
        "taxonomy_status": "deprecated_legacy_label"
        if knowledge_record.status == "deprecated"
        else "known",
        "target_definition": knowledge_record.target_definition,
        "alternative_labels": [
            {
                "label": candidate.path,
                "definition": candidate.alternative_definition,
                "source": "sibling",
            }
            for candidate in siblings
        ]
        + [
            {
                "label": candidate.path,
                "definition": candidate.alternative_definition,
                "source": "type_retrieval",
            }
            for candidate in retrieved
        ],
        "candidate_pool": {
            **shared_candidate_pool,
            "direct_sibling_count": len(type_allowed_siblings)
            if candidate_rule is not None
            else len(all_siblings),
        },
        "target_is_type_allowed": target_is_type_allowed,
    }


def _shared_candidate_pool(
    record: Mapping[str, Any],
    *,
    rulebook: KnowledgeRulebook,
    candidate_policy: KnowledgeCandidatePolicy,
    route_key: tuple[str, str, str] | None,
) -> tuple[KnowledgeCandidateRule | None, tuple[Any, ...], dict[str, Any]]:
    """Retrieve one comparable, type-constrained shortlist for all labels on a question."""
    candidate_rule = candidate_policy.match(*route_key) if route_key is not None else None
    if candidate_rule is None:
        return None, (), {
            "status": "unconfigured",
            "knowledge_policy": "unresolved",
            "validation_action": "skip_policy_unresolved",
            "allowed_prefixes": [],
            "max_retrieved_candidates": 0,
            "max_sibling_candidates": 0,
            "sibling_selection": "none",
            "direct_sibling_count": 0,
            "max_output_labels": 0,
            "shared_retrieved_labels": [],
        }
    if candidate_rule.knowledge_policy in {"forbidden", "unresolved"}:
        return candidate_rule, (), {
            "status": candidate_rule.knowledge_policy,
            "knowledge_policy": candidate_rule.knowledge_policy,
            "validation_action": f"skip_policy_{candidate_rule.knowledge_policy}",
            "allowed_prefixes": [],
            "max_retrieved_candidates": 0,
            "max_sibling_candidates": 0,
            "sibling_selection": "none",
            "direct_sibling_count": 0,
            "max_output_labels": 0,
            "shared_retrieved_labels": [],
        }
    retrieved = rulebook.retrieve_active_records(
        prefixes=candidate_rule.allowed_knowledge_prefixes,
        query=_model_question_context(record),
        exclude_paths=frozenset(),
        limit=candidate_rule.max_retrieved_candidates,
    )
    return candidate_rule, retrieved, {
        "status": "configured",
        "knowledge_policy": candidate_rule.knowledge_policy,
        "validation_action": "validate_with_model",
        "allowed_prefixes": list(candidate_rule.allowed_knowledge_prefixes),
        "max_retrieved_candidates": candidate_rule.max_retrieved_candidates,
        "max_sibling_candidates": candidate_rule.max_sibling_candidates,
        "sibling_selection": candidate_rule.sibling_selection,
        "direct_sibling_count": 0,
        "max_output_labels": candidate_rule.max_output_labels,
        "shared_retrieved_labels": [candidate.path for candidate in retrieved],
    }


def build_knowledge_validation_packet(
    source_path: Path,
    *,
    review_packet_path: Path,
    rulebook: KnowledgeRulebook,
    candidate_policy: KnowledgeCandidatePolicy,
    taxonomy_migration: KnowledgeTaxonomyMigration | None = None,
    output_path: Path,
) -> dict[str, Any]:
    """Join selected source rows to their legacy knowledge labels and definitions."""
    if output_path.exists():
        raise FileExistsError(f"knowledge validation packet already exists: {output_path}")
    selected_routes = _selected_routes(review_packet_path)
    selected_lines = set(selected_routes)
    found_lines: set[int] = set()
    report_counts = Counter[str]()
    rows: list[dict[str, Any]] = []
    migration = taxonomy_migration or KnowledgeTaxonomyMigration(aliases=())
    with source_path.open("r", encoding="utf-8") as source:
        for source_line, line in enumerate(source, 1):
            if source_line not in selected_lines:
                continue
            found_lines.add(source_line)
            if not line.strip():
                report_counts["selected_blank_lines"] += 1
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                report_counts["selected_invalid_json_lines"] += 1
                continue
            if not isinstance(record, dict):
                report_counts["selected_non_object_records"] += 1
                continue
            labels = _legacy_knowledge_paths(record)
            if not labels:
                report_counts["selected_records_without_legacy_knowledge"] += 1
                continue
            candidate_rule, shared_retrieved, shared_candidate_pool = _shared_candidate_pool(
                record,
                rulebook=rulebook,
                candidate_policy=candidate_policy,
                route_key=selected_routes[source_line],
            )
            for legacy_label in labels:
                canonicalized = migration.canonicalize(legacy_label)
                row = _validation_row(
                    record,
                    source_line=source_line,
                    legacy_label=legacy_label,
                    canonical_label=canonicalized.canonical_path,
                    taxonomy_mapping_status=canonicalized.status,
                    taxonomy_mapping_rule_id=canonicalized.rule_id,
                    rulebook=rulebook,
                    candidate_rule=candidate_rule,
                    shared_retrieved=shared_retrieved,
                    shared_candidate_pool=shared_candidate_pool,
                )
                rows.append(row)
                report_counts[row["taxonomy_status"]] += 1
                report_counts[f"taxonomy_mapping:{canonicalized.status}"] += 1
                report_counts[f"validation_action:{row['validation_action']}"] += 1
                if (
                    row["validation_action"] == "validate_with_model"
                    and row["taxonomy_status"] == "known"
                ):
                    report_counts["model_validation_items"] += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    return {
        "schema_version": "knowledge-validation-packet-report-v1",
        "source_path": str(source_path),
        "review_packet_path": str(review_packet_path),
        "output_path": str(output_path),
        "selected_source_lines": len(selected_lines),
        "found_selected_source_lines": len(found_lines),
        "missing_selected_source_lines": len(selected_lines - found_lines),
        "known_validation_items": report_counts["known"],
        "deprecated_legacy_labels": report_counts["deprecated_legacy_label"],
        "unmapped_legacy_labels": report_counts["unmapped_legacy_label"],
        "selected_records_without_legacy_knowledge": report_counts[
            "selected_records_without_legacy_knowledge"
        ],
        "records": len(rows),
        "model_validation_items": report_counts["model_validation_items"],
        "policy_forbidden_items": report_counts["validation_action:skip_policy_forbidden"],
        "policy_unresolved_items": report_counts["validation_action:skip_policy_unresolved"],
        "taxonomy_mapping_counts": {
            "identity": report_counts["taxonomy_mapping:identity"],
            "prefix_alias": report_counts["taxonomy_mapping:prefix_alias"],
        },
    }
