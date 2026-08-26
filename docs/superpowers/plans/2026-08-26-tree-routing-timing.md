# Tree Routing Timing Instrumentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist timing at tree-choice, task and concurrent batch levels so future tree-routing runs can identify latency hot nodes and decide whether to reduce candidates, shorten definitions, reduce backtracking or change concurrency.

**Architecture:** The choice client measures its prompt-build/transport/parse call; the pure search loop measures each complete chooser invocation and stores it with node metadata in `trace`; task routing measures task execution; the concurrent CLI measures scheduler queue delay and total wall time. An optional non-overwriting report summarizes percentiles, slow tasks and node-level totals from the output rows.

**Tech Stack:** Python 3 standard library (`time.perf_counter_ns`, `statistics`), existing JSONL tree router, `unittest`.

## Global Constraints

- Timings use monotonic `perf_counter_ns`, are reported in milliseconds, and never use wall-clock timestamps for durations.
- Every output row remains valid when timing is unavailable from an injected test selector.
- No timing result changes the model candidate, labels, prompt content, retry policy or concurrency automatically.
- Per-node report keys use canonical `parent_path`; no question text or model raw response enters aggregate report keys.
- Existing commands remain compatible; `--report` is optional and refuses overwrite when supplied.

---

### Task 1: Record per-choice and task timing in JSONL traces

**Files:**

- Modify: `english_knowledge_tagger/knowledge_tree_search.py`
- Modify: `english_knowledge_tagger/knowledge_tree_choice.py`
- Modify: `english_knowledge_tagger/knowledge_tree_tasks.py`
- Test: `tests/test_knowledge_tree_search.py`
- Test: `tests/test_knowledge_tree_choice.py`
- Test: `tests/test_knowledge_tree_tasks.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class TreeChoice:
    # existing fields
    model_call_elapsed_ms: float | None = None
    prompt_chars: int | None = None
    response_chars: int | None = None
```

Every trace step adds `candidate_count`, `choice_elapsed_ms`, `model_call_elapsed_ms`, `prompt_chars`, `response_chars`. Every routed task result adds `task_elapsed_ms`.

- [x] **Step 1: Write failing trace timing tests**

```python
result = search_one_candidate(...)
step = result.trace[0]
self.assertEqual(step["candidate_count"], 1)
self.assertGreaterEqual(step["choice_elapsed_ms"], 0.0)

result = client.choose(...)
self.assertGreaterEqual(result.model_call_elapsed_ms, 0.0)
self.assertEqual(result.prompt_chars, len(captured_prompt))
```

- [x] **Step 2: Verify red**

Run: `.venv/bin/python -m pytest tests/test_knowledge_tree_search.py tests/test_knowledge_tree_choice.py tests/test_knowledge_tree_tasks.py -v`

Expected: FAIL because timing fields are absent.

- [x] **Step 3: Implement monotonic measurements**

```python
started_ns = time.perf_counter_ns()
decision = choose(request)
choice_elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
```

The DS client records `prompt_chars`, `response_chars`, and a client call duration. `route_knowledge_tree_task` wraps `search_one_candidate` with another monotonic measurement.

- [x] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_knowledge_tree_search.py tests/test_knowledge_tree_choice.py tests/test_knowledge_tree_tasks.py -v`

Expected: PASS.

### Task 2: Produce batch, queue and node-level timing report

**Files:**

- Create: `english_knowledge_tagger/knowledge_tree_timing.py`
- Modify: `scripts/route_knowledge_tree.py`
- Test: `tests/test_knowledge_tree_timing.py`
- Test: `tests/test_route_knowledge_tree_cli.py`

**Interfaces:**

```python
def summarize_tree_timing(rows: Sequence[Mapping[str, object]], *, wall_elapsed_ms: float,
                          concurrency: int) -> dict[str, object]: ...
```

CLI accepts optional `--report PATH`. Each result JSONL row adds `queue_elapsed_ms`; report includes `wall_elapsed_ms`, task/queue/choice p50/p95/p99, top 20 slow tasks and node summaries ordered by total choice time.

- [x] **Step 1: Write failing report tests**

```python
report = summarize_tree_timing(rows, wall_elapsed_ms=100.0, concurrency=16)
self.assertEqual(report["nodes"][0]["parent_path"], "知识点->词法->介词")
self.assertEqual(report["nodes"][0]["calls"], 2)
self.assertEqual(report["task_elapsed_ms"]["p95"], 20.0)
```

```python
completed = subprocess.run([... , "--report", str(report_path)])
self.assertEqual(json.loads(report_path.read_text())["processed"], 1)
```

- [x] **Step 2: Verify red**

Run: `.venv/bin/python -m pytest tests/test_knowledge_tree_timing.py tests/test_route_knowledge_tree_cli.py -v`

Expected: FAIL because timing module and CLI report do not exist.

- [x] **Step 3: Implement report and scheduler timing**

```python
submitted_ns = time.perf_counter_ns()
executor.submit(_route_one, ..., submitted_ns=submitted_ns)

worker_started_ns = time.perf_counter_ns()
queue_elapsed_ms = (worker_started_ns - submitted_ns) / 1_000_000
```

Use nearest-rank percentile over finite non-negative numeric values. Empty series return null. Report only numeric aggregate/provenance fields and canonical node paths.

- [x] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_knowledge_tree_timing.py tests/test_route_knowledge_tree_cli.py -v`

Expected: PASS.

### Task 3: Document profiling interpretation and verify

**Files:**

- Modify: `docs/knowledge-label-validation.md`
- Modify: `docs/superpowers/plans/2026-08-26-tree-routing-timing.md`

- [x] **Step 1: Document one timed pilot command**

```bash
python3 scripts/route_knowledge_tree.py --input "$TREE_TASKS" --teacher-csv "$TEACHER_CSV" --output "$TIMING_DIR/results.jsonl" --report "$TIMING_DIR/timing.report.json" --limit 126 --concurrency 16 --terminal-definition-mode none
```

Document decision rules: high queue p95 suggests concurrency/service saturation; high node p95 with high candidate count suggests prune/retrieve; high no-match/backtrack at a node suggests taxonomy/definition revision; high task time with low call latency suggests local orchestration inspection.

- [x] **Step 2: Verify all tests**

Run: `.venv/bin/python -m pytest -q`

Expected: PASS.

- [x] **Step 3: Commit and push**

```bash
git add english_knowledge_tagger/knowledge_tree_search.py english_knowledge_tagger/knowledge_tree_choice.py english_knowledge_tagger/knowledge_tree_tasks.py english_knowledge_tagger/knowledge_tree_timing.py scripts/route_knowledge_tree.py tests/test_knowledge_tree_search.py tests/test_knowledge_tree_choice.py tests/test_knowledge_tree_tasks.py tests/test_knowledge_tree_timing.py tests/test_route_knowledge_tree_cli.py docs/knowledge-label-validation.md docs/superpowers/plans/2026-08-26-tree-routing-timing.md
git commit -m "feat: profile tree routing latency"
git push origin HEAD:main
```
