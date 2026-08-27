# Final Label Discriminator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an auditable final label discriminator whose model prompt contains only a candidate label definition and cleaned question content, then document every prepared label batch and its release state.

**Architecture:** A streaming sanitizer converts a route-eligible mentor packet into a new packet that has no historical `output_all`, instruction, or type metadata. A separate DS client renders the final prompt, returns gate-compatible evidence and never mutates source data. A Markdown progress ledger records prepared batch counts and the only path from label evidence to trainable question candidates.

**Tech Stack:** Python standard library, JSON/JSONL, `urllib`, existing label definition loader, existing terminal-label gate, `unittest`.

## Global Constraints

- Final prompt version is `final-label-discriminator-v1`; it is distinct from `mentor-direct-v1` and requires fresh label × route calibration before any new label policy is released.
- The model receives only the candidate label, its teacher definition and cleaned question content; it never receives `output_all`, any other labels, instruction, route/scope or type metadata.
- `题型结构为：...`, `题型名称为：...` and the trailing SFT classification instruction must be removed before packet output and prompt rendering; route policy runs outside the model.
- Output is a new JSONL packet/evidence file and refuses overwrite; final source and old mentor packet are read-only.
- `confidence` is audit metadata only. Gate disposition remains controlled by the human-authored calibration policy.
- A positive label verdict is not a train row until `assemble_silver_questions.py` verifies all active historical labels on that question.

---

### Task 1: Build a sanitized final-discriminator packet

**Files:**
- Create: `english_knowledge_tagger/final_label_discriminator.py`
- Create: `scripts/build_final_label_discriminator_packet.py`
- Create: `tests/test_final_label_discriminator.py`

**Interfaces:**

```python
def build_final_label_discriminator_packet(
    eligible_packet_path: Path, *, label_definitions_path: Path, output_path: Path
) -> dict[str, object]: ...
```

The function accepts only rows with `rollout_route_decision == "eligible"`, writes source identity, candidate label, label-definition lineage and cleaned `question_text`, and rejects output rows containing `output_all`, `instruction`, or type metadata.

- [x] **Step 1: Write a failing test.**

```python
def test_final_packet_removes_type_metadata_and_historical_labels():
    report = build_final_label_discriminator_packet(eligible, label_definitions_path=definitions, output_path=output)
    row = json.loads(output.read_text())
    assert row["question_text"] == "题目题干：Choose the right word."
    assert "output_all" not in row
    assert "instruction" not in row
    assert "题型结构为" not in row["question_text"]
    assert report["selected_records"] == 1
```

- [x] **Step 2: Verify red.**

Run: `.venv/bin/python -m pytest tests/test_final_label_discriminator.py -q`

Expected: fail because the module and function do not exist.

- [x] **Step 3: Implement the sanitizer and CLI.**

```python
packet_row = {
    "schema_version": "final-label-discriminator-packet-v1",
    "review_id": f"final-label-discriminator-v1:{source_line}:{verify_label}",
    "question_id": source["question_id"],
    "parent_id": source["parent_id"],
    "source_line": source["source_line"],
    "is_sub_question": source["is_sub_question"],
    "route_key": source["route_key"],
    "verify_label": source["verify_label"],
    "question_text": clean_final_label_question(source["input"]),
}
```

`clean_final_label_question` removes every line beginning with `题型结构为：`, `题型名称为：`, `所给图片为题目题干` or `根据以上信息，当前题目所属的题型方法类目和知识点类目为：`; it preserves all remaining question, option, answer and analysis text and truncates at 2,000 characters.

- [x] **Step 4: Verify green.**

Run: `.venv/bin/python -m pytest tests/test_final_label_discriminator.py -q`

Expected: PASS.

### Task 2: Render and run the final discriminator

**Files:**
- Modify: `english_knowledge_tagger/final_label_discriminator.py`
- Create: `scripts/validate_final_label_discriminator.py`
- Modify: `tests/test_final_label_discriminator.py`

**Interfaces:**

```python
def build_final_label_discriminator_prompt(packet_row, *, label_definitions) -> str: ...
class FinalLabelDiscriminatorClient:
    def verify(self, request: FinalLabelDiscriminatorRequest) -> FinalLabelDiscriminatorResult: ...
```

The prompt includes only `verify_label`, the label's `definition`, and `question_text`; it requires JSON `{match, confidence, reason}`. The client calls DS with `temperature=0`, `max_tokens=512`, and `enable_thinking=false`. Evidence uses the existing `terminal-label-discriminator-evidence-v1` schema so it can enter the existing gate.

- [x] **Step 1: Write failing prompt/client/evidence tests.**

```python
def test_final_prompt_has_only_label_definition_and_question_text():
    prompt = build_final_label_discriminator_prompt(packet, label_definitions=definitions)
    assert "历史标签" not in prompt
    assert "题型结构为" not in prompt
    assert "当前题目打的全部标签" not in prompt
    assert "标签释义" in prompt

def test_final_client_result_is_gate_compatible():
    result = client.verify(FinalLabelDiscriminatorRequest(packet_row=packet))
    evidence = final_result_to_evidence(packet, result=result, rulebook=rulebook, migration=migration)
    assert evidence["llm_match"] is True
    assert evidence["confidence"] == "high"
    assert "output_all" not in evidence
```

- [x] **Step 2: Verify red.**

Run: `.venv/bin/python -m pytest tests/test_final_label_discriminator.py -q`

Expected: fail because prompt/client/evidence interfaces are absent.

- [x] **Step 3: Implement bounded verifier CLI.**

The CLI has `--input`, `--label-definitions`, `--teacher-csv`, `--taxonomy-migration`, `--output`, `--report`, `--limit`, `--allow-full`, `--concurrency`, endpoint/model/timeout arguments. It uses at most 128 workers, preserves packet order, writes explicit error evidence and refuses a full run without `--allow-full`.

- [x] **Step 4: Verify green.**

Run: `.venv/bin/python -m pytest tests/test_final_label_discriminator.py tests/test_terminal_label_discriminator_gate.py -q`

Expected: PASS.

### Task 3: Record prepared data and final-release progress

**Files:**
- Create: `docs/final-discriminator-ready-data.md`
- Modify: `README.md`
- Modify: `docs/document-status.md`

The document records source/definition hashes, each label's full/eligible/quarantine count, final-packet state, DS state, policy stage, 60-review state and training-assembly state. It explicitly distinguishes `prepared_for_final_discriminator`, `silver_label_candidate`, `silver_question_candidate` and `released_silver`.

- [x] **Step 1: Write the document with the four prepared lexical POS labels.**

The initial counts are noun `39,756 / 32,747 / 7,009`, adverb `21,551 / 17,495 / 4,056`, verb `62,986 / 55,236 / 7,750`, and adjective `35,752 / 29,769 / 5,983`.

- [x] **Step 2: Document runnable no-DS packet commands and post-deployment smoke/full/gate/assembly commands.**

The final command sequence must process each label separately and must not claim a final-model true result is directly trainable without question assembly and 60-sample approval.

- [x] **Step 3: Run the full suite, check formatting, commit and push.**

Run: `.venv/bin/python -m pytest -q && git diff --check`.
