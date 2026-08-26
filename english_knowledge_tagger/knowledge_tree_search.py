"""Pure, bounded descent and backtracking for one knowledge-point tree candidate."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import time
from typing import Callable, Mapping

from .knowledge_taxonomy_tree import NO_MATCH, KnowledgeTaxonomyTree


@dataclass(frozen=True)
class TreeChoiceRequest:
    """One constrained sibling-choice request; the transport implementation is external."""

    question_context: str
    parent_path: str
    candidate_paths: tuple[str, ...]
    excluded_paths: tuple[str, ...]


@dataclass(frozen=True)
class TreeChoice:
    """A parsed response from one model or deterministic test selector."""

    choice: str
    candidate_coverage: str
    evidence: str
    raw_response: str = ""
    parse_error: str | None = None
    model_call_elapsed_ms: float | None = None
    prompt_chars: int | None = None
    response_chars: int | None = None


@dataclass(frozen=True)
class TreeSearchResult:
    """Candidate outcome plus the complete replayable decision trace."""

    status: str
    candidate_label: str | None
    trace: tuple[Mapping[str, object], ...]


Choose = Callable[[TreeChoiceRequest], TreeChoice]
_COVERAGE = frozenset({"covered", "insufficient", "unknown"})


def _parent(path: str) -> str:
    parent, separator, _ = path.rpartition("->")
    if not separator:
        raise ValueError(f"taxonomy path has no parent: {path}")
    return parent


def _result(
    status: str, candidate_label: str | None, trace: list[dict[str, object]]
) -> TreeSearchResult:
    return TreeSearchResult(status=status, candidate_label=candidate_label, trace=tuple(trace))


def search_one_candidate(
    tree: KnowledgeTaxonomyTree,
    *,
    question_context: str,
    allowed_prefixes: tuple[str, ...],
    choose: Choose,
    max_steps: int = 8,
    max_backtracks: int = 2,
) -> TreeSearchResult:
    """Find one active terminal or return an explicit non-terminal outcome.

    ``NO_MATCH`` never becomes a knowledge label. It rejects the current branch,
    and only a no-match at the type-constrained root finishes as ``uncovered``.
    """
    if not question_context.strip():
        raise ValueError("tree search question_context must be non-empty")
    if max_steps <= 0:
        raise ValueError("max_steps must be positive")
    if max_backtracks < 0:
        raise ValueError("max_backtracks must be non-negative")

    root_candidates = tree.root_candidates(allowed_prefixes)
    current_parent = tree.root_path
    excluded: defaultdict[str, set[str]] = defaultdict(set)
    trace: list[dict[str, object]] = []
    steps = 0
    backtracks = 0

    def candidates(parent: str) -> tuple[str, ...]:
        available = root_candidates if parent == tree.root_path else tree.children(parent)
        return tuple(path for path in available if path not in excluded[parent])

    def backtrack() -> TreeSearchResult | None:
        nonlocal current_parent, backtracks
        if current_parent == tree.root_path:
            return _result("uncovered", None, trace)
        backtracks += 1
        if backtracks > max_backtracks:
            return _result("budget_exhausted", None, trace)
        failed_child = current_parent
        current_parent = _parent(current_parent)
        excluded[current_parent].add(failed_child)
        return None

    while steps < max_steps:
        candidate_paths = candidates(current_parent)
        if not candidate_paths:
            outcome = backtrack()
            if outcome is not None:
                return outcome
            continue

        request = TreeChoiceRequest(
            question_context=question_context,
            parent_path=current_parent,
            candidate_paths=candidate_paths,
            excluded_paths=tuple(sorted(excluded[current_parent])),
        )
        choice_started_ns = time.perf_counter_ns()
        decision = choose(request)
        choice_elapsed_ms = (time.perf_counter_ns() - choice_started_ns) / 1_000_000
        steps += 1
        trace.append(
            {
                "step": steps,
                "parent_path": current_parent,
                "candidate_paths": candidate_paths,
                "candidate_count": len(candidate_paths),
                "excluded_paths": request.excluded_paths,
                "choice": decision.choice,
                "candidate_coverage": decision.candidate_coverage,
                "evidence": decision.evidence,
                "raw_response": decision.raw_response,
                "parse_error": decision.parse_error,
                "choice_elapsed_ms": choice_elapsed_ms,
                "model_call_elapsed_ms": decision.model_call_elapsed_ms,
                "prompt_chars": decision.prompt_chars,
                "response_chars": decision.response_chars,
            }
        )
        if decision.parse_error is not None:
            return _result("unparsed", None, trace)
        if decision.candidate_coverage not in _COVERAGE:
            return _result("unparsed", None, trace)
        if decision.choice not in {*candidate_paths, NO_MATCH}:
            return _result("unparsed", None, trace)
        if decision.choice == NO_MATCH:
            outcome = backtrack()
            if outcome is not None:
                return outcome
            continue
        if decision.candidate_coverage != "covered":
            return _result("unparsed", None, trace)
        if tree.is_terminal(decision.choice):
            return _result("tree_candidate", decision.choice, trace)
        current_parent = decision.choice

    return _result("budget_exhausted", None, trace)
