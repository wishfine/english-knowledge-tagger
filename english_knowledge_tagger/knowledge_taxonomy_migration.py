"""Versioned aliases from historical knowledge paths to the active teacher taxonomy."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Mapping


SCHEMA_VERSION = "knowledge-taxonomy-migration-v1"


@dataclass(frozen=True)
class KnowledgeTaxonomyAlias:
    rule_id: str
    source_prefix: str
    target_prefix: str


@dataclass(frozen=True)
class CanonicalKnowledgePath:
    legacy_path: str
    canonical_path: str
    status: str
    rule_id: str | None


@dataclass(frozen=True)
class KnowledgeTaxonomyMigration:
    """Longest-prefix alias rules; identity is always preserved explicitly."""

    aliases: tuple[KnowledgeTaxonomyAlias, ...]

    def canonicalize(self, legacy_path: str) -> CanonicalKnowledgePath:
        for alias in self.aliases:
            if legacy_path == alias.source_prefix or legacy_path.startswith(f"{alias.source_prefix}->"):
                suffix = legacy_path.removeprefix(alias.source_prefix)
                return CanonicalKnowledgePath(
                    legacy_path=legacy_path,
                    canonical_path=f"{alias.target_prefix}{suffix}",
                    status="prefix_alias",
                    rule_id=alias.rule_id,
                )
        return CanonicalKnowledgePath(
            legacy_path=legacy_path,
            canonical_path=legacy_path,
            status="identity",
            rule_id=None,
        )


def _nonempty_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or not value.strip().startswith("知识点->"):
        raise ValueError(f"taxonomy migration {field} must be a canonical '知识点->' path")
    return value.strip()


def load_knowledge_taxonomy_migration(path: Path) -> KnowledgeTaxonomyMigration:
    """Load exact versioned prefix aliases, rejecting ambiguous source prefixes."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"knowledge taxonomy migration is not valid JSON: {path}") from error
    if not isinstance(payload, Mapping) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"knowledge taxonomy migration schema_version must be {SCHEMA_VERSION!r}")
    raw_rules = payload.get("rules")
    if not isinstance(raw_rules, list):
        raise ValueError("knowledge taxonomy migration rules must be a list")
    aliases: list[KnowledgeTaxonomyAlias] = []
    source_prefixes: set[str] = set()
    rule_ids: set[str] = set()
    for raw_rule in raw_rules:
        if not isinstance(raw_rule, Mapping):
            raise ValueError("each knowledge taxonomy migration rule must be an object")
        rule_id = raw_rule.get("rule_id")
        if not isinstance(rule_id, str) or not rule_id.strip():
            raise ValueError("knowledge taxonomy migration rule_id must be non-empty")
        alias = KnowledgeTaxonomyAlias(
            rule_id=rule_id.strip(),
            source_prefix=_nonempty_path(raw_rule.get("source_prefix"), "source_prefix"),
            target_prefix=_nonempty_path(raw_rule.get("target_prefix"), "target_prefix"),
        )
        if alias.rule_id in rule_ids:
            raise ValueError(f"duplicate knowledge taxonomy migration rule_id: {alias.rule_id}")
        if alias.source_prefix in source_prefixes:
            raise ValueError(f"duplicate knowledge taxonomy migration source_prefix: {alias.source_prefix}")
        rule_ids.add(alias.rule_id)
        source_prefixes.add(alias.source_prefix)
        aliases.append(alias)
    return KnowledgeTaxonomyMigration(
        aliases=tuple(sorted(aliases, key=lambda item: len(item.source_prefix), reverse=True))
    )
