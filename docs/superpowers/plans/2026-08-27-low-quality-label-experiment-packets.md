# Low-Quality Label Experiment Packets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the offline preparation for the conversion tree T1 experiment and the mixed-POS M1 blind review, so conversion needs only a DS tree call after service recovery and mixed-POS needs only human/Gemini review before its next decision.

**Architecture:** A single deterministic packet module creates two kinds of output. Conversion T1 copies a stratified 60-row subset of existing `knowledge-tree-task-v1` rows so it can be passed directly to `route_knowledge_tree.py`, while a separate index records non-model strata. Mixed-POS M1 emits a blind packet with the teacher definition, route and question text but hides historical `output_all`, `llm_match`, `llm_reason` and `llm_should_be`; a separate audit index preserves those fields for later reconciliation.

**Tech Stack:** Python standard library, JSONL, SHA-256 deterministic ranking, existing rulebook reader, `unittest`.

## Global Constraints

- Neither builder calls DS/Gemini or mutates source, mentor verifier JSONL, history labels, or tree results.
- All output paths must be distinct and must not already exist.
- Reviewer-facing mixed-POS output must not leak model verdicts, model replacement suggestions, or legacy `output_all`.
- Audit index outputs contain source/model evidence and are not reviewer-facing.
- Tree candidate output remains `relabel_candidate` evidence; no builder emits a patch or silver result.
- Do not stage incomplete review ledgers or `uv.lock`.

---

### Task 1: Deterministic conversion T1 tree input packet

**Files:**
- Create: `english_knowledge_tagger/low_quality_label_review_packets.py`
- Create: `scripts/build_conversion_tree_t1_packet.py`
- Create: `tests/test_low_quality_label_review_packets.py`

**Interfaces:**

```python
build_conversion_tree_t1_packet(
    tasks_path: Path, *, output_path: Path, audit_index_path: Path, seed: str,
    quotas: ConversionTreeT1Quotas = DEFAULT_CONVERSION_T1_QUOTAS,
    boundary_question_ids: Mapping[str, tuple[str, ...]] = DEFAULT_CONVERSION_BOUNDARIES,
) -> dict[str, object]
```

Default output has exactly 60 unique tasks: 15 direct-true rechecks (including completed human boundary cases), 10 derived, 10 word-form, 5 vocabulary, 5 fixed-phrase, 5 grammar direct-false suggestions, then 4 translation, 3 spelling and 3 parent-fill route-diversity tasks selected from the remaining rows. Every non-fixed selection is ordered by SHA-256 over `seed + task_id`; the audit index maps each task ID to its selection stratum.

- [x] **Step 1: Write a failing test.** Build synthetic tree tasks covering all strata; assert exact total, no duplicate task IDs, known boundary inclusion, stable same-seed task IDs, and an audit index that contains strata while task rows remain routable tree-task rows.
- [x] **Step 2: Verify red.** Run `.venv/bin/python -m pytest tests/test_low_quality_label_review_packets.py -q`; expected missing module failure.
- [x] **Step 3: Implement deterministic selection and CLI.** Validate direct trigger types, required task fields, all quotas and output non-overwrite. Preserve input task JSON unchanged in the DS-facing output.
- [x] **Step 4: Verify green.** Run `.venv/bin/python -m pytest tests/test_low_quality_label_review_packets.py -q`.

### Task 2: Mixed-POS M1 blind review packet

**Files:**
- Modify: `english_knowledge_tagger/low_quality_label_review_packets.py`
- Create: `scripts/build_mixed_pos_m1_review_packet.py`
- Modify: `tests/test_low_quality_label_review_packets.py`

**Interfaces:**

```python
build_mixed_pos_m1_review_packet(
    verification_path: Path, *, verify_label: str, teacher_definition: str,
    blind_output_path: Path, audit_index_path: Path, seed: str,
) -> dict[str, object]
```

It selects every `llm_match=true` row in the exact legal route `parent × 单选题 × 选择题`, plus exactly 12 false rows per direct-suggestion stratum: how-question, fixed phrase, same-POS vocabulary and connector vocabulary. The blind packet contains candidate label, teacher definition, identity, route and raw question input only. It globally hash-shuffles selected rows to avoid stratum order leakage. The audit index maps review IDs to direct evidence and stratum.

- [x] **Step 1: Extend the failing test.** Use synthetic legal and illegal-route verifier rows plus four false strata; assert all legal true rows are present, all four false buckets select the requested count, illegal route is excluded, reviewer fields contain no `llm_` or `output_all`, and the audit index does contain direct evidence.
- [x] **Step 2: Verify red.** Run the same test file; expected missing function failure.
- [x] **Step 3: Implement blind packet, rulebook CLI and report.** CLI receives teacher CSV, resolves the target active terminal definition, and rejects insufficient false strata rather than silently changing quota.
- [x] **Step 4: Verify green.** Run `.venv/bin/python -m pytest tests/test_low_quality_label_review_packets.py -q`.

### Task 3: Add operational commands and verify actual experiment packets

**Files:**
- Modify: `docs/low-quality-label-remediation.md`
- Modify: `docs/superpowers/plans/2026-08-27-low-quality-label-experiment-packets.md`

- [x] **Step 1: Document server commands.** Include conversion packet generation plus DS tree run command, and mixed-POS blind/audit packet generation plus human/Gemini review boundary.
- [x] **Step 2: Run both builders on the supplied local JSONL files.** Confirm conversion has 60 rows and M1 has 100 rows (52 legal true + 48 false) before claiming readiness.
- [x] **Step 3: Run `.venv/bin/python -m pytest -q && git diff --check`.**
- [x] **Step 4: Commit and push only implementation, tests, docs and this plan.**

## Self-Review

- Conversion direct true rows remain rechecks, not keep candidates: Task 1.
- Mixed-POS M1 reviewer cannot see DS evidence or legacy labels: Task 2.
- All review groups are deterministic, auditable and independent from source mutation: Tasks 1--3.
