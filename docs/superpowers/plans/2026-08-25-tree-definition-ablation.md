# Tree Terminal Definition Ablation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a reproducible 3×2 ablation of compressed terminal definitions in DS taxonomy-tree routing and summarize replacement stability before changing the production prompt.

**Architecture:** Add an explicit terminal-definition mode to the existing one-step tree-choice prompt and persist it in every result row. A dependency-free analysis module will validate six named output JSONLs, summarize candidate/status agreement among the three repeats in each mode, and separately report the `replace` trigger slice.

**Tech Stack:** Python 3 standard library, JSONL, existing DS-V4 tree router, `unittest`.

## Global Constraints

- All six runs must reuse byte-identical frozen `tasks.jsonl`, teacher CSV, candidate policy, model, search budget and concurrency.
- The sole prompt ablation is terminal compressed definitions: `compressed` versus `none`.
- Temperature remains 0.0; observed repeat differences are recorded as service/output variability, not interpreted as stochastic sampling certainty.
- Tree candidates remain audit evidence, never automatic patches or final labels.

---

### Task 1: Make terminal definitions an explicit router mode

**Files:**

- Modify: `english_knowledge_tagger/knowledge_tree_choice.py`
- Modify: `scripts/route_knowledge_tree.py`
- Test: `tests/test_knowledge_tree_choice.py`
- Test: `tests/test_route_knowledge_tree_cli.py`

**Interfaces:**

```python
TERMINAL_DEFINITION_MODES = frozenset({"compressed", "none"})
def build_tree_choice_prompt(request, tree, *, terminal_definition_mode: str = "compressed") -> str: ...
class KnowledgeTreeChoiceClient:
    def __init__(..., terminal_definition_mode: str = "compressed", ...): ...
```

The CLI receives `--terminal-definition-mode compressed|none` and writes that exact value into every JSONL result row.

- [x] **Step 1: Write failing definition-mode tests**

```python
prompt = build_tree_choice_prompt(request, tree, terminal_definition_mode="none")
self.assertIn(candidate_path, prompt)
self.assertNotIn("按发音选择 a/an。", prompt)

completed = run_router("--terminal-definition-mode", "none")
self.assertEqual(result["terminal_definition_mode"], "none")
```

- [x] **Step 2: Verify red**

Run: `.venv/bin/python -m pytest tests/test_knowledge_tree_choice.py tests/test_route_knowledge_tree_cli.py -v`

Expected: FAIL because neither prompt nor output accepts the mode.

- [x] **Step 3: Implement mode validation and provenance**

```python
if terminal_definition_mode not in TERMINAL_DEFINITION_MODES:
    raise ValueError("unsupported terminal_definition_mode")
definition = tree.definition(path) if terminal_definition_mode == "compressed" else None
```

Pass the CLI argument to the client and add `terminal_definition_mode` in successful and error result rows.

- [x] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_knowledge_tree_choice.py tests/test_route_knowledge_tree_cli.py -v`

Expected: PASS.

### Task 2: Summarize three-repeat stability for each mode

**Files:**

- Create: `english_knowledge_tagger/knowledge_tree_run_analysis.py`
- Create: `scripts/analyze_knowledge_tree_runs.py`
- Test: `tests/test_knowledge_tree_run_analysis.py`
- Test: `tests/test_analyze_knowledge_tree_runs_cli.py`

**Interfaces:**

```python
def summarize_run_groups(
    groups: Mapping[str, tuple[tuple[str, tuple[Mapping[str, object], ...]], ...]]
) -> dict[str, object]: ...
```

CLI accepts exactly three `--with-definitions name=path` and exactly three `--without-definitions name=path` arguments and writes a non-overwriting JSON report.

- [x] **Step 1: Write failing analysis tests**

```python
report = summarize_run_groups({"compressed": compressed_runs, "none": none_runs})
self.assertEqual(report["groups"]["compressed"]["replace"]["all_three_candidate_agreement"], 1.0)
self.assertLess(report["groups"]["none"]["replace"]["all_three_decision_agreement"], 1.0)
```

- [x] **Step 2: Verify red**

Run: `.venv/bin/python -m pytest tests/test_knowledge_tree_run_analysis.py tests/test_analyze_knowledge_tree_runs_cli.py -v`

Expected: FAIL because the analysis module and CLI do not exist.

- [x] **Step 3: Implement run validation and metrics**

```python
decision = (row["status"], row.get("candidate_label"))
all_three_decision_agreement = mean(len(set(decisions)) == 1 for task_id in common_ids)
all_three_candidate_agreement = mean(
    all(status == "tree_candidate" for status, _ in decisions) and len({label for _, label in decisions}) == 1
    for task_id in common_ids
)
```

Report per run: task count, status counts, mean trace length and mean no-match/backtrack count. Report each group for all common tasks and the `trigger_kinds` containing `replace` slice. Reject duplicate task IDs, mixed mode rows, and fewer/more than three runs per mode.

- [x] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_knowledge_tree_run_analysis.py tests/test_analyze_knowledge_tree_runs_cli.py -v`

Expected: PASS.

### Task 3: Document six-run protocol and verify repository

**Files:**

- Modify: `docs/knowledge-label-validation.md`
- Modify: `docs/superpowers/plans/2026-08-25-tree-definition-ablation.md`

- [x] **Step 1: Document the six immutable runs**

```bash
for repeat in 1 2 3; do
  python3 scripts/route_knowledge_tree.py --input "$TREE_TASKS" --teacher-csv "$TEACHER_CSV" --output "$TREE_DIR/compressed-$repeat.jsonl" --limit 100 --concurrency 16 --terminal-definition-mode compressed
  python3 scripts/route_knowledge_tree.py --input "$TREE_TASKS" --teacher-csv "$TEACHER_CSV" --output "$TREE_DIR/none-$repeat.jsonl" --limit 100 --concurrency 16 --terminal-definition-mode none
done
```

- [x] **Step 2: Verify full repository**

Run: `.venv/bin/python -m pytest -q`

Expected: PASS.

- [x] **Step 3: Commit and push**

```bash
git add english_knowledge_tagger/knowledge_tree_choice.py english_knowledge_tagger/knowledge_tree_run_analysis.py scripts/route_knowledge_tree.py scripts/analyze_knowledge_tree_runs.py tests/test_knowledge_tree_choice.py tests/test_route_knowledge_tree_cli.py tests/test_knowledge_tree_run_analysis.py tests/test_analyze_knowledge_tree_runs_cli.py docs/knowledge-label-validation.md docs/superpowers/plans/2026-08-25-tree-definition-ablation.md
git commit -m "feat: add tree definition ablation analysis"
git push origin HEAD:main
```
