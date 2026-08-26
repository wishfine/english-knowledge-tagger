"""Exact small-question routes to allowed knowledge-point candidate pools."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "knowledge-candidate-policy-v1"
SCOPES = frozenset({"parent", "child", "unknown"})
KNOWLEDGE_POLICIES = frozenset({"forbidden", "optional", "required", "unresolved"})
SIBLING_SELECTIONS = frozenset({"limited_direct_leaves", "all_direct_leaves", "none"})


@dataclass(frozen=True)
class KnowledgeCandidateRule:
    """A bounded candidate pool for one exact source-declared question route."""

    scope: str
    declared_type_structure: str
    declared_type_name: str
    allowed_knowledge_prefixes: tuple[str, ...]
    max_retrieved_candidates: int
    max_sibling_candidates: int | None
    max_output_labels: int
    knowledge_policy: str
    sibling_selection: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.scope, self.declared_type_structure, self.declared_type_name)


@dataclass(frozen=True)
class KnowledgeCandidatePolicy:
    """Exact-match policy; a missing rule must not borrow a parent label pool."""

    rules: Mapping[tuple[str, str, str], KnowledgeCandidateRule]

    def match(self, scope: str, structure: str, name: str) -> KnowledgeCandidateRule | None:
        return self.rules.get((scope, structure, name))


def _nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"knowledge candidate rule {field} must be a non-empty string")
    return value.strip()


def _positive_int(value: object, field: str, *, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0 or value > maximum:
        raise ValueError(f"knowledge candidate rule {field} must be an integer from 1 to {maximum}")
    return value


def _prefixes(value: object, *, policy: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(
            f"knowledge candidate rule {policy} requires a non-empty "
            "allowed_knowledge_prefixes list"
        )
    prefixes = tuple(_nonempty_string(item, "allowed_knowledge_prefixes") for item in value)
    if len(set(prefixes)) != len(prefixes):
        raise ValueError("knowledge candidate rule allowed_knowledge_prefixes contains duplicates")
    if any(not prefix.startswith("知识点->") for prefix in prefixes):
        raise ValueError("knowledge candidate rule prefixes must use canonical '知识点->' paths")
    return prefixes


def _empty_pool_value(value: object, field: str, *, policy: str) -> int:
    if value is None:
        return 0
    if isinstance(value, int) and not isinstance(value, bool) and value == 0:
        return 0
    raise ValueError(f"knowledge candidate rule {policy} requires {field} to be omitted or 0")


def _empty_prefixes(value: object, *, policy: str) -> tuple[str, ...]:
    if value is None or value == []:
        return ()
    raise ValueError(
        f"knowledge candidate rule {policy} requires allowed_knowledge_prefixes to be omitted or []"
    )


def _sibling_selection(value: object, *, uses_candidate_pool: bool) -> str:
    if not uses_candidate_pool:
        if value is None or value == "none":
            return "none"
        raise ValueError("knowledge candidate rule without a candidate pool requires sibling_selection none")
    if value is None:
        return "limited_direct_leaves"
    if not isinstance(value, str) or value not in {
        "limited_direct_leaves",
        "all_direct_leaves",
    }:
        raise ValueError(
            "knowledge candidate rule sibling_selection must be limited_direct_leaves "
            "or all_direct_leaves"
        )
    return value


def _sibling_limit(value: object, *, selection: str, policy: str) -> int | None:
    if selection == "all_direct_leaves":
        if value is None:
            return None
        raise ValueError(
            f"knowledge candidate rule {policy} with all_direct_leaves must omit "
            "max_sibling_candidates"
        )
    if selection == "limited_direct_leaves":
        return _positive_int(value, "max_sibling_candidates", maximum=8)
    return _empty_pool_value(value, "max_sibling_candidates", policy=policy)


def load_knowledge_candidate_policy(path: Path) -> KnowledgeCandidatePolicy:
    """Load a versioned, exact-match candidate pool policy JSON file."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"knowledge candidate policy is not valid JSON: {path}") from error
    if not isinstance(payload, Mapping) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"knowledge candidate policy schema_version must be {SCHEMA_VERSION!r}")
    raw_rules = payload.get("rules")
    if not isinstance(raw_rules, list):
        raise ValueError("knowledge candidate policy rules must be a list")
    rules: dict[tuple[str, str, str], KnowledgeCandidateRule] = {}
    for raw_rule in raw_rules:
        if not isinstance(raw_rule, Mapping):
            raise ValueError("each knowledge candidate rule must be an object")
        knowledge_policy = _nonempty_string(
            raw_rule.get("knowledge_policy", "required"), "knowledge_policy"
        )
        if knowledge_policy not in KNOWLEDGE_POLICIES:
            raise ValueError(f"knowledge candidate rule has unsupported knowledge_policy: {knowledge_policy}")
        uses_candidate_pool = knowledge_policy in {"optional", "required"}
        sibling_selection = _sibling_selection(
            raw_rule.get("sibling_selection"), uses_candidate_pool=uses_candidate_pool
        )
        rule = KnowledgeCandidateRule(
            scope=_nonempty_string(raw_rule.get("scope"), "scope"),
            declared_type_structure=_nonempty_string(
                raw_rule.get("declared_type_structure"), "declared_type_structure"
            ),
            declared_type_name=_nonempty_string(
                raw_rule.get("declared_type_name"), "declared_type_name"
            ),
            allowed_knowledge_prefixes=(
                _prefixes(raw_rule.get("allowed_knowledge_prefixes"), policy=knowledge_policy)
                if uses_candidate_pool
                else _empty_prefixes(raw_rule.get("allowed_knowledge_prefixes"), policy=knowledge_policy)
            ),
            max_retrieved_candidates=(
                _positive_int(
                    raw_rule.get("max_retrieved_candidates"), "max_retrieved_candidates", maximum=12
                )
                if uses_candidate_pool
                else _empty_pool_value(
                    raw_rule.get("max_retrieved_candidates"),
                    "max_retrieved_candidates",
                    policy=knowledge_policy,
                )
            ),
            max_sibling_candidates=_sibling_limit(
                raw_rule.get("max_sibling_candidates"),
                selection=sibling_selection,
                policy=knowledge_policy,
            ),
            max_output_labels=(
                _positive_int(raw_rule.get("max_output_labels"), "max_output_labels", maximum=6)
                if uses_candidate_pool
                else _empty_pool_value(
                    raw_rule.get("max_output_labels"), "max_output_labels", policy=knowledge_policy)
            ),
            knowledge_policy=knowledge_policy,
            sibling_selection=sibling_selection,
        )
        if rule.scope not in SCOPES:
            raise ValueError(f"knowledge candidate rule has unsupported scope: {rule.scope}")
        if rule.key in rules:
            raise ValueError(f"duplicate exact knowledge candidate rule key: {rule.key}")
        rules[rule.key] = rule
    return KnowledgeCandidatePolicy(rules=rules)
