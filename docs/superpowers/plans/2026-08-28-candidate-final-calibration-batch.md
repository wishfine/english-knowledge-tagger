# Candidate Final Calibration Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Join the existing human-review identity sample with the 69 materialized final packets in one review-sample pass, producing independent final-v1 calibration packets and coverage reports without calling DS.

**Architecture:** The batch builder reads `batch.index.json`, validates each referenced packet, and indexes the small human-review JSONL by `verify_label × question_id`. It emits one sanitized calibration packet for each label that has review identities, while an index reports labels with no review coverage or records missing from the final packet. Human verdict text is never copied into model-visible fields.

**Tech Stack:** Python standard library, JSON/JSONL, SHA-256, existing final packet schema, `unittest`.

## Global Constraints

- No DS call, source scan or source-label modification is allowed.
- The packet batch index is the only accepted source for packet paths and labels.
- Calibration identity and stratum remain audit fields; final prompt continues to use only label, definition and question text.
- A missing reviewed question is evidence of packet/route/input mismatch, never a deletion instruction.
- Outputs must refuse overwrite and record hashes of both source packet index and review sample.

---

### Task 1: Write a failing batch-join test

**Files:**
- Create: `tests/test_candidate_final_calibration_batch.py`

- [x] **Step 1: Build a fixture with two packet labels, one reviewed question missing from its final packet and one review label outside the batch.**
- [x] **Step 2: Assert per-label selected counts, missing identities, strata and that no original output/instruction fields appear in calibration rows.**
- [x] **Step 3: Run the test and verify it fails because the batch module is absent.**

### Task 2: Implement batch calibration packet construction and CLI

**Files:**
- Create: `english_knowledge_tagger/candidate_final_calibration_batch.py`
- Create: `scripts/build_candidate_final_calibration_batch.py`

- [x] **Step 1: Validate the packet batch index and load review identities once.**
- [x] **Step 2: Stream each packet once, emit rows only for matching reviewed identities and preserve only safe audit fields.**
- [x] **Step 3: Write `calibration.index.json` with full sample, eligible and missing counts by label and stratum.**
- [x] **Step 4: Add a non-overwriting CLI.**
- [x] **Step 5: Run focused tests and verify they pass.**

### Task 3: Document the server preparation step

**Files:**
- Modify: `docs/final-discriminator-ready-data.md`
- Modify: `docs/positive-candidate-batch-workflow.md`

- [x] **Step 1: Record the required server location of the 9,191-row review identity sample.**
- [x] **Step 2: Add an offline command that creates calibration packets but does not claim final-v1 policy calibration has happened.**

### Task 4: Verify and commit

**Files:**
- Test: `tests/test_candidate_final_calibration_batch.py`
- Test: `tests/test_candidate_final_packet_batch.py`
- Test: `tests/test_final_label_calibration_packet.py`

- [x] **Step 1: Run focused and full test suites, plus `git diff --check`.**
- [x] **Step 2: Commit only the calibration batch implementation, tests, docs and plan.**
