# Low-Quality Tree Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make audited low-quality labels reproducibly ready for DS tree follow-up experiments and make tree candidate outputs reproducibly reviewable by Web GPT.

**Architecture:** Add one builder that selects tree-eligible tasks by already-reviewed `keep/remove` decision and fixed route quotas, writing a DS-facing packet plus a separate audit index. Add one builder that joins tree tasks, tree results, audit strata and rulebook definitions into a reviewer-facing JSONL with no raw DS rationale. Add a terminal-choice constraint option that only appends a versioned conversion-specific negative rule when the conversion leaf is among the current terminal candidates.

**Tech Stack:** Python standard library, JSONL, existing rulebook/tree/search modules, `unittest`.

## Global Constraints

- Inputs are read-only; no command mutates source questions, historical labels, mentor verdicts, or reviewer evidence.
- Every output is non-overwriting and has a report with exact input/output counts.
- DS-facing tree packets must preserve valid `knowledge-tree-task-v1` fields and cannot contain reviewer decisions.
- Web-GPT packets must contain question context, candidate label and candidate definition but must not expose DS raw rationale or prompt traces.
- Constraint text applies only to terminal choices that offer the conversion label; it must not alter other tree levels.
- Tree results remain `relabel_candidate` evidence until external review passes; no patch/silver output is emitted.

---

### Task 1: Build audited tree follow-up packets

**Files:**
- Create: `english_knowledge_tagger/audited_tree_packet.py`
- Create: `scripts/build_audited_tree_packet.py`
- Create: `tests/test_audited_tree_packet.py`

**Interface:**

```python
build_audited_tree_packet(
    tasks_path: Path, *, evidence_path: Path, output_path: Path,
    audit_index_path: Path, report_path: Path, keep_controls: int,
    remove_quotas: tuple[RouteQuota, ...], seed: str,
) -> dict[str, object]
```

- [ ] Write a failing test using synthetic tree tasks and evidence with matching `question_id + parent_id`; request one exact route quota and two keep controls; assert deterministic selection, no duplicate task IDs, `remove` tasks only in DS packet, and reviewer decisions only in audit index.
- [ ] Run `python3 -m unittest tests.test_audited_tree_packet -v`; expect import failure.
- [ ] Implement exact identity joins, route-prefix quota selection, SHA-256 seeded ranking, and non-overwrite guards. Reject missing evidence, duplicate identities, quota shortfall, and a task not eligible for tree routing.
- [ ] Run the focused test and existing tree-task tests; expect all pass.

### Task 2: Build tree-result reviewer packets

**Files:**
- Create: `english_knowledge_tagger/tree_candidate_review_packet.py`
- Create: `scripts/build_tree_candidate_review_packet.py`
- Create: `tests/test_tree_candidate_review_packet.py`

**Interface:**

```python
build_tree_candidate_review_packet(
    tasks_path: Path, *, audit_index_path: Path, results_path: Path,
    teacher_csv_path: Path, output_path: Path,
) -> dict[str, object]
```

- [ ] Write a failing test with one terminal result and one `budget_exhausted` result; assert every row retains question identity/context, terminal rows include only the active candidate definition, and raw response/trace/rationale are omitted.
- [ ] Run `python3 -m unittest tests.test_tree_candidate_review_packet -v`; expect import failure.
- [ ] Implement exact task-ID joins, active rulebook definition lookup, result status validation and ordered output. Reject unmatched rows and unknown terminal candidates.
- [ ] Run the focused test and existing rulebook/tree tests; expect all pass.

### Task 3: Add conversion terminal constraint

**Files:**
- Modify: `english_knowledge_tagger/knowledge_tree_choice.py`
- Modify: `scripts/route_knowledge_tree.py`
- Modify: `tests/test_knowledge_tree_choice.py`
- Modify: `tests/test_route_knowledge_tree_cli.py`

- [ ] Write a failing unit test that constructs a terminal request offering `知识点->词汇->构词法->转化法`, sets the constraint, and asserts the prompt contains the rule; assert a non-conversion terminal request does not contain it.
- [ ] Run `python3 -m unittest tests.test_knowledge_tree_choice -v`; expect missing parameter failure.
- [ ] Add an optional named constraint enum and pass it from the CLI into the choice client. Use the exact rule: `词缀、拼写增删、-ing/-ed、复数、三单、比较级等词形变化不是转化法；只有词形不变而词性改变才可选转化法。`.
- [ ] Run the focused unit/CLI tests; expect all pass.

### Task 4: Document and verify

**Files:**
- Modify: `docs/low-quality-label-remediation.md`
- Modify: this plan

- [ ] Document the T1.1 packet/review commands and the shared packet-builder contract for Theme-1, Order-1 and Argument-1.
- [ ] Run all non-pytest test files with `PYTHONPATH="$PWD/tests"` and exclude only the two known pytest-only files.
- [ ] Run `git diff --check`, commit implementation/tests/docs, and push to `origin main`.

## Self-Review

- Task 1 makes Theme/Order/Argument packet preparation deterministic without an implicit label-specific route rule.
- Task 2 prevents Web GPT from seeing DS thought traces while retaining candidate definition and question evidence.
- Task 3 changes only conversion leaf selection, so sibling tree behavior is stable.
- Task 4 records the actual commands and test evidence.
