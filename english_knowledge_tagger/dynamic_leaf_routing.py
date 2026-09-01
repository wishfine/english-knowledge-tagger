"""Dynamic local leaf neighborhoods and a bounded paged resolver."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re
from typing import Callable, Mapping

from .candidate_labeling import (
    LabelingServiceConfig,
    LabelingServiceError,
    Transport,
    _http_transport,
)
from .conversion_gate import _extract_json_payload
from .knowledge_rulebook import KnowledgeRulebook
from .knowledge_taxonomy_tree import NO_MATCH, KnowledgeTaxonomyTree
from .knowledge_tree_search import TreeChoice, TreeChoiceRequest


MORE = "__MORE__"
BACKTRACK = "__BACKTRACK__"
HOLD = "__HOLD__"


@dataclass(frozen=True)
class DynamicLeafCandidate:
    label: str
    definition: str
    sources: tuple[str, ...]
    confusion_count: int
    same_parent: bool
    soft_route_compatible: bool
    definition_similarity: float


@dataclass(frozen=True)
class DynamicLeafNeighborhood:
    target_label: str
    candidates: tuple[DynamicLeafCandidate, ...]


@dataclass(frozen=True)
class DynamicLeafPage:
    target_label: str
    cursor: int
    candidates: tuple[DynamicLeafCandidate, ...]
    controls: tuple[str, ...]


@dataclass(frozen=True)
class DynamicLeafChoice:
    choice: str
    evidence: str


@dataclass(frozen=True)
class DynamicLeafResolution:
    status: str
    candidate_label: str | None
    trace: tuple[Mapping[str, object], ...]


Choose = Callable[[DynamicLeafPage], DynamicLeafChoice]


def _parent(path: str) -> str:
    parent, separator, _ = path.rpartition("->")
    if not separator:
        raise ValueError(f"knowledge path has no parent: {path}")
    return parent


def _terms(value: str) -> frozenset[str]:
    ascii_words = re.findall(r"[a-z0-9]+", value.lower())
    han = "".join(re.findall(r"[\u4e00-\u9fff]", value))
    bigrams = [han[index : index + 2] for index in range(max(0, len(han) - 1))]
    return frozenset((*ascii_words, *bigrams))


def _similarity(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def build_dynamic_leaf_neighborhood(
    rulebook: KnowledgeRulebook,
    *,
    target_label: str,
    question_text: str,
    confusion_counts: Mapping[str, int],
    soft_route_compatible: set[str] | frozenset[str],
    hard_excluded: frozenset[str] = frozenset(),
    max_neighbors: int = 32,
    candidate_parent_path: str | None = None,
    include_escape_candidates: bool = True,
) -> DynamicLeafNeighborhood:
    """Rank direct siblings, observed confusions, soft-route and lexical escape labels."""
    if max_neighbors <= 0:
        raise ValueError("max_neighbors must be positive")
    target = rulebook.records.get(target_label)
    if target is None or target.status != "active":
        raise ValueError("target_label must be an active teacher leaf")
    for label, count in confusion_counts.items():
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError(f"confusion count must be a non-negative integer: {label}")
    active_parent = candidate_parent_path or _parent(target_label)
    direct_siblings = {
        path
        for path, record in rulebook.records.items()
        if record.status == "active" and _parent(path) == active_parent and path != target_label
    }
    active = {
        path: record
        for path, record in rulebook.records.items()
        if record.status == "active" and path != target_label and path not in hard_excluded
    }
    query_terms = _terms(f"{question_text}\n{target.alternative_definition}")
    similarities = {
        path: _similarity(
            query_terms, _terms(f"{path}\n{record.alternative_definition}")
        )
        for path, record in active.items()
    }
    lexical_escape = (
        {
            path
            for path, _ in sorted(
                similarities.items(), key=lambda item: (-item[1], item[0])
            )[:8]
        }
        if include_escape_candidates
        else set()
    )
    included = (
        direct_siblings
        | ({path for path in confusion_counts if path in active} if include_escape_candidates else set())
        | ({path for path in soft_route_compatible if path in active} if include_escape_candidates else set())
        | lexical_escape
    )
    target_parent = active_parent
    candidates: list[DynamicLeafCandidate] = []
    for path in included:
        record = active.get(path)
        if record is None:
            continue
        sources: list[str] = []
        if path in direct_siblings:
            sources.append("direct_sibling")
        if confusion_counts.get(path, 0):
            sources.append("confusion")
        if path in soft_route_compatible:
            sources.append("soft_route")
        if path in lexical_escape:
            sources.append("definition_similarity")
        candidates.append(
            DynamicLeafCandidate(
                label=path,
                definition=record.alternative_definition,
                sources=tuple(sources),
                confusion_count=confusion_counts.get(path, 0),
                same_parent=_parent(path) == target_parent,
                soft_route_compatible=path in soft_route_compatible,
                definition_similarity=similarities[path],
            )
        )
    ordered = tuple(
        sorted(
            candidates,
            key=lambda item: (
                -item.confusion_count,
                -int(item.same_parent),
                -int(item.soft_route_compatible),
                -item.definition_similarity,
                item.label,
            ),
        )[:max_neighbors]
    )
    return DynamicLeafNeighborhood(target_label=target_label, candidates=ordered)


def page_dynamic_leaf_neighborhood(
    neighborhood: DynamicLeafNeighborhood,
    *,
    cursor: int,
    page_size: int = 4,
) -> DynamicLeafPage:
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    if cursor < 0 or cursor > len(neighborhood.candidates):
        raise ValueError("cursor is outside the dynamic neighborhood")
    candidates = neighborhood.candidates[cursor : cursor + page_size]
    has_more = cursor + len(candidates) < len(neighborhood.candidates)
    controls = (MORE, BACKTRACK, HOLD) if has_more else (BACKTRACK, HOLD)
    return DynamicLeafPage(
        target_label=neighborhood.target_label,
        cursor=cursor,
        candidates=candidates,
        controls=controls,
    )


def build_dynamic_leaf_choice_prompt(
    page: DynamicLeafPage, *, question_text: str
) -> str:
    """Render only the current alternative leaves and explicit controls."""
    if not question_text.strip():
        raise ValueError("dynamic leaf question_text must be non-empty")
    candidates = "\n".join(
        f"- {candidate.label}\n  释义：{candidate.definition}"
        for candidate in page.candidates
    )
    controls: list[str] = []
    if MORE in page.controls:
        controls.append(f"- {MORE}：当前候选不足，查看下一批相邻标签。")
    controls.extend(
        (
            f"- {BACKTRACK}：当前邻域均不适用，返回上一层分支。",
            f"- {HOLD}：题面不足、多知识点混合或无法可靠选择。",
        )
    )
    return f"""你正在为一道英语题选择一个可能替代的末级知识点。当前历史标签已经由独立判别器稳定否定；不要恢复或猜测历史标签。

只能从本页候选或控制项中选择一个。选择具体标签时，它必须直接解释答案；仅出现相关词或结构不够。

本页候选：
{candidates}
{chr(10).join(controls)}

题目内容：
{question_text.strip()}

只输出 JSON：
{{"choice":"本页完整标签路径或控制项","evidence":"不超过80字的题面依据"}}"""


class DynamicLeafChoiceClient:
    def __init__(
        self,
        config: LabelingServiceConfig,
        *,
        transport: Transport | None = None,
    ):
        if not config.endpoint:
            raise ValueError("dynamic leaf endpoint must be non-empty")
        self._config = config
        self._transport = transport or _http_transport

    def choose(self, page: DynamicLeafPage, *, question_text: str) -> DynamicLeafChoice:
        prompt = build_dynamic_leaf_choice_prompt(page, question_text=question_text)
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        response = self._transport(
            self._config.endpoint,
            {
                "model": self._config.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": self._config.max_tokens,
                "temperature": 0.0,
                "chat_template_kwargs": {"enable_thinking": False},
            },
            self._config.timeout_seconds,
            headers,
        )
        try:
            raw = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise LabelingServiceError("dynamic leaf response has no content") from error
        if not isinstance(raw, str):
            raise LabelingServiceError("dynamic leaf response content must be a string")
        payload = _extract_json_payload(raw)
        choice = payload.get("choice")
        evidence = payload.get("evidence")
        allowed = {candidate.label for candidate in page.candidates} | set(page.controls)
        if not isinstance(choice, str) or choice not in allowed:
            raise LabelingServiceError("dynamic leaf choice is outside the current page")
        if not isinstance(evidence, str) or not evidence.strip():
            raise LabelingServiceError("dynamic leaf evidence must be non-empty")
        return DynamicLeafChoice(choice=choice, evidence=evidence.strip())


def resolve_dynamic_leaf(
    neighborhood: DynamicLeafNeighborhood,
    *,
    choose: Choose,
    page_size: int = 4,
    max_pages: int | None = None,
) -> DynamicLeafResolution:
    """Resolve one alternative leaf or an explicit non-releasing outcome."""
    cursor = 0
    trace: list[dict[str, object]] = []
    while True:
        if max_pages is not None and len(trace) >= max_pages:
            return DynamicLeafResolution(
                status="budget_exhausted", candidate_label=None, trace=tuple(trace)
            )
        page = page_dynamic_leaf_neighborhood(
            neighborhood, cursor=cursor, page_size=page_size
        )
        decision = choose(page)
        allowed = {candidate.label for candidate in page.candidates} | set(page.controls)
        trace.append(
            {
                "cursor": cursor,
                "candidate_labels": [candidate.label for candidate in page.candidates],
                "controls": list(page.controls),
                "choice": decision.choice,
                "evidence": decision.evidence,
            }
        )
        if decision.choice not in allowed:
            return DynamicLeafResolution(
                status="unparsed", candidate_label=None, trace=tuple(trace)
            )
        if decision.choice == MORE:
            cursor += len(page.candidates)
            continue
        if decision.choice == BACKTRACK:
            return DynamicLeafResolution(
                status="backtrack", candidate_label=None, trace=tuple(trace)
            )
        if decision.choice == HOLD:
            return DynamicLeafResolution(
                status="hold", candidate_label=None, trace=tuple(trace)
            )
        return DynamicLeafResolution(
            status="candidate", candidate_label=decision.choice, trace=tuple(trace)
        )


def search_dynamic_tree_candidate(
    tree: KnowledgeTaxonomyTree,
    *,
    rulebook: KnowledgeRulebook,
    target_label: str,
    question_text: str,
    confusion_counts: Mapping[str, int],
    soft_route_compatible: set[str] | frozenset[str],
    choose_branch: Callable[[TreeChoiceRequest], TreeChoice],
    choose_leaf: Choose,
    hard_excluded: frozenset[str] = frozenset(),
    page_size: int = 4,
    max_steps: int = 8,
    max_backtracks: int = 2,
) -> DynamicLeafResolution:
    """Start at the rejected label parent, then backtrack through the taxonomy if needed."""
    if target_label not in tree.terminal_records:
        raise ValueError("dynamic tree target_label must be an active terminal")
    if not question_text.strip():
        raise ValueError("dynamic tree question_text must be non-empty")
    if max_steps <= 0 or max_backtracks < 0:
        raise ValueError("dynamic tree budgets are invalid")
    current_parent = _parent(target_label)
    excluded: defaultdict[str, set[str]] = defaultdict(set)
    excluded[current_parent].add(target_label)
    trace: list[dict[str, object]] = []
    steps = 0
    backtracks = 0

    def backtrack() -> DynamicLeafResolution | None:
        nonlocal current_parent, backtracks
        if current_parent == tree.root_path:
            return DynamicLeafResolution(
                status="uncovered", candidate_label=None, trace=tuple(trace)
            )
        backtracks += 1
        if backtracks > max_backtracks:
            return DynamicLeafResolution(
                status="budget_exhausted", candidate_label=None, trace=tuple(trace)
            )
        failed_child = current_parent
        current_parent = _parent(current_parent)
        excluded[current_parent].add(failed_child)
        return None

    while steps < max_steps:
        children = tuple(
            child
            for child in tree.children(current_parent)
            if child not in excluded[current_parent]
        )
        if not children:
            outcome = backtrack()
            if outcome is not None:
                return outcome
            continue
        if all(tree.is_terminal(child) for child in children):
            neighborhood = build_dynamic_leaf_neighborhood(
                rulebook,
                target_label=target_label,
                question_text=question_text,
                confusion_counts=confusion_counts,
                soft_route_compatible=soft_route_compatible,
                hard_excluded=frozenset({target_label, *hard_excluded, *excluded[current_parent]}),
                candidate_parent_path=current_parent,
            )
            local = resolve_dynamic_leaf(
                neighborhood,
                choose=choose_leaf,
                page_size=page_size,
                max_pages=max_steps - steps,
            )
            for item in local.trace:
                trace.append({"kind": "leaf_page", "parent_path": current_parent, **item})
            steps += len(local.trace)
            if local.status == "candidate":
                return DynamicLeafResolution(
                    status="candidate",
                    candidate_label=local.candidate_label,
                    trace=tuple(trace),
                )
            if local.status in {"hold", "unparsed", "budget_exhausted"}:
                return DynamicLeafResolution(
                    status=local.status, candidate_label=None, trace=tuple(trace)
                )
            outcome = backtrack()
            if outcome is not None:
                return outcome
            continue

        request = TreeChoiceRequest(
            question_context=question_text,
            parent_path=current_parent,
            candidate_paths=children,
            excluded_paths=tuple(sorted(excluded[current_parent])),
        )
        decision = choose_branch(request)
        steps += 1
        trace.append(
            {
                "kind": "branch",
                "parent_path": current_parent,
                "candidate_paths": list(children),
                "choice": decision.choice,
                "candidate_coverage": decision.candidate_coverage,
                "evidence": decision.evidence,
                "parse_error": decision.parse_error,
            }
        )
        if decision.parse_error is not None or decision.choice not in {*children, NO_MATCH}:
            return DynamicLeafResolution(
                status="unparsed", candidate_label=None, trace=tuple(trace)
            )
        if decision.choice == NO_MATCH:
            outcome = backtrack()
            if outcome is not None:
                return outcome
            continue
        if decision.candidate_coverage != "covered":
            return DynamicLeafResolution(
                status="unparsed", candidate_label=None, trace=tuple(trace)
            )
        if tree.is_terminal(decision.choice):
            return DynamicLeafResolution(
                status="candidate", candidate_label=decision.choice, trace=tuple(trace)
            )
        current_parent = decision.choice
    return DynamicLeafResolution(
        status="budget_exhausted", candidate_label=None, trace=tuple(trace)
    )
