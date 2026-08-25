"""Exact small-question routes to allowed knowledge-point candidate pools."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "knowledge-candidate-policy-v1"
SCOPES = frozenset({"parent", "child", "unknown"})


@dataclass(frozen=True)
class KnowledgeCandidateRule:
    """A bounded candidate pool for one exact source-declared question route."""

    scope: str
    declared_type_structure: str
    declared_type_name: str
    allowed_knowledge_prefixes: tuple[str, ...]
    max_retrieved_candidates: int
    max_sibling_candidates: int
    max_output_labels: int

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


def _prefixes(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("knowledge candidate rule allowed_knowledge_prefixes must be a non-empty list")
    prefixes = tuple(_nonempty_string(item, "allowed_knowledge_prefixes") for item in value)
    if len(set(prefixes)) != len(prefixes):
        raise ValueError("knowledge candidate rule allowed_knowledge_prefixes contains duplicates")
    if any(not prefix.startswith("知识点->") for prefix in prefixes):
        raise ValueError("knowledge candidate rule prefixes must use canonical '知识点->' paths")
    return prefixes


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
        rule = KnowledgeCandidateRule(
            scope=_nonempty_string(raw_rule.get("scope"), "scope"),
            declared_type_structure=_nonempty_string(
                raw_rule.get("declared_type_structure"), "declared_type_structure"
            ),
            declared_type_name=_nonempty_string(
                raw_rule.get("declared_type_name"), "declared_type_name"
            ),
            allowed_knowledge_prefixes=_prefixes(raw_rule.get("allowed_knowledge_prefixes")),
            max_retrieved_candidates=_positive_int(
                raw_rule.get("max_retrieved_candidates"), "max_retrieved_candidates", maximum=12
            ),
            max_sibling_candidates=_positive_int(
                raw_rule.get("max_sibling_candidates"), "max_sibling_candidates", maximum=8
            ),
            max_output_labels=_positive_int(
                raw_rule.get("max_output_labels"), "max_output_labels", maximum=6
            ),
        )
        if rule.scope not in SCOPES:
            raise ValueError(f"knowledge candidate rule has unsupported scope: {rule.scope}")
        if rule.key in rules:
            raise ValueError(f"duplicate exact knowledge candidate rule key: {rule.key}")
        rules[rule.key] = rule
    return KnowledgeCandidatePolicy(rules=rules)
