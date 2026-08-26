# Terminal Label Silver Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make direct per-terminal-label discriminator verdicts the auditable high-quality extraction path, while reserving candidate retrieval and tree search for labels the discriminator rejects or cannot decide.

**Architecture:** A sparse, versioned calibration policy declares what a reviewed terminal label may do with `match=true` and `match=false`. A normalised discriminator contract turns mentor-specific records into evidence rows without mutating source labels. A gate produces `silver_label_candidate` evidence, `relabel_candidate` evidence, or holds records. A question-level assembler promotes only questions whose complete historical label set has positive, policy-approved evidence; this remains silver, never HQ, because per-label verification cannot prove missing-label completeness.

**Tech Stack:** Python standard library, existing SFT label parser, teacher CSV taxonomy migration, JSONL, `unittest`.

## Global Constraints

- The unit of direct verification is `question_id × terminal label`, not a type-route candidate pool.
- `parent` versus `child` remains mandatory source scope and audit dimension; exact type route is a segmentation field, not a label-candidate hard filter.
- `match=true` rate is yield, not a correctness metric. Only a human-approved calibration policy can release positive evidence.
- A label-level release can only create `silver_label_candidate`; it cannot directly rewrite source or create `hq-v*` training data.
- `match=false` must default to hold; only an explicitly reviewed policy can emit `relabel_candidate`.
- The final discriminator adapter must be field-configurable because mentor's raw JSONL schema is not yet supplied. Do not infer it from prose or spreadsheets.
- Candidate budget/tree processing receives held false/uncertain/missing evidence after this gate; it is not used to validate a positive legacy label.

---

### Task 1: Define sparse reviewed-terminal calibration policy

**Files:**

- Create: `english_knowledge_tagger/terminal_label_calibration_policy.py`
- Create: `scripts/build_terminal_label_calibration_template.py`
- Create: `tests/test_terminal_label_calibration_policy.py`

**Interfaces:**

```json
{
  "schema_version": "terminal-label-calibration-policy-v1",
  "labels": [{
    "canonical_label": "知识点->...",
    "positive_disposition": "silver_label_candidate|hold",
    "negative_disposition": "relabel_candidate|hold",
    "calibration_stage": "screened_12|released_post_sweep",
    "audit": {"positive": {"retain": 12, "remove": 0, "uncertain": 0}}
  }]
}
```

- [x] **Step 1: Write failing policy tests**

Assert a sparse reviewed policy returns explicit dispositions for one terminal label and `hold` for every unlisted label. Reject a positive silver disposition when the audit records any reviewed positive removal.

- [x] **Step 2: Verify red**

Run: `.venv/bin/python -m pytest tests/test_terminal_label_calibration_policy.py -q`

Expected: FAIL because the policy module does not exist.

- [x] **Step 3: Implement policy and template**

Implement exact active-terminal validation against the rulebook; no glob/prefix policy. Template emits one JSONL review row per active terminal label with zeroed audit fields, and does not make any automatic release decision.

- [x] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_terminal_label_calibration_policy.py -q`

Expected: PASS.

### Task 2: Standardise direct discriminator evidence and apply the calibration gate

**Files:**

- Create: `english_knowledge_tagger/terminal_label_discriminator_gate.py`
- Create: `scripts/gate_terminal_label_discriminator.py`
- Create: `tests/test_terminal_label_discriminator_gate.py`

**Interfaces:**

```text
normalised input: question_id, parent_id, source_line, legacy_label,
canonical_label, llm_match(true|false), status(candidate|error),
model, prompt_version

output disposition: silver_label_candidate | relabel_candidate | hold
```

- [x] **Step 1: Write failing gate tests**

Use a reviewed `positive_disposition=silver_label_candidate` label and an unreviewed label. Assert only the reviewed `llm_match=true` record is released; a `llm_match=false` record remains held unless a reviewed negative disposition permits relabeling.

- [x] **Step 2: Verify red**

Run: `.venv/bin/python -m pytest tests/test_terminal_label_discriminator_gate.py -q`

Expected: FAIL because the gate module does not exist.

- [x] **Step 3: Implement strict evidence gate**

Require canonical paths, boolean verdict, non-empty source identifiers and a candidate service status. Preserve raw run provenance fields. Emit JSONL separately by disposition and a report by canonical label, scope and route when present. Reject duplicate `question_id × canonical_label` evidence rows with conflicting verdicts.

- [x] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_terminal_label_discriminator_gate.py -q`

Expected: PASS.

### Task 3: Assemble conservative silver question candidates

**Files:**

- Create: `english_knowledge_tagger/silver_question_assembly.py`
- Create: `scripts/assemble_silver_questions.py`
- Create: `tests/test_silver_question_assembly.py`

**Interfaces:**

```text
source JSONL + silver_label_candidate evidence
→ silver_question_candidate JSONL + hold/relabel report
```

- [x] **Step 1: Write failing complete-label-set test**

One source question has labels A and B. Assert it is emitted only when both have approved positive evidence; A alone remains held with `missing_positive_evidence_for_historical_label`. A source label with explicit false/relabel evidence must never be emitted.

- [x] **Step 2: Verify red**

Run: `.venv/bin/python -m pytest tests/test_silver_question_assembly.py -q`

Expected: FAIL because the assembler does not exist.

- [x] **Step 3: Implement streamable source assembly**

Build the evidence index first, scan source once, parse all historical knowledge labels, migrate them, and require every active historical label to be released positive. Output the original label set plus all evidence review IDs; status is `silver_question_candidate`, not HQ. Emit holds with compact IDs/reasons only.

- [x] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_silver_question_assembly.py -q`

Expected: PASS.

### Task 4: Integrate teacher gold and document staged experiments

**Files:**

- Modify: `docs/current-data-loop.md`
- Modify: `docs/knowledge-label-validation.md`
- Modify: `docs/superpowers/plans/2026-08-26-terminal-label-silver-loop.md`

- [x] **Step 1: Document gates and experiment order**

Document `screened_12` as preliminary silver evidence, not a 100% claim. Record 60 zero-error post-sweep audit as a stronger 95%-bound release gate. Explain that approved teacher correction rows feed k/sibling coverage only after source child resolution.

- [x] **Step 2: Verify full suite**

Run: `.venv/bin/python -m pytest -q && git diff --check`

Expected: PASS.

- [ ] **Step 3: Commit and push**

Commit only source code, tests, policy/template docs and the plan; never stage the local reviewer Markdown drafts or `uv.lock`.
