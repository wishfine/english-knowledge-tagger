# Input Completeness Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在知识点最终判别中同时记录规则侧输入完整性和 DS 侧证据充分性，使确实无法判断的题目进入 hold，而不把它们混入确定负例。

**Architecture:** 新增一个纯 Python 输入完整性分类器，基于清洗后的题面识别直接题干、父题上下文、解析/答案、音频/图片标记和兄弟题解析歧义。最终判别器在 opt-in 的新 prompt 版本中要求 DS 返回 `input_status`；所有 evidence 记录规则侧 `input_precheck`，最终质量快照只允许完整或明确解析辅助的正向证据进入候选，其余记录进入带原因的 hold。

**Tech Stack:** Python 3 标准库、现有 JSONL/SQLite pipeline、`unittest`。

## Global Constraints

- 原始 v2/v3 JSONL、历史 `output` 和标签只读，任何新状态都写入新 evidence/snapshot。
- 保留旧 `final-label-discriminator-v1` 的解析兼容性；新字段必须通过新 prompt 版本或缺省值兼容旧 evidence。
- `input_status` 是证据完整性状态，不是知识点标签真值；`insufficient/ambiguous` 不得被统计为确定 `match=false`。
- 输入完整性在 `question_id × verify_label` evidence 粒度保存；父题上下文不得被当作子题知识点标签。
- 不把仅有音频时长、图片占位、`解析：略` 或 `同(1)题详解` 视为充分证据。
- 所有输出路径拒绝覆盖，测试必须覆盖新旧 prompt、SSE、快照 hold 行为。

---

### Task 1: Add deterministic input completeness classifier

**Files:**
- Create: `english_knowledge_tagger/input_completeness.py`
- Test: `tests/test_input_completeness.py`

**Interfaces:**
- `classify_input_completeness(packet_row: Mapping[str, object]) -> dict[str, object]`
- Return keys: `status`, `has_stem`, `has_options`, `has_answer`, `has_analysis`, `has_parent_material`, `modality`, `reason`.

- [x] **Step 1: Write failing tests**

覆盖以下行为：

```python
def test_direct_stem_is_complete(): ...
def test_explicit_analysis_without_child_stem_is_analysis_supported(): ...
def test_generic_analysis_is_insufficient(): ...
def test_sibling_analysis_reference_is_ambiguous(): ...
def test_audio_duration_without_content_is_insufficient(): ...
```

- [x] **Step 2: Run focused tests and verify failure**

Run: `python3 -m unittest tests.test_input_completeness -v`

Expected: import failure because the classifier module does not exist.

- [x] **Step 3: Implement minimal classifier**

Reuse the existing section parsing semantics from `enhanced_source_audit.py`. Use these statuses:

```text
complete
analysis_supported
parent_context_only
audio_or_image_missing
sibling_mapping_ambiguous
insufficient
```

`analysis_supported` requires a non-generic analysis plus answer or options; `同(1)题详解` and `解析：略` are insufficient/ambiguous. Audio/image markers without actual content stay non-complete.

- [x] **Step 4: Run focused tests**

Run: `python3 -m unittest tests.test_input_completeness -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add english_knowledge_tagger/input_completeness.py tests/test_input_completeness.py
git commit -m "feat: classify final label input completeness"
```

### Task 2: Add opt-in DS `input_status` output and evidence fields

**Files:**
- Modify: `english_knowledge_tagger/final_label_discriminator.py`
- Modify: `scripts/validate_final_label_discriminator.py`
- Modify: `tests/test_final_label_discriminator.py`
- Modify: `tests/test_validate_final_label_discriminator_cli.py`

**Interfaces:**
- Add `FINAL_PROMPT_VERSION_WITH_INPUT_STATUS = "final-label-discriminator-v2-input-status"`.
- Extend `FinalLabelDiscriminatorResult` with `input_status: str | None`.
- Add CLI flag `--include-input-status`.
- Evidence fields: `input_precheck`, `llm_input_status`.

- [x] **Step 1: Write failing tests**

Add tests asserting that opt-in prompts require JSON `input_status`, parser rejects unknown statuses, and evidence contains both local precheck and DS status. Keep existing v1 tests unchanged.

- [x] **Step 2: Run tests and verify failure**

Run: `python3 -m unittest tests.test_final_label_discriminator tests.test_validate_final_label_discriminator_cli -v`

Expected: FAIL because the new flag/status fields do not exist.

- [x] **Step 3: Implement parser, prompt and CLI flag**

The opt-in prompt must request:

```json
{"match": true, "input_status": "complete", "confidence": "high", "reason": "..."}
```

Allowed DS statuses are `complete`, `analysis_supported`, `insufficient`, and `ambiguous`. For old v1 responses, preserve `llm_input_status=null`. Always compute `input_precheck` locally from the packet row and attach it to evidence.

- [x] **Step 4: Run focused tests**

Run: `python3 -m unittest tests.test_final_label_discriminator tests.test_validate_final_label_discriminator_cli -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add english_knowledge_tagger/final_label_discriminator.py scripts/validate_final_label_discriminator.py tests/test_final_label_discriminator.py tests/test_validate_final_label_discriminator_cli.py
git commit -m "feat: record DS input sufficiency status"
```

### Task 3: Filter incomplete evidence in final quality snapshot

**Files:**
- Modify: `english_knowledge_tagger/final_quality_snapshot.py`
- Modify: `tests/test_final_quality_snapshot.py`

**Interfaces:**
- Read optional `input_precheck.status` and `llm_input_status`.
- Add hold reasons `input_insufficient` and `input_ambiguous`.
- Add summary counters for each input status.

- [x] **Step 1: Write failing tests**

Add one complete positive evidence row, one `llm_match=true` with `input_precheck.status=insufficient`, and one `llm_match=true` with `input_precheck.status=analysis_supported`. Assert only complete and explicitly allowed analysis-supported rows become candidates; insufficient/ambiguous rows become holds and are not counted as negative evidence.

- [x] **Step 2: Run focused tests and verify failure**

Run: `python3 -m unittest tests.test_final_quality_snapshot -v`

Expected: FAIL because snapshot currently accepts every positive evidence row.

- [x] **Step 3: Implement conservative snapshot gate**

Treat `complete` as eligible. Treat `analysis_supported` as a separately counted candidate class, not interchangeable with complete. Treat `insufficient`, `audio_or_image_missing`, `parent_context_only`, and `sibling_mapping_ambiguous` as holds unless a future policy explicitly allows them.

- [x] **Step 4: Run focused tests**

Run: `python3 -m unittest tests.test_final_quality_snapshot -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add english_knowledge_tagger/final_quality_snapshot.py tests/test_final_quality_snapshot.py
git commit -m "feat: hold final candidates with insufficient input"
```

### Task 4: Document and run the v3 pilot

**Files:**
- Modify: `docs/current-data-loop.md`
- Modify: `docs/final-discriminator-ready-data.md`
- Add runtime-only outputs: `$RUNTIME/final-v2-input-status/<run-id>/`

- [x] **Step 1: Document field semantics and command**

Document that v1 evidence remains historical, while the new opt-in prompt version records `input_status`; explain the difference between direct completeness and analysis-supported evidence.

- [ ] **Step 2: Build a bounded v3 pilot packet**

Use the seven labels from the v3 completeness audit, sample at most 24 records per label, and record source SHA, packet SHA, model, endpoints, concurrency and prompt version.

- [ ] **Step 3: Run DS with `--include-input-status`**

Run at low concurrency first, inspect `input_precheck` × `llm_input_status` disagreements, and do not materialize training data yet.

- [ ] **Step 4: Produce a status matrix**

Report, per label: complete, analysis-supported, insufficient, ambiguous, DS match rate within each status, and the count excluded by final snapshot.

- [ ] **Step 5: Run regression tests**

Run: `python3 -m unittest discover -s tests -p 'test_*.py' -v`

Expected: all runnable tests pass; any environment-only dependency issue is reported separately.
