# Positive Candidate Delta Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze the 64 labels newly eligible under the latest authority ledger as an incremental, non-releasing fast-screening batch without reprocessing the 69-label snapshot already materialized on 35.

**Architecture:** A delta builder compares a full latest positive-candidate manifest with a prior snapshot and writes only new candidates in the same downstream-compatible manifest schema. It preserves the latest ledger hashes plus the base manifest hash. A separate guidance configuration defaults every delta label to `soft_typical`, because teacher CSV inspection found no new explicit route-exclusion wording.

**Tech Stack:** Python standard library, JSON, SHA-256, existing manifest schema and route-guidance loader, `unittest`.

## Global Constraints

- Delta qualification remains one-sided Wilson lower bound ≥0.70, true audit exactly 12/12 and active teacher taxonomy; the builder cannot create new eligibility.
- The 69-label 20260827 snapshot is immutable and must not be overwritten or regenerated.
- Delta output is non-releasing and can only begin final packet construction, calibration and later DS validation.
- No route filtering is inferred from “常见题型”; the delta guidance default is `soft_typical`.
- The authority Markdown ledgers are user-owned inputs and must not be committed by this work.

---

### Task 1: Write failing delta manifest tests

**Files:**
- Create: `tests/test_positive_candidate_delta_manifest.py`

- [x] **Step 1: Create fixture manifests where the latest queue has one prior and one new candidate.**
- [x] **Step 2: Assert the delta contains only the new candidate, records both manifest hashes and rejects a prior label missing from latest.**
- [x] **Step 3: Run the focused test and verify it fails because the delta module is absent.**

### Task 2: Implement delta builder, CLI and frozen 64-label snapshot

**Files:**
- Create: `english_knowledge_tagger/positive_candidate_delta_manifest.py`
- Create: `scripts/build_positive_candidate_delta_manifest.py`
- Create: `configs/candidate_batches/positive-candidates-20260828-delta.json`
- Create: `configs/candidate_batches/positive-candidates-20260828-delta.route-guidance.json`

- [x] **Step 1: Validate both manifests against `positive-candidate-manifest-v1`; enforce exact label/canonical identity for their overlap.**
- [x] **Step 2: Write only labels in latest but not base and retain latest authority ledger input hashes.**
- [x] **Step 3: Bind the all-soft guidance config to the delta SHA and validate it through the existing loader.**
- [x] **Step 4: Run focused tests and snapshot validation.**

### Task 3: Document fast-screening expansion

**Files:**
- Create: `docs/positive-candidate-delta-20260828.md`
- Modify: `docs/positive-candidate-batch-workflow.md`
- Modify: `docs/document-status.md`

- [x] **Step 1: Record 133 total / 64 delta labels, grouped by top-level taxonomy, and emphasize no labels were released.**
- [x] **Step 2: Document incremental one-scan packet materialization, then calibration packet construction, using the new delta paths.**

### Task 4: Verify and commit

**Files:**
- Test: `tests/test_positive_candidate_delta_manifest.py`
- Test: `tests/test_candidate_route_guidance.py`
- Test: `tests/test_candidate_final_packet_batch.py`

- [x] **Step 1: Run focused and full test suites plus `git diff --check`.**
- [x] **Step 2: Commit only delta code, configs, docs, tests and plan.**
