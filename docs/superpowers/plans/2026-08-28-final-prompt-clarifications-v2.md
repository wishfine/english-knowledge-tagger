# Final Prompt Clarifications v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a versioned, label-specific boundary-clarification mechanism for final-label calibration, beginning with the fixed-phrase label’s documented exclusion of bare clause-connector/function questions.

**Architecture:** A clarification JSON declares a new prompt version, source hash and per-rendered-label addenda. The final verifier loads it only when explicitly requested, appends the matching clarification outside the teacher definition, and stamps every evidence/report record with the declared v2 version and clarification hash. Existing v1 packets and runs remain byte-for-byte compatible when no clarification file is provided.

**Tech Stack:** Python standard library, existing final discriminator prompt/client/CLI, JSON, SHA-256, `unittest`.

## Global Constraints

- Teacher taxonomy and original mentor definition JSON remain immutable; clarification is a calibration prompt addendum, not a label-definition rewrite.
- Any clarification file must declare a new prompt version; v1 calibration evidence cannot be mixed with v2 policy.
- The initial addendum is justified by the authority review: `whatever` as a clause connector/function is not fixed phrase/sentence-pattern evidence.
- Source labels, packet rows and human audit records must not be modified.
- A v2 result is non-releasing until the same label’s v2 true predictions receive human review.

---

### Task 1: Write failing prompt-clarification tests

**Files:**
- Create: `tests/test_final_label_prompt_clarifications.py`

- [x] **Step 1: Assert that a valid v2 clarification appends only to its target label’s prompt and that v1 has no added text.**
- [x] **Step 2: Assert malformed version, unknown label and duplicate label entries are rejected.**
- [x] **Step 3: Run the test and verify it fails because clarification support does not exist.**

### Task 2: Implement versioned clarification loading and evidence provenance

**Files:**
- Modify: `english_knowledge_tagger/final_label_discriminator.py`
- Modify: `scripts/validate_final_label_discriminator.py`

- [x] **Step 1: Load and validate a clarification JSON against exact rendered mentor definitions.**
- [x] **Step 2: Let the client render an optional per-label addendum and emit configured prompt version.**
- [x] **Step 3: Propagate prompt version and clarification hash/path into candidate/error evidence and report.**
- [x] **Step 4: Add optional `--prompt-clarifications` CLI flag while preserving v1 defaults.**
- [x] **Step 5: Run tests and verify they pass.**

### Task 3: Freeze the initial v2 addendum and document re-calibration

**Files:**
- Create: `configs/final_label_prompt_clarifications/final-label-discriminator-v2-fixed-phrase.json`
- Modify: `docs/final-discriminator-ready-data.md`
- Modify: `docs/positive-candidate-batch-workflow.md`

- [x] **Step 1: Add the documented `whatever/whenever` clause-function exclusion without narrowing valid phrase/idiom, fixed sentence pattern or true synonym-rewrite cases.**
- [x] **Step 2: Provide the 24-record v2 rerun command and state that its evidence must be reviewed independently of v1.**

### Task 4: Verify and commit

**Files:**
- Test: `tests/test_final_label_prompt_clarifications.py`
- Test: `tests/test_final_label_discriminator.py`
- Test: `tests/test_validate_final_label_discriminator_cli.py`

- [x] **Step 1: Run focused and full test suites, plus `git diff --check`.**
- [x] **Step 2: Commit only clarification code, config, documentation, tests and plan.**
