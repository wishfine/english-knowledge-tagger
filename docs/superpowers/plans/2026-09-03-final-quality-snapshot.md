# Final Quality Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an offline, auditable quality snapshot from completed final-discriminator evidence and the repaired v3 source without rerunning DS.

**Architecture:** Load per-label evidence from a completed run, count true/false/error/low-confidence outcomes, and exclude labels explicitly marked below the Wilson gate. Join positive evidence to the repaired v3 source by stable question identity, then emit unreleased silver question candidates only when every active historical label on a source row has an approved positive evidence row. All incomplete, false, error, excluded-label, duplicate-identity, and missing-label cases go to a hold file with a reason; source rows are never overwritten.

**Tech Stack:** Python 3 standard library, existing taxonomy parser/migration, JSONL, `unittest`.

## Global Constraints

- This is offline post-processing; no DS request is made.
- `status=error`, `llm_match=false`, low-confidence evidence, and excluded labels remain explicitly counted and auditable; model confidence is not a release switch.
- Output is `silver_question_candidate_unreleased`, not `released_silver` or training data.
- The v3 source is read-only and must be hashed in the report.

---

### Task 1: Implement evidence aggregation and source join

**Files:**

- Create: `english_knowledge_tagger/final_quality_snapshot.py`
- Test: `tests/test_final_quality_snapshot.py`

- [ ] **Step 1: Write failing tests for per-label counts, excluded labels, and complete multi-label promotion.**
- [ ] **Step 2: Run `python3 -m unittest tests/test_final_quality_snapshot.py -v` and observe the missing-module failure.**
- [ ] **Step 3: Implement `build_final_quality_snapshot(run_dir, source_path, output_dir, excluded_labels)` with deterministic JSONL outputs and SHA-256 report metadata.**
- [ ] **Step 4: Re-run the focused tests and verify they pass.**

### Task 2: Add CLI and server usage documentation

**Files:**

- Create: `scripts/build_final_quality_snapshot.py`
- Modify: `docs/final-discriminator-ready-data.md`
- Test: `tests/test_final_quality_snapshot.py`

- [ ] **Step 1: Write a failing CLI subprocess test for refusing overwrite and reporting counts.**
- [ ] **Step 2: Run the focused test and observe the missing-script failure.**
- [ ] **Step 3: Implement `--run-dir`, `--source`, repeatable `--exclude-label`, and `--output-dir`.**
- [ ] **Step 4: Run focused and full tests, then document the v3 snapshot command and the meaning of `uncertain`, `error`, and `hold`.**
- [ ] **Step 5: Commit only owned code, tests, docs, and this plan.**
