"""Read-only active knowledge-point taxonomy tree built from the teacher rulebook."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping

from .knowledge_rulebook import KnowledgeRulebook, KnowledgeRulebookRecord


NO_MATCH = "__NO_MATCH__"
ROOT_PATH = "知识点"
_ROOT_CATEGORY_DEFINITIONS = {
    "知识点->词汇": "词义、词汇辨析、固定搭配/句型、构词法等词汇层面的核心考查。",
    "知识点->词法": "词类及其形态、时态语态、非谓语、冠词、代词、介词等语法词法考查。",
    "知识点->句法": "句子成分、句型、从句、主谓一致、特殊句式等句法结构考查。",
    "知识点->语用": "交际目的、言语功能、情境表达与得体性考查。",
    "知识点->语篇主题": "文章或材料主要谈论的人、事、社会/自然主题。",
    "知识点->语篇体裁": "文章的文体、篇章组织和表达形式。",
    "知识点->语音": "字母、音标、发音、重音和语调等语音考查。",
    "知识点->其他": "不适合归入上述主类的有效知识点；仅在其它根类均不匹配时选择。",
}


@dataclass(frozen=True)
class KnowledgeTaxonomyTree:
    """A deterministic tree of active terminal knowledge-point paths."""

    root_path: str
    children_by_parent: Mapping[str, tuple[str, ...]]
    terminal_records: Mapping[str, KnowledgeRulebookRecord]

    @classmethod
    def from_rulebook(cls, rulebook: KnowledgeRulebook) -> "KnowledgeTaxonomyTree":
        """Build only from active leaves; deprecated labels cannot be tree candidates."""
        terminals = {
            path: record for path, record in rulebook.records.items() if record.status == "active"
        }
        children: defaultdict[str, set[str]] = defaultdict(set)
        for path in terminals:
            parts = path.split("->")
            if not parts or parts[0] != ROOT_PATH:
                raise ValueError(f"knowledge taxonomy path must start with {ROOT_PATH!r}: {path}")
            for index in range(1, len(parts)):
                parent = "->".join(parts[:index])
                child = "->".join(parts[: index + 1])
                children[parent].add(child)
        return cls(
            root_path=ROOT_PATH,
            children_by_parent={
                parent: tuple(sorted(paths)) for parent, paths in sorted(children.items())
            },
            terminal_records=terminals,
        )

    def children(self, parent_path: str) -> tuple[str, ...]:
        """Return canonical children only; the model control token is never a taxonomy node."""
        return self.children_by_parent.get(parent_path, ())

    def root_candidates(self, allowed_prefixes: tuple[str, ...]) -> tuple[str, ...]:
        """Validate and return the exact type-policy roots for one constrained search."""
        if not allowed_prefixes:
            raise ValueError("tree search requires at least one allowed knowledge prefix")
        node_paths = {self.root_path, *self.children_by_parent, *self.terminal_records}
        for prefix in allowed_prefixes:
            if prefix not in node_paths:
                raise ValueError(f"allowed knowledge prefix is not in taxonomy: {prefix}")
        if len(set(allowed_prefixes)) != len(allowed_prefixes):
            raise ValueError("allowed knowledge prefixes contain duplicates")
        if self.root_path in allowed_prefixes:
            if allowed_prefixes != (self.root_path,):
                raise ValueError("whole-taxonomy root cannot be combined with narrower prefixes")
            return self.children(self.root_path)
        return tuple(sorted(allowed_prefixes))

    def is_terminal(self, path: str) -> bool:
        return path in self.terminal_records

    def definition(self, path: str) -> str | None:
        """Return compact teacher leaf text or a stable first-level category guide."""
        record = self.terminal_records.get(path)
        if record is not None:
            return record.alternative_definition
        return _ROOT_CATEGORY_DEFINITIONS.get(path)
