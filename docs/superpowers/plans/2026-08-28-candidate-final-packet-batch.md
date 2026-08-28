# Candidate Final Packet Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Materialize sanitized final-discriminator packets for the frozen 69-label candidate queue in one source scan, applying only the four explicit hard route exclusions.

**Architecture:** The batch builder reads the candidate manifest, validated route guidance and mentor definition JSON once, then streams source JSONL. For each matching historical label it writes one final-v1-compatible row to that label’s packet if the label’s route rule allows it and text is usable. A batch index records all packet paths and hold reasons; the final discriminator sees no type headers, route rule or historical output.

**Tech Stack:** Python standard library, JSON/JSONL, SHA-256, existing final prompt cleaner, route guidance loader, `unittest`.

## Global Constraints

- Source JSONL is read exactly once and is never modified.
- `hard_exclusive` filters only the four frozen POS labels; `soft_typical` includes every route with usable text.
- Packets must use `final-label-discriminator-packet-v1` and preserve only permitted audit fields.
- Packet rows must exclude original `input`, `instruction`, `output`, `output_all`, type headers and SFT category suffixes.
- Text completeness is a separate hold reason from route exclusion.
- Outputs refuse overwrite and record source, manifest, guidance and definition hashes.

---

### Task 1: Write a failing one-pass packet test

**Files:**
- Create: `tests/test_candidate_final_packet_batch.py`

**Interfaces:**

```python
def build_candidate_final_packet_batch(
    source_path: Path, *, manifest_path: Path, guidance_path: Path,
    rulebook: KnowledgeRulebook, label_definitions_path: Path,
    output_dir: Path
) -> dict[str, object]: ...
```

- [x] **Step 1: Add a fixture with one hard and one soft candidate label across two routes.**
- [x] **Step 2: Assert that the hard label excludes its nonmatching route, the soft label retains both routes, and packet text contains neither type metadata nor source label fields.**
- [x] **Step 3: Run the focused test and verify it fails because the batch builder does not exist.**

### Task 2: Implement one-scan batch materialization and CLI

**Files:**
- Create: `english_knowledge_tagger/candidate_final_packet_batch.py`
- Create: `scripts/build_candidate_final_packet_batch.py`

- [x] **Step 1: Validate manifest/guidance/definition compatibility before opening output files.**
- [x] **Step 2: Stream source once, partition matching labels by hard/soft guidance, clean question content and write final-v1 rows.**
- [x] **Step 3: Write `batch.index.json` with per-label source, selected and held counts plus packet paths.**
- [x] **Step 4: Add CLI flags for source, manifest, guidance, teacher CSV, definitions, output directory and report.**
- [x] **Step 5: Run focused test and verify it passes.**

### Task 3: Document server execution and update current workflow

**Files:**
- Modify: `docs/positive-candidate-batch-workflow.md`
- Modify: `docs/final-discriminator-ready-data.md`
- Modify: `docs/document-status.md`

- [x] **Step 1: Document that packet materialization is permitted while DS is stopped, but calibration and final rollout remain blocked.**
- [x] **Step 2: Provide one server command and expected 69 packet index; do not imply packet existence is silver release.**

### Task 4: Verify and commit

**Files:**
- Test: `tests/test_candidate_final_packet_batch.py`
- Test: `tests/test_candidate_route_guidance.py`
- Test: `tests/test_positive_candidate_inventory.py`

- [x] **Step 1: Run the focused and adjacent tests, then the full test suite and `git diff --check`.**
- [x] **Step 2: Commit only builder, CLI, tests, documentation and its implementation plan.**
