# Effective Candidate-Pool Ablation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the 20 validation items with genuinely new v0.2 alternatives into paired v0.1/v0.2 DS packets, then summarize six repeat runs without treating model preference as label truth.

**Architecture:** A packet builder joins the frozen v0.1/v0.2 packets to the effective-coverage comparison output and writes same-order 20-row packets. An analyzer requires exactly three baseline and three candidate verdict files, measures within-mode decision stability and identifies cases where v0.2 consistently chooses a newly available label. Human review remains the only correctness decision.

**Tech Stack:** Python standard library, JSONL, existing DS validation CLI, `unittest`.

## Global Constraints

- Select only coverage rows with non-empty `newly_available_alternative_labels`; `reclassified_only_rows` are excluded.
- Baseline and candidate packets must contain the same review IDs, source identity, target label and question context hash, in the same deterministic order.
- The six DS runs are candidates only; no source labels, patches or HQ samples are changed.
- The analyzer records agreement and candidate selection, not accuracy; human blind review decides whether a newly selected label is correct.
- Each run uses a fresh output file and the same endpoint, model, concurrency, prompt version and 20-row frozen packet.

---

### Task 1: Build paired 20-row effective-coverage packets

**Files:**

- Create: `english_knowledge_tagger/knowledge_effective_pool_ablation.py`
- Create: `scripts/build_effective_pool_ablation_packets.py`
- Create: `tests/test_knowledge_effective_pool_ablation.py`

**Interface:**

```python
def build_effective_pool_ablation_packets(
    baseline_packet: Path,
    candidate_packet: Path,
    coverage_packet: Path,
    *,
    baseline_output_path: Path,
    candidate_output_path: Path,
) -> dict[str, object]: ...
```

- [x] **Step 1: Write the failing paired-packet test**

```python
report = build_effective_pool_ablation_packets(v01, v02, coverage, ...)
self.assertEqual(report["selected_rows"], 1)
self.assertEqual(v01_subset_review_ids, ["effective"])
self.assertEqual(v02_subset_review_ids, ["effective"])
```

The fixture contains one effective coverage row and one reclassification-only row; only the effective row may be emitted.

- [x] **Step 2: Verify red**

Run: `.venv/bin/python -m pytest tests/test_knowledge_effective_pool_ablation.py -q`

Expected: FAIL because the builder does not exist.

- [x] **Step 3: Implement strict selection**

Read all packets with unique `review_id`; require the coverage row's immutable identity to agree with both packets. Select non-empty `newly_available_alternative_labels`, preserve baseline packet ordering, require equal context SHA-256 between paired rows, and refuse output overwrite. Report selected rows by target parent and all newly available labels.

- [x] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_knowledge_effective_pool_ablation.py -q`

Expected: PASS.

### Task 2: Analyze three v0.1 and three v0.2 flat-validation runs

**Files:**

- Create: `english_knowledge_tagger/knowledge_effective_pool_ablation_analysis.py`
- Create: `scripts/analyze_effective_pool_ablation.py`
- Create: `tests/test_knowledge_effective_pool_ablation_analysis.py`

**Interface:**

```python
def summarize_effective_pool_ablation(
    baseline_runs: tuple[Run, Run, Run],
    candidate_runs: tuple[Run, Run, Run],
    *,
    new_labels_by_review_id: Mapping[str, tuple[str, ...]],
) -> dict[str, object]: ...
```

- [x] **Step 1: Write failing decision-analysis tests**

```python
report = summarize_effective_pool_ablation(...)
self.assertEqual(report["candidate"]["all_three_decision_agreement"], 1.0)
self.assertEqual(report["comparison"]["candidate_consistently_selects_new_label"], 1)
```

- [x] **Step 2: Verify red**

Run: `.venv/bin/python -m pytest tests/test_knowledge_effective_pool_ablation_analysis.py -q`

Expected: FAIL because the analyzer does not exist.

- [x] **Step 3: Implement stability and effect summaries**

For a decision use `(status, verdict, candidate_coverage, best_label)`. Require exactly three named runs per mode and identical review-ID sets. Report verdict/status counts, three-repeat decision agreement, unanimous cross-mode decision disagreements, and IDs where v0.2 unanimously returns `replace` to a coverage-provided new label. Include a 20-row review table with IDs and decisions only, never question text/evidence/raw response.

- [x] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_knowledge_effective_pool_ablation_analysis.py -q`

Expected: PASS.

### Task 3: Document and verify the six-run experiment

**Files:**

- Modify: `docs/knowledge-label-validation.md`
- Modify: `docs/current-data-loop.md`
- Modify: `docs/superpowers/plans/2026-08-26-effective-pool-ablation.md`

- [x] **Step 1: Document packet build, six runs and analysis commands**

Use `--limit 20 --concurrency 16`; pass v0.1 subset to three baseline runs and v0.2 subset to three candidate runs. The output manifest records source paths and all six outputs.

- [x] **Step 2: Run all tests**

Run: `.venv/bin/python -m pytest -q && git diff --check`

Expected: PASS.

- [x] **Step 3: Commit and push**

```bash
git add english_knowledge_tagger/knowledge_effective_pool_ablation.py \
  scripts/build_effective_pool_ablation_packets.py tests/test_knowledge_effective_pool_ablation.py \
  english_knowledge_tagger/knowledge_effective_pool_ablation_analysis.py \
  scripts/analyze_effective_pool_ablation.py tests/test_knowledge_effective_pool_ablation_analysis.py \
  docs/knowledge-label-validation.md docs/current-data-loop.md \
  docs/superpowers/plans/2026-08-26-effective-pool-ablation.md
git commit -m "feat: analyze effective knowledge pool ablations"
git push origin HEAD:main
```
