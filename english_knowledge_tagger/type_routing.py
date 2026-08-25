"""Versioned, exact-match routing policies for question-type cleaning."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "type-routing-policy-v1"
POLICY_STATUSES = frozenset({"unmapped", "needs_review", "approved", "not_applicable"})
SCOPES = frozenset({"parent", "child", "unknown"})
TYPE_SELECTION_MODES = frozenset({"unresolved", "single", "multiple"})


@dataclass(frozen=True)
class TypeRoutingRule:
    """A rule for one exact source-declared type and parent/child scope."""

    rule_id: str
    scope: str
    declared_type_structure: str
    declared_type_name: str
    policy_status: str
    canonical_family: str
    type_selection_mode: str
    candidate_type_prefixes: tuple[str, ...]
    knowledge_inheritance: str
    knowledge_policy: str
    review_notes: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.scope, self.declared_type_structure, self.declared_type_name)


@dataclass(frozen=True)
class TypeRoutingPolicy:
    """Exact-match rules; missing rules are intentionally unresolved."""

    rules: Mapping[tuple[str, str, str], TypeRoutingRule]

    def match(self, scope: str, structure: str, name: str) -> TypeRoutingRule | None:
        return self.rules.get((scope, structure, name))


def _nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"routing rule {field} must be a non-empty string")
    return value.strip()


def _string_list(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"routing rule {field} must be a list of strings")
    normalized = tuple(_nonempty_string(item, field) for item in value)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"routing rule {field} contains duplicates")
    return normalized


def _rule_from_mapping(raw_rule: object) -> TypeRoutingRule:
    if not isinstance(raw_rule, Mapping):
        raise ValueError("each routing rule must be an object")
    rule = TypeRoutingRule(
        rule_id=_nonempty_string(raw_rule.get("rule_id"), "rule_id"),
        scope=_nonempty_string(raw_rule.get("scope"), "scope"),
        declared_type_structure=_nonempty_string(
            raw_rule.get("declared_type_structure"), "declared_type_structure"
        ),
        declared_type_name=_nonempty_string(raw_rule.get("declared_type_name"), "declared_type_name"),
        policy_status=_nonempty_string(raw_rule.get("policy_status"), "policy_status"),
        canonical_family=(raw_rule.get("canonical_family") or "").strip(),
        type_selection_mode=_nonempty_string(
            raw_rule.get("type_selection_mode"), "type_selection_mode"
        ),
        candidate_type_prefixes=_string_list(
            raw_rule.get("candidate_type_prefixes"), "candidate_type_prefixes"
        ),
        knowledge_inheritance=_nonempty_string(
            raw_rule.get("knowledge_inheritance"), "knowledge_inheritance"
        ),
        knowledge_policy=(raw_rule.get("knowledge_policy") or "").strip(),
        review_notes=(raw_rule.get("review_notes") or "").strip(),
    )
    if rule.scope not in SCOPES:
        raise ValueError(f"routing rule has unsupported scope: {rule.scope}")
    if rule.policy_status not in POLICY_STATUSES:
        raise ValueError(f"routing rule has unsupported policy_status: {rule.policy_status}")
    if rule.type_selection_mode not in TYPE_SELECTION_MODES:
        raise ValueError(
            f"routing rule has unsupported type_selection_mode: {rule.type_selection_mode}"
        )
    if rule.knowledge_inheritance != "never":
        raise ValueError("routing rule knowledge_inheritance must be 'never'")
    if any(not prefix.startswith("题型->") for prefix in rule.candidate_type_prefixes):
        raise ValueError("routing rule candidate_type_prefixes must use canonical '题型->' paths")
    if rule.policy_status == "approved":
        if not rule.canonical_family:
            raise ValueError("approved routing rule requires canonical_family")
        if not rule.candidate_type_prefixes:
            raise ValueError("approved routing rule requires candidate_type_prefixes")
        if rule.type_selection_mode == "unresolved":
            raise ValueError("approved routing rule requires a resolved type_selection_mode")
    return rule


def load_type_routing_policy(path: Path) -> TypeRoutingPolicy:
    """Read and validate one versioned exact-match routing policy JSON file."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"routing policy is not valid JSON: {path}") from error
    if not isinstance(payload, Mapping) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"routing policy schema_version must be {SCHEMA_VERSION!r}")
    raw_rules = payload.get("rules")
    if not isinstance(raw_rules, list):
        raise ValueError("routing policy rules must be a list")

    rules: dict[tuple[str, str, str], TypeRoutingRule] = {}
    rule_ids: set[str] = set()
    for raw_rule in raw_rules:
        rule = _rule_from_mapping(raw_rule)
        if rule.rule_id in rule_ids:
            raise ValueError(f"duplicate routing rule_id: {rule.rule_id}")
        if rule.key in rules:
            raise ValueError(f"duplicate exact routing rule key: {rule.key}")
        rule_ids.add(rule.rule_id)
        rules[rule.key] = rule
    return TypeRoutingPolicy(rules=rules)


def _scope_sort_key(scope: str) -> int:
    return {"parent": 0, "child": 1, "unknown": 2}[scope]


def bootstrap_type_routing_policy(inventory: Mapping[str, Any]) -> dict[str, Any]:
    """Create a complete but deliberately unmapped policy skeleton from inventory JSON."""
    raw_rows = inventory.get("rows")
    if not isinstance(raw_rows, list):
        raise ValueError("inventory rows must be a list")
    keys: set[tuple[str, str, str]] = set()
    for row in raw_rows:
        if not isinstance(row, Mapping):
            raise ValueError("inventory row must be an object")
        scope = _nonempty_string(row.get("scope"), "inventory scope")
        structure = _nonempty_string(
            row.get("declared_type_structure"), "inventory declared_type_structure"
        )
        name = _nonempty_string(row.get("declared_type_name"), "inventory declared_type_name")
        if scope not in SCOPES:
            raise ValueError(f"inventory row has unsupported scope: {scope}")
        key = (scope, structure, name)
        if key in keys:
            raise ValueError(f"inventory contains duplicate routing key: {key}")
        keys.add(key)

    rules = []
    for scope, structure, name in sorted(keys, key=lambda key: (_scope_sort_key(key[0]), key[1], key[2])):
        rules.append(
            {
                "rule_id": f"route:{scope}:{structure}:{name}",
                "scope": scope,
                "declared_type_structure": structure,
                "declared_type_name": name,
                "policy_status": "unmapped",
                "canonical_family": "",
                "type_selection_mode": "unresolved",
                "candidate_type_prefixes": [],
                "knowledge_inheritance": "never",
                "knowledge_policy": "unresolved",
                "review_notes": "由老师CSV与样本复核后填写；历史输出仅作候选证据。",
            }
        )
    return {"schema_version": SCHEMA_VERSION, "rules": rules}
