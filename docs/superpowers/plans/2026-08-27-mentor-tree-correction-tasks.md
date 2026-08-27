# Mentor Tree Correction Task Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert one mentor direct-verification JSONL into auditable whole-taxonomy tree tasks and explicit hold records, so low-match labels such as `知识点@词汇@构词法@转化法` can enter the existing breadth-first tree correction experiment without changing source data or labels.

**Architecture:** Preserve the existing `knowledge-tree-task-v1` and `route_knowledge_tree.py` executor. A new read-only builder maps consistent mentor `llm_match=true` rows to `direct_match_recheck` tasks and consistent `false` rows to `direct_mismatch` tasks. It puts contradictory (`false` plus `should_be=正确`), non-label `should_be`, and missing question context into a separate hold JSONL. The tree accepts `知识点` as a special all-active-taxonomy root and expands it to its direct children in the first choice step.

**Tech Stack:** Python standard library, JSONL, existing knowledge taxonomy tree/search, `unittest`.

## Global Constraints

- Input mentor JSONL and enhanced source remain read-only; output paths refuse overwrite.
- This builder never invokes DS, performs no label replacement, and never treats `llm_should_be` as truth.
- Tree tasks retain source line, question ID, parent ID, route, original label, direct result, and direct reason as audit metadata; only question context is supplied to the tree model.
- A tree task may return the original terminal, a different terminal, or `uncovered`/`budget_exhausted`; all outcomes remain candidates for manual review.
- Full-tree tasks use the `知识点` root and are limited by the existing tree executor's `max_steps` and `max_backtracks`.
- Do not stage incomplete human-review ledgers or `uv.lock`.

---

### Task 1: Permit an explicit whole-taxonomy root in the existing tree search

**Files:**
- Modify: `english_knowledge_tagger/knowledge_taxonomy_tree.py`
- Modify: `tests/test_knowledge_tree_search.py`
- Modify: `docs/knowledge-label-validation.md`

**Interfaces:**

```python
KnowledgeTaxonomyTree.root_candidates(("知识点",)) -> tuple[str, ...]
```

When the only allowed prefix is the tree root, return the root's direct active children (for example `知识点->词汇`, `知识点->词法`), never the root itself. Combining `知识点` with narrower prefixes is invalid because it creates an ambiguous root policy.

- [x] **Step 1: Write the failing whole-root test.** Add an active `知识点->词汇->构词法->转化法` leaf to `_tree()` and assert that a search with `allowed_prefixes=("知识点",)` offers `知识点->词汇` and `知识点->词法` on trace step 1, then descends to a selected terminal.
- [x] **Step 2: Verify red.** Run `.venv/bin/python -m pytest tests/test_knowledge_tree_search.py -q`; the implementation currently offers only `知识点` at the first step.
- [x] **Step 3: Implement the special root expansion.** In `root_candidates`, validate that `知识点` is not combined with another prefix and return `children(self.root_path)` when it is the only prefix. Keep narrow-prefix behavior unchanged.
- [x] **Step 4: Verify green.** Run `.venv/bin/python -m pytest tests/test_knowledge_tree_search.py -q`.
- [x] **Step 5: Document that `知识点` means whole-tree experimental routing, not a real label candidate.**

### Task 2: Build mentor direct-verification tree tasks and hold records

**Files:**
- Create: `english_knowledge_tagger/mentor_tree_correction_tasks.py`
- Create: `scripts/build_mentor_tree_correction_tasks.py`
- Create: `tests/test_mentor_tree_correction_tasks.py`

**Interfaces:**

```python
build_mentor_tree_correction_tasks(
    verification_path: Path,
    *, verify_label: str, output_path: Path, hold_output_path: Path,
) -> dict[str, object]
```

For each input line with the exact `verify_label`:

```text
llm_match=true                                  -> direct_match_recheck tree task
llm_match=false + label-shaped should_be        -> direct_mismatch tree task
llm_match=false + should_be="正确"              -> direct_contract_conflict hold
llm_match=false + non-label should_be           -> direct_insufficient hold
missing cleaned question context                 -> missing_question_context hold
```

Tree tasks use `allowed_knowledge_prefixes=["知识点"]`, `knowledge_policy="optional"`, `max_output_labels=1`, exact source identity, cleaned mentor input, and a trigger containing the original label plus direct evidence. The builder derives `route_key` from the input's type lines solely for audit; it does not route-filter records.

- [x] **Step 1: Write failing tests for task and hold partitioning.** Create four synthetic mentor rows: a true row, a false row whose `should_be` starts with `知识点@`, a contradictory false/`正确` row, and an insufficient false natural-language row. Assert two tasks, two holds, exact trigger kinds, root prefix, cleaned question context, and audit counts.
- [x] **Step 2: Verify red.** Run `.venv/bin/python -m pytest tests/test_mentor_tree_correction_tasks.py -q`; expected failure is missing module.
- [x] **Step 3: Implement the validated builder and CLI.** Reject pre-existing output/report paths, invalid JSON, missing exact label, and non-boolean `llm_match`. Write sorted JSON keys and a report with input/task/hold/disposition/route counts.
- [x] **Step 4: Verify green.** Run `.venv/bin/python -m pytest tests/test_mentor_tree_correction_tasks.py -q`.

### Task 3: Document and verify the offline conversion experiment preparation

**Files:**
- Modify: `docs/knowledge-label-validation.md`
- Modify: `docs/current-data-loop.md`
- Modify: `docs/superpowers/plans/2026-08-27-mentor-tree-correction-tasks.md`

- [x] **Step 1: Document the separation of direct verifier output and tree output.** Include the conversion path: raw 500 rows -> tasks/hold -> small DS tree run -> manual review; no full-source rollout before that review.
- [x] **Step 2: Document the exact CLI command with the 500-row conversion input.** The command must create a unique runtime directory and mention that all 70 direct true rows are rechecked by the tree.
- [x] **Step 3: Run the complete suite and formatting check.** Run `.venv/bin/python -m pytest -q && git diff --check`.
- [ ] **Step 4: Commit and push.** Stage only implementation, tests, docs and this plan.

## Self-Review

- Whole-tree search starts with the active top-level taxonomy children, not a fake `知识点` choice: Task 1.
- The 70 direct true rows are not automatically retained and the 415 consistent false rows can become correction tasks: Task 2.
- Contradictory or insufficient mentor records stay out of tree-generated replacement candidates: Task 2.
- No DS call or source mutation occurs while preparing the conversion experiment: all tasks and documentation.
