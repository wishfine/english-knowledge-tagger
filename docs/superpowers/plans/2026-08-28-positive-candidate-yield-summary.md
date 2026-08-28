# Positive Candidate Yield Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a reproducible Markdown summary of all active positive-candidate labels and their current mentor DS match yields.

**Architecture:** Candidate manifests establish the exact label universe; the full-sample ledger supplies current `match/total` rates. The output buckets labels by rate and flags any current rate below 70% as a release hold. It never modifies source ledgers or manifests.

**Tech Stack:** Python standard library and `unittest`.

## Global Constraints

- Every manifest label appears exactly once.
- Existing calibration ledgers remain read-only.
- Low yield causes a hold, never source-label deletion.

---

### Task 1: Render summary data

**Files:**

- Create: `english_knowledge_tagger/positive_candidate_yield_summary.py`
- Test: `tests/test_positive_candidate_yield_summary.py`

- [ ] **Step 1: Write a failing test for exact one-time bucketing and low-rate holds.**
- [ ] **Step 2: Run `python3 -m unittest tests/test_positive_candidate_yield_summary.py -v` and observe the missing-module failure.**
- [ ] **Step 3: Implement manifest and ledger parsers plus a Markdown renderer.**
- [ ] **Step 4: Re-run the focused test and verify it passes.**

### Task 2: Expose CLI and generate report

**Files:**

- Create: `scripts/build_positive_candidate_yield_summary.py`
- Create: `docs/positive-candidate-ds-match-summary-20260828.md`
- Test: `tests/test_positive_candidate_yield_summary.py`

- [ ] **Step 1: Write a failing subprocess CLI test that checks non-overwriting output.**
- [ ] **Step 2: Run the focused test and observe the missing-script failure.**
- [ ] **Step 3: Implement repeatable `--manifest`, `--ledger`, and `--output` flags, then generate the 133-label report.**
- [ ] **Step 4: Run focused and full test suites.**
- [ ] **Step 5: Commit only the owned module, script, test, generated report, and this plan.**
