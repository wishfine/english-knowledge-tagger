"""Versioned, exact-match routing policies for question-type cleaning."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from .sft_labels import parse_sft_output_labels
from .type_inventory import MISSING, _TYPE_NAME_PATTERN, _TYPE_STRUCTURE_PATTERN, _declared_value
from .type_rulebook import TypeRulebook

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


def _scope_from_record(record: Mapping[str, Any]) -> str:
    if record.get("is_sub_question") is True:
        return "child"
    if record.get("is_sub_question") is False:
        return "parent"
    return "unknown"


def _identifier(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _canonical_type_path(label: str) -> str:
    return "题型->" + label.removeprefix("题型@").replace("@", "->")


def _legacy_type_paths(record: Mapping[str, Any]) -> list[str]:
    parsed = parse_sft_output_labels(record.get("output"))
    if parsed is None:
        return []
    _, type_labels = parsed
    return sorted(_canonical_type_path(label) for label in type_labels)


def _is_in_prefix(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(f"{prefix}->")


def route_sft_record(
    record: Mapping[str, Any],
    *,
    source_line: int,
    policy: TypeRoutingPolicy,
    rulebook: TypeRulebook,
) -> dict[str, Any]:
    """Create an audit route for one rendered SFT record without changing labels."""
    scope = _scope_from_record(record)
    structure = _declared_value(_TYPE_STRUCTURE_PATTERN, record.get("input"))
    name = _declared_value(_TYPE_NAME_PATTERN, record.get("input"))
    rule = policy.match(scope, structure, name)
    legacy_type_labels = _legacy_type_paths(record)
    risk_codes: set[str] = set()

    if structure == MISSING or name == MISSING:
        risk_codes.add("missing_declared_type")
    if rule is None:
        risk_codes.add("unmapped_policy")
        route = {
            "policy_status": "unmapped",
            "rule_id": None,
            "canonical_family": None,
            "type_selection_mode": "unresolved",
            "candidate_type_prefixes": [],
            "candidate_type_paths": [],
            "knowledge_inheritance": "never",
            "knowledge_policy": "unresolved",
            "review_notes": "没有此 exact scope × 题型结构 × 题型名称 的策略行。",
        }
    else:
        if rule.policy_status == "unmapped":
            risk_codes.add("unmapped_policy")
        elif rule.policy_status == "needs_review":
            risk_codes.add("needs_policy_review")
        candidate_paths = rulebook.candidates_for_prefixes(rule.candidate_type_prefixes)
        route = {
            "policy_status": rule.policy_status,
            "rule_id": rule.rule_id,
            "canonical_family": rule.canonical_family or None,
            "type_selection_mode": rule.type_selection_mode,
            "candidate_type_prefixes": list(rule.candidate_type_prefixes),
            "candidate_type_paths": list(candidate_paths),
            "knowledge_inheritance": rule.knowledge_inheritance,
            "knowledge_policy": rule.knowledge_policy or "unresolved",
            "review_notes": rule.review_notes,
        }

    for legacy_path in legacy_type_labels:
        status = rulebook.status_for(legacy_path)
        if status is None:
            risk_codes.add("legacy_type_not_in_rulebook")
        elif status == "deprecated":
            risk_codes.add("legacy_type_deprecated")
        if rule is not None and rule.candidate_type_prefixes and not any(
            _is_in_prefix(legacy_path, prefix) for prefix in rule.candidate_type_prefixes
        ):
            risk_codes.add("legacy_type_outside_candidate_prefix")

    return {
        "schema_version": "type-route-v1",
        "source_line": source_line,
        "question_id": _identifier(record.get("question_id")),
        "parent_id": _identifier(record.get("parent_id")),
        "scope": scope,
        "declared_type": {"structure": structure, "name": name},
        "legacy_type_labels": legacy_type_labels,
        "route": route,
        "risk_codes": sorted(risk_codes),
    }


def _counter_as_dict(counter: Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def route_sft_jsonl(
    input_path: Path,
    *,
    output_path: Path,
    policy: TypeRoutingPolicy,
    rulebook: TypeRulebook,
    limit: int | None = None,
) -> dict[str, Any]:
    """Stream an SFT JSONL source to a non-overwriting type-route JSONL artifact."""
    if output_path.exists():
        raise FileExistsError(f"type-route output already exists: {output_path}")
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive when provided")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    records = Counter[str]()
    route_statuses = Counter[str]()
    canonical_families = Counter[str]()
    risk_codes = Counter[str]()
    with input_path.open("r", encoding="utf-8") as source, output_path.open(
        "x", encoding="utf-8"
    ) as output:
        for source_line, line in enumerate(source, 1):
            if not line.strip():
                continue
            if limit is not None and records["valid"] >= limit:
                break
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                records["invalid_json_lines"] += 1
                continue
            if not isinstance(record, dict):
                records["non_object_records"] += 1
                continue
            route = route_sft_record(
                record,
                source_line=source_line,
                policy=policy,
                rulebook=rulebook,
            )
            output.write(json.dumps(route, ensure_ascii=False, sort_keys=True) + "\n")
            records["valid"] += 1
            route_statuses[route["route"]["policy_status"]] += 1
            family = route["route"]["canonical_family"]
            if isinstance(family, str) and family:
                canonical_families[family] += 1
            for code in route["risk_codes"]:
                risk_codes[code] += 1

    return {
        "schema_version": "type-route-report-v1",
        "input_path": str(input_path),
        "input_bytes": input_path.stat().st_size,
        "output_path": str(output_path),
        "limit": limit,
        "records": {
            "valid": records["valid"],
            "invalid_json_lines": records["invalid_json_lines"],
            "non_object_records": records["non_object_records"],
        },
        "route_status_counts": _counter_as_dict(route_statuses),
        "canonical_family_counts": _counter_as_dict(canonical_families),
        "risk_code_counts": _counter_as_dict(risk_codes),
    }
