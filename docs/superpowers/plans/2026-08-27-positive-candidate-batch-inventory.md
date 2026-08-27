# Positive Candidate Batch Inventory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze a non-releasing manifest of the current positive-candidate labels, then scan the final source once to produce `label × route` inventory, deterministic route-review samples and a forecast of which matching questions can eventually obtain complete label evidence.

**Architecture:** The manifest generator reads the historical raw-yield ledger only for `match/n` and the authority full-sample ledger only for the human true audit. It enforces the Wilson/true/taxonomy criteria but produces a work queue, never a calibration policy. The inventory scanner streams final source exactly once and emits only aggregates plus bounded human-review samples; route policies remain manual inputs for a later materialization step.

**Tech Stack:** Python standard library, JSON/JSONL, SHA-256, existing rulebook/migration/output-label parser, `unittest`.

## Global Constraints

- Candidate qualification: one-sided 95% Wilson lower bound ≥0.70, true audit exactly `12/12`, canonical label active in the teacher rulebook.
- The Markdown ledgers are an explicit input to a queue generator only; no generated manifest may release silver, relabel or modify source labels.
- Inventory reads the final source once; do not scan it once per candidate label.
- `route_key` is metadata for aggregate and human review; no route is automatically eligible.
- Route-review samples contain only cleaned question content and the target label, never `output_all` or other historical labels.
- All outputs refuse overwrite and record input SHA-256 values.

---

### Task 1: Generate a non-releasing positive-candidate manifest

**Files:**
- Create: `english_knowledge_tagger/positive_candidate_manifest.py`
- Create: `scripts/build_positive_candidate_manifest.py`
- Create: `tests/test_positive_candidate_manifest.py`

**Interfaces:**

```python
def build_positive_candidate_manifest(
    full_sample_ledger_path: Path, *, raw_yield_ledger_path: Path,
    rulebook: KnowledgeRulebook, migration: KnowledgeTaxonomyMigration,
    output_path: Path
) -> dict[str, object]: ...
```

The output manifest contains only labels meeting every queue criterion, their historical raw yield, Wilson lower bound, true audit counts, rendered/canonical paths and ledger hashes. It separately reports taxonomy-blocked labels and never writes dispositions.

- [x] **Step 1: Write failing manifest tests.**

```python
def test_manifest_requires_wilson_true_12_and_active_taxonomy():
    report = build_positive_candidate_manifest(full, raw_yield_ledger_path=historical, ...)
    assert report["candidate_records"] == 1
    assert manifest["candidates"][0]["legacy_label"] == LABEL
    assert manifest["candidates"][0]["human_true_audit"] == {"retain": 12, "reviewed": 12}
    assert "positive_disposition" not in manifest["candidates"][0]
```

- [x] **Step 2: Verify red.**

Run: `.venv/bin/python -m pytest tests/test_positive_candidate_manifest.py -q`

Expected: FAIL because the module does not exist.

- [x] **Step 3: Implement manifest parser and CLI.**

Only parse first-column rendered knowledge rows and their DS/true fractions. Reject duplicate label rows or malformed percentages. Use SHA-256 on both ledgers and write a `positive-candidate-manifest-v1` JSON payload.

- [x] **Step 4: Verify green.**

Run: `.venv/bin/python -m pytest tests/test_positive_candidate_manifest.py -q`

Expected: PASS.

### Task 2: Build one-pass route inventory and coverage forecast

**Files:**
- Create: `english_knowledge_tagger/positive_candidate_inventory.py`
- Create: `scripts/inventory_positive_candidate_batch.py`
- Create: `tests/test_positive_candidate_inventory.py`

**Interfaces:**

```python
def inventory_positive_candidate_batch(
    source_path: Path, *, manifest_path: Path, rulebook: KnowledgeRulebook,
    migration: KnowledgeTaxonomyMigration, inventory_output_path: Path,
    route_samples_output_path: Path, sample_size_per_route: int, seed: str
) -> dict[str, object]: ...
```

For every historical source row containing at least one manifest legacy label, the scanner increments each matching label's scope/route count. It computes whether all active historical labels on that question are in the candidate manifest and counts the active labels missing from the queue. It writes at most `sample_size_per_route` deterministic hash-ranked route-review rows per label × route.

- [x] **Step 1: Write a failing one-pass inventory test.**

```python
def test_inventory_counts_each_matching_label_and_predicts_complete_queue_coverage():
    report = inventory_positive_candidate_batch(source, manifest_path=manifest, ...)
    assert inventory["labels"][LABEL_A]["route_counts"]["parent × 单选题 × 选择题"] == 1
    assert inventory["labels"][LABEL_A]["coverage"]["all_active_labels_in_candidate_queue"] == 1
    assert inventory["labels"][LABEL_A]["coverage"]["missing_active_label_counts"][LABEL_C] == 1
```

- [x] **Step 2: Verify red.**

Run: `.venv/bin/python -m pytest tests/test_positive_candidate_inventory.py -q`

Expected: FAIL because the module does not exist.

- [x] **Step 3: Implement scanner, deterministic sampling and CLI.**

Use `parse_sft_output_labels`, migration and source-byte hashing. A route-review row includes target label, source identity, route, cleaned question text and coverage flag; it excludes original `input`, `instruction` and `output_all`.

- [x] **Step 4: Verify green.**

Run: `.venv/bin/python -m pytest tests/test_positive_candidate_inventory.py -q`

Expected: PASS.

### Task 3: Record the 69-label batch workflow

**Files:**
- Create: `docs/positive-candidate-batch-workflow.md`
- Modify: `docs/document-status.md`
- Modify: `README.md`

The guide distinguishes the existing four final packets from 65 labels pending inventory, gives server commands to validate the frozen manifest and run one source scan, and explains why a queue-covered question is only a potential future `silver_question_candidate`.

- [x] **Step 1: Document exact outputs and non-release boundary.**
- [x] **Step 2: Document 35-server commands for manifest + one-pass inventory.**
- [ ] **Step 3: Run full tests, check diff, commit and push without staging concurrent human/low-quality work.**
