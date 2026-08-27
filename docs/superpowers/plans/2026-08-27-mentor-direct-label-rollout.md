# Mentor Direct Label Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Select productive labels using a one-sided Wilson yield bound, then run one manually calibrated label over every matching source record with the exact mentor-v1 verifier prompt and full evidence lineage.

**Architecture:** The priority analyser consumes mentor's machine-readable `overall_summary.json`, never a manually maintained ledger, and classifies only yield eligibility. A streaming packet builder selects every source record containing one exact historical knowledge label. The verifier reproduces mentor-v1 prompt fields and response contract, then writes `terminal-label-discriminator-evidence-v1` rows compatible with the existing calibration gate. A sparse policy remains manually authored; the first policy contains only the audited noun-phrase discrimination label.

**Tech Stack:** Python standard library, JSON/JSONL, `urllib`, `concurrent.futures`, existing teacher rulebook/migration/calibration gate, `unittest`.

## Global Constraints

- The 500-record result is a yield sample only when its sample selection is random or stable stratified; no script may call it an accuracy estimate.
- Priority condition: one-sided 95% Wilson lower confidence bound for `match=true` is at least 0.70, `error=0`, and at least 12 true records.
- The full run must use prompt version `mentor-direct-v1`: same label-definition JSON, relationship sections, `output_all`, 2,000-character source-input truncation, `temperature=0.1`, `max_tokens=512`, and disabled thinking.
- The preliminary policy is a human decision. Do not parse incomplete Markdown calibration ledgers to create it.
- `match=false` for the first label remains `hold`; no auto-removal follows from the initial positive-label rollout.
- Source JSONL is read-only; all packet, verdict, gate, and 60-sample outputs are new files that refuse overwrite.

---

### Task 1: Rank mentor verification summaries with a one-sided Wilson bound

**Files:**
- Create: `english_knowledge_tagger/mentor_verification_priority.py`
- Create: `scripts/rank_mentor_verification_report.py`
- Create: `tests/test_mentor_verification_priority.py`

**Interfaces:**

```python
assess_mentor_verification_summary(summary: Mapping[str, object], *, target_lcb: float = 0.70) -> tuple[dict[str, object], ...]
```

The function reads mentor `overall_summary.json` entries (`category`, `label_stats[label] = {total, match, mismatch, error}`) and emits one row per label with `match_rate`, `wilson_lower_95`, and one of `rollout_candidate`, `hold_service_errors`, `hold_too_few_true`, or `hold_yield_below_threshold`.

- [x] **Step 1: Write the failing tests**

```python
def test_500_sample_label_requires_at_least_367_matches_for_a_70_percent_lower_bound():
    rows = assess_mentor_verification_summary(summary_with(366, 500))
    assert rows[0]["status"] == "hold_yield_below_threshold"
    rows = assess_mentor_verification_summary(summary_with(367, 500))
    assert rows[0]["status"] == "rollout_candidate"

def test_service_error_prevents_rollout_even_when_match_rate_is_high():
    row = assess_mentor_verification_summary(summary_with(490, 500, error=1))[0]
    assert row["status"] == "hold_service_errors"
```

- [x] **Step 2: Verify red**

Run: `.venv/bin/python -m pytest tests/test_mentor_verification_priority.py -q`

Expected: FAIL because the module does not exist.

- [x] **Step 3: Implement summary parsing and CLI**

The CLI accepts `--summary`, `--output-json`, and `--output-csv`; rejects existing outputs; outputs only machine-derived yield status; prints candidate count. It must never claim that a model match rate is label accuracy.

- [x] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_mentor_verification_priority.py -q`

Expected: PASS.

### Task 2: Build an exact-label, full-source mentor-v1 packet

**Files:**
- Create: `english_knowledge_tagger/mentor_direct_rollout.py`
- Create: `scripts/build_mentor_label_rollout_packet.py`
- Create: `tests/test_mentor_direct_rollout.py`

**Interfaces:**

```python
build_mentor_label_rollout_packet(
    source_path: Path, *, verify_label: str, label_definitions_path: Path,
    output_path: Path
) -> dict[str, object]
```

The source is streamed once. One output row is written for every exact historical `知识点@...` occurrence matching `verify_label`; rows preserve source identity, raw input, raw instruction and full raw `output` as `output_all`.

- [x] **Step 1: Write failing packet/prompt tests**

```python
def test_packet_selects_only_exact_historical_label_and_keeps_source_identity():
    report = build_mentor_label_rollout_packet(source, verify_label=LABEL, ...)
    assert report["selected_records"] == 1
    assert packet_row["source_line"] == 2
    assert packet_row["output_all"] == source_row["output"]

def test_mentor_v1_prompt_removes_only_declared_type_and_picture_lines_then_truncates_to_2000():
    prompt = build_mentor_direct_v1_prompt(packet_row, label_definition)
    assert "题型结构为" not in prompt
    assert "当前题目打的全部标签" in prompt
```

- [x] **Step 2: Verify red**

Run: `.venv/bin/python -m pytest tests/test_mentor_direct_rollout.py -q`

Expected: FAIL because the module does not exist.

- [x] **Step 3: Implement exact prompt/packet builder**

Reproduce mentor code's label definition, examples, similar/cooccur/exclusive text, `output_all`, `chat_template_kwargs.enable_thinking=false`, 2,000-character truncation, and JSON response parser. Do not silently substitute teacher CSV definitions for the calibrated mentor definition JSON.

- [x] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_mentor_direct_rollout.py -q`

Expected: PASS.

### Task 3: Run full packet and emit gate-compatible evidence

**Files:**
- Modify: `english_knowledge_tagger/mentor_direct_rollout.py`
- Create: `scripts/validate_mentor_label_rollout.py`
- Modify: `english_knowledge_tagger/terminal_label_discriminator_gate.py`
- Modify: `tests/test_terminal_label_discriminator_gate.py`
- Modify: `tests/test_mentor_direct_rollout.py`

**Interfaces:**

```python
MentorDirectClient.verify(MentorDirectRequest) -> MentorDirectResult
```

CLI arguments include `--input`, `--label-definitions`, `--teacher-csv`, `--taxonomy-migration`, `--output`, `--limit`, and `--concurrency`. Candidate response rows map the exact historical label to an active canonical label and emit `terminal-label-discriminator-evidence-v1`; malformed/service responses have `status="error"` and `llm_match=null`.

- [x] **Step 1: Write failing client and gate tests**

```python
def test_client_emits_gate_compatible_candidate_evidence_for_match_true():
    evidence = result_to_evidence(...)
    assert evidence["llm_match"] is True
    assert evidence["canonical_label"] == CANONICAL_LABEL

def test_gate_holds_error_evidence_without_requiring_a_boolean_match():
    result = gate_terminal_label_discriminator([error_evidence], ...)
    assert result.hold[0]["disposition_reason"] == "discriminator_status_error"
```

- [x] **Step 2: Verify red**

Run: `.venv/bin/python -m pytest tests/test_mentor_direct_rollout.py tests/test_terminal_label_discriminator_gate.py -q`

Expected: FAIL because the verifier/evidence conversion is missing and gate rejects null error verdicts.

- [x] **Step 3: Implement bounded concurrent runner and error semantics**

Use a bounded thread pool, preserve input order, retry transport failures at most three times, and write rows immediately. Candidate rows use mentor-v1 response semantics; error rows always route to hold. Do not use `should_be` to replace labels.

- [x] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_mentor_direct_rollout.py tests/test_terminal_label_discriminator_gate.py -q`

Expected: PASS.

### Task 4: Add the human-approved first preliminary policy and operation guide

**Files:**
- Create: `configs/terminal_label_calibration_policies/mentor-direct-v1-preliminary-20260827.json`
- Modify: `docs/data-cleaning-playbook.md`
- Modify: `docs/document-status.md`
- Modify: `docs/superpowers/plans/2026-08-27-mentor-direct-label-rollout.md`

**Policy record:**

```json
{
  "canonical_label": "知识点->词汇->词汇辨析->名词（短语）辨析",
  "positive_disposition": "silver_label_candidate",
  "negative_disposition": "hold",
  "calibration_stage": "screened_12",
  "audit": {
    "positive": {"retain": 12, "remove": 0, "uncertain": 0},
    "negative": {"retain": 1, "remove": 10, "uncertain": 1}
  }
}
```

- [x] **Step 1: Document the exact production sequence**

Document: rank from `overall_summary.json`; build the noun-phrase discrimination packet; run with prompt `mentor-direct-v1`; gate with this sparse policy; independently sample 60 rows only from its new full-run `silver-label-evidence.jsonl`; no false deletion.

- [x] **Step 2: Verify complete suite and formatting**

Run: `.venv/bin/python -m pytest -q && git diff --check`

Expected: PASS.

- [x] **Step 3: Commit and push**

Commit only implementation, tests, policy, documentation and this plan. Do not stage incomplete human review ledgers or `uv.lock`.

### Task 5: Build the independent 60-positive post-sweep sample

**Files:**
- Create: `english_knowledge_tagger/silver_post_sweep_sample.py`
- Create: `scripts/sample_silver_post_sweep.py`
- Create: `tests/test_silver_post_sweep_sample.py`

**Interfaces:**

```python
sample_silver_post_sweep(
    silver_evidence_path: Path, *, verify_label: str, output_path: Path,
    sample_size: int = 60, seed: str, exclude_jsonl_path: Path | None = None
) -> dict[str, object]
```

The sampler accepts only `silver_label_candidate` evidence for the exact historical label, uses a deterministic SHA-256 ranking over `seed + review_id`, and excludes question IDs found in the initial 12/12 review packet when supplied. It writes fewer than 60 only when fewer independent full-run positives exist; the report makes this explicit.

- [x] **Step 1: Write the failing sampler test**

```python
def test_sampler_excludes_initial_calibration_questions_and_uses_stable_seeded_selection():
    report = sample_silver_post_sweep(..., sample_size=2, exclude_jsonl_path=initial_review)
    assert report["selected_records"] == 2
    assert {row["question_id"] for row in sample} == {"102", "103"}
```

- [x] **Step 2: Verify red**

Run: `.venv/bin/python -m pytest tests/test_silver_post_sweep_sample.py -q`

Expected: FAIL because the sampler module does not exist.

- [x] **Step 3: Implement deterministic independent sampler and CLI**

Require exact `verify_label`, `disposition=silver_label_candidate`, and `llm_match=true`; preserve source identity and review evidence but do not write review verdicts. Reject overwrite and report available, excluded, and selected counts.

- [x] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_silver_post_sweep_sample.py -q`

Expected: PASS.

### Task 6: Partition a full-label packet by the human-approved route scope

**Files:**
- Create: `english_knowledge_tagger/mentor_label_rollout_partition.py`
- Create: `scripts/partition_mentor_label_rollout_packet.py`
- Create: `configs/terminal_label_rollout_policies/mentor-direct-v1-noun-discrimination-20260827.json`
- Create: `tests/test_mentor_label_rollout_partition.py`
- Modify: `docs/data-cleaning-playbook.md`

**Interfaces:**

```python
partition_mentor_label_rollout_packet(
    packet_path: Path, *, policy_path: Path, eligible_output_path: Path,
    quarantine_output_path: Path
) -> dict[str, object]
```

The first manual policy allows only `parent × 单选题 × 选择题` for `知识点@词汇@词汇辨析@名词（短语）辨析`. Exact route mismatches must be written unchanged to quarantine with a policy reason; they are not passed to the full DS verifier.

- [x] **Step 1: Write the failing partition test**

```python
def test_partitioner_keeps_only_the_exact_human_approved_route():
    report = partition_mentor_label_rollout_packet(packet, policy_path=policy, ...)
    assert report["eligible_records"] == 1
    assert eligible[0]["rollout_route_decision"] == "eligible"
    assert quarantine[0]["rollout_route_decision"] == "quarantine"
```

- [x] **Step 2: Verify red**

Run: `.venv/bin/python -m pytest tests/test_mentor_label_rollout_partition.py -q`

Expected: FAIL because the partition module does not exist.

- [x] **Step 3: Implement exact route policy and streamable partitioner**

Reject packets containing a different verify label, malformed route key, duplicate policy routes, or pre-existing outputs. Report each route count and both destination paths; source packet remains unchanged.

- [x] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_mentor_label_rollout_partition.py -q`

Expected: PASS.

## Self-Review

- Yield threshold, error gate, minimum true count, and no accuracy claim are all covered by Task 1.
- Exact mentor-v1 prompt reproduction and source identity preservation are covered by Task 2.
- Full-run model evidence, error handling, taxonomy canonicalization and existing gate integration are covered by Task 3.
- The first label's human-approved policy and 60-sample operational gate are covered by Task 4.
- No task parses the unfinished Markdown ledgers, mutates source labels, or sends false results directly to replacement.

### Task 7: Prepare the approved lexical POS batch while DS is paused

**Files:**
- Create: three `configs/terminal_label_rollout_policies/mentor-direct-v1-*-discrimination-20260827.json` policy files.
- Modify: `configs/terminal_label_calibration_policies/mentor-direct-v1-preliminary-20260827.json`
- Modify: `tests/test_terminal_label_rollout_policy_configs.py`
- Modify: `tests/test_terminal_label_calibration_policy_configs.py`
- Modify: `docs/data-cleaning-playbook.md`, `docs/document-status.md`, `README.md`

The four labels are noun/adverb/verb/adjective `(短语)辨析`. Each was a separate 500-record yield candidate and has a complete positive `12/12 retain` review. All use the same manually approved route, `parent × 单选题 × 选择题`, but retain separate route policies, packets, DS runs and independent 60-positive release samples.

- [x] **Step 1: Extend config tests to require the four distinct route and calibration policies.**
- [x] **Step 2: Verify red.** Both new route policies and preliminary calibration entries are absent, causing expected test failures.
- [x] **Step 3: Freeze the three new route files and their reviewed audit counts.** All negative outcomes remain `hold`.
- [x] **Step 4: Verify green.** Run `.venv/bin/python -m pytest tests/test_terminal_label_rollout_policy_configs.py tests/test_terminal_label_calibration_policy_configs.py -q`.
- [x] **Step 5: Document sequential offline packet preparation and the per-label DS/release boundary.**
