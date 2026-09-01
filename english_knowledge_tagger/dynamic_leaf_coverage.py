"""Offline coverage comparison for dynamic leaf neighborhoods and teacher corrections."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .dynamic_leaf_routing import build_dynamic_leaf_neighborhood
from .knowledge_rulebook import KnowledgeRulebook
from .teacher_subquestion_gold_resolution import CORRECTION_SCHEMA_VERSION


SCHEMA_VERSION = "dynamic-leaf-coverage-v1"


def _path(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip().startswith("知识点->"):
        raise ValueError(f"{field_name} must be a canonical knowledge path")
    return value.strip()


def _parent(path: str) -> str:
    parent, separator, _ = path.rpartition("->")
    if not separator:
        raise ValueError(f"knowledge path has no parent: {path}")
    return parent


def _confusions(
    ambiguity_manifest: Mapping[str, object],
) -> dict[str, dict[str, int]]:
    rows = ambiguity_manifest.get("labels")
    if not isinstance(rows, list):
        raise ValueError("ambiguity manifest labels must be a list")
    result: dict[str, dict[str, int]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("ambiguity manifest label row must be an object")
        label = _path(row.get("canonical_label"), field_name="ambiguity canonical_label")
        neighbors = row.get("confusion_neighbors")
        if not isinstance(neighbors, list):
            raise ValueError("ambiguity confusion_neighbors must be a list")
        counts: dict[str, int] = {}
        for item in neighbors:
            if not isinstance(item, Mapping):
                raise ValueError("ambiguity confusion neighbor must be an object")
            candidate = _path(
                item.get("canonical_label"), field_name="confusion canonical_label"
            )
            count = item.get("count")
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise ValueError("confusion count must be a non-negative integer")
            counts[candidate] = count
        result[label] = counts
    return result


@dataclass
class _Metrics:
    records: int = 0
    covered: Counter[str] = field(default_factory=Counter)

    def add(self, strategy_sets: Mapping[str, set[str]], gold: set[str]) -> None:
        self.records += 1
        for name, candidates in strategy_sets.items():
            if candidates & gold:
                self.covered[name] += 1

    def report(self, strategy_names: Sequence[str]) -> dict[str, object]:
        strategies = {
            name: {
                "covered_records": self.covered[name],
                "coverage_rate": self.covered[name] / self.records if self.records else None,
            }
            for name in strategy_names
        }
        dynamic_all = strategies.get("dynamic_all", {}).get("coverage_rate")
        selected = "hold"
        if isinstance(dynamic_all, (int, float)) and dynamic_all > 0:
            for name in ("dynamic_top4", "dynamic_top8"):
                rate = strategies[name]["coverage_rate"]
                if isinstance(rate, (int, float)) and rate >= dynamic_all - 0.01:
                    selected = name
                    break
        return {
            "records": self.records,
            "strategies": strategies,
            "selected_budget": selected,
        }


def summarize_dynamic_leaf_coverage(
    rulebook: KnowledgeRulebook,
    *,
    corrections: Sequence[Mapping[str, object]],
    ambiguity_manifest: Mapping[str, object],
    baseline_candidates: Mapping[tuple[str, str], set[str]] | None = None,
) -> dict[str, object]:
    """Compare candidate presence only; no model is called and no patch is emitted."""
    confusion_by_label = _confusions(ambiguity_manifest)
    strategy_names = [
        "direct_siblings_all",
        "dynamic_top4",
        "dynamic_top8",
        "dynamic_all",
    ]
    if baseline_candidates is not None:
        strategy_names.append("retrieval12_sibling8")
    global_metrics = _Metrics()
    by_historical: defaultdict[str, _Metrics] = defaultdict(_Metrics)
    by_gold: defaultdict[str, _Metrics] = defaultdict(_Metrics)
    by_pair: defaultdict[str, _Metrics] = defaultdict(_Metrics)
    seen: set[tuple[str, str]] = set()
    for number, row in enumerate(corrections, 1):
        if row.get("schema_version") != CORRECTION_SCHEMA_VERSION:
            raise ValueError(f"correction row {number}: unexpected schema_version")
        question_id = row.get("question_id")
        if not isinstance(question_id, str) or not question_id.strip():
            raise ValueError(f"correction row {number}: question_id must be non-empty")
        historical = _path(row.get("historical_label"), field_name="historical_label")
        identity = (question_id.strip(), historical)
        if identity in seen:
            raise ValueError(f"correction row {number}: duplicate question/label pair")
        seen.add(identity)
        if historical not in rulebook.records:
            raise ValueError(f"correction row {number}: historical label absent from rulebook")
        raw_gold = row.get("gold_labels")
        if not isinstance(raw_gold, list) or not raw_gold:
            raise ValueError(f"correction row {number}: gold_labels must be non-empty")
        gold = {_path(item, field_name="gold_label") for item in raw_gold}
        missing_gold = gold - set(rulebook.records)
        if missing_gold:
            raise ValueError(f"correction row {number}: gold label absent from rulebook")
        question_text = row.get("question_text")
        if not isinstance(question_text, str):
            question_text = ""
        siblings = {
            item.path for item in rulebook.direct_active_leaf_siblings(historical)
        }
        neighborhood = build_dynamic_leaf_neighborhood(
            rulebook,
            target_label=historical,
            question_text=question_text,
            confusion_counts=confusion_by_label.get(historical, {}),
            soft_route_compatible=set(),
        )
        ordered = [candidate.label for candidate in neighborhood.candidates]
        strategies = {
            "direct_siblings_all": siblings,
            "dynamic_top4": set(ordered[:4]),
            "dynamic_top8": set(ordered[:8]),
            "dynamic_all": set(ordered),
        }
        if baseline_candidates is not None:
            strategies["retrieval12_sibling8"] = set(
                baseline_candidates.get(identity, set())
            )
        global_metrics.add(strategies, gold)
        historical_parent = _parent(historical)
        by_historical[historical_parent].add(strategies, gold)
        for gold_parent in sorted({_parent(label) for label in gold}):
            by_gold[gold_parent].add(strategies, gold)
            by_pair[f"{historical_parent} × {gold_parent}"].add(strategies, gold)

    global_report = global_metrics.report(strategy_names)
    return {
        "schema_version": SCHEMA_VERSION,
        "correction_records": len(corrections),
        "strategies": global_report["strategies"],
        "selected_budget": global_report["selected_budget"],
        "by_historical_parent": {
            key: metrics.report(strategy_names)
            for key, metrics in sorted(by_historical.items())
        },
        "by_gold_parent": {
            key: metrics.report(strategy_names) for key, metrics in sorted(by_gold.items())
        },
        "by_historical_parent_and_gold_parent": {
            key: metrics.report(strategy_names) for key, metrics in sorted(by_pair.items())
        },
    }
