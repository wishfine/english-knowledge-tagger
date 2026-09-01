# Parent Context Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从嵌套的 `初中英语_labeled.jsonl` 中为 `cleaned_final_enhanced_v2.jsonl` 的子题补充必要父题文本上下文，生成可审计的新派生源，不修改任一原始文件或历史标签。

**Architecture:** 第一遍流式扫描 raw，建立磁盘 SQLite 的父题和嵌套子题身份索引；第二遍流式扫描 enhanced v2，按 `(question_id, parent_id)` 匹配并只前置唯一父题的 `stem` 文本。所有无法唯一匹配、身份冲突或缺少父题的记录进入审计状态，原始 `output`、题型、知识点和多模态增强字段保持不变。

**Tech Stack:** Python 3 标准库、SQLite、JSONL、`unittest`。

## Global Constraints

- raw `初中英语_labeled.jsonl` 与 `cleaned_final_enhanced_v2.jsonl` 只读。
- 不复制父题 `knowledge_points` 或 `question_types` 到子题。
- 不覆盖已有输出；输出目录和 SQLite 索引必须不存在或显式拒绝覆盖。
- 主键使用 `question_id + parent_id + is_sub_question`，父题上下文匹配必须唯一。
- v3 派生源只改变 child 的 `input`；`output`、ID、音频、图片字段逐行保持一致。
- raw 的父题文本只作为上下文 donor；raw 标签不参与任何判别。

---

### Task 1: Define nested-source indexing and enrichment contract

**Files:**
- Create: `english_knowledge_tagger/parent_context_repair.py`
- Test: `tests/test_parent_context_repair.py`

**Interfaces:**
- `build_raw_index(raw_path: Path, index_path: Path) -> dict[str, object]`
- `enrich_enhanced_source(enhanced_path: Path, index_path: Path, output_path: Path, audit_path: Path, report_path: Path, manifest_path: Path, source_sha256: str, raw_sha256: str) -> dict[str, object]`
- `render_parent_context(parent: Mapping[str, object]) -> str`

- [ ] **Step 1: Write failing tests**

覆盖以下行为：嵌套 `sub_questions` 能建立子题索引；唯一匹配时只追加父题 `stem`；找不到父题、重复冲突父题和非 child 行分别分流；`output` 和非 `input` 字段不变。

- [ ] **Step 2: Run tests and verify the intended failure**

Run: `python3 -m unittest tests.test_parent_context_repair -v`

Expected: import failure because the module does not exist yet.

- [ ] **Step 3: Implement the minimal pure helpers and SQLite contract**

建立只包含规范化字符串、父题上下文和源行号的 SQLite 表；重复相同上下文可合并，冲突上下文保留多版本供第二遍标记 `ambiguous_parent`。

- [ ] **Step 4: Run the focused tests**

Run: `python3 -m unittest tests.test_parent_context_repair -v`

Expected: PASS。

- [ ] **Step 5: Commit the isolated contract**

```bash
git add english_knowledge_tagger/parent_context_repair.py tests/test_parent_context_repair.py
git commit -m "feat: define nested parent context repair contract"
```

### Task 2: Add the streaming repair CLI

**Files:**
- Create: `scripts/repair_parent_context.py`
- Modify: `english_knowledge_tagger/parent_context_repair.py`
- Test: `tests/test_repair_parent_context_cli.py`

**Interfaces:**
- CLI arguments: `--raw`, `--enhanced`, `--index`, `--output`, `--audit`, `--report`, `--manifest`.
- CLI output: a JSON report with raw parent/nested-child counts, enhanced counts, match statuses, changed rows, and identity conflicts.

- [ ] **Step 1: Write failing CLI tests**

Use temporary JSONL fixtures with one parent containing one child and one standalone parent; assert output has the same number of rows, child input gains a `父题上下文` section, and labels remain byte-equivalent.

- [ ] **Step 2: Run CLI tests and verify failure**

Run: `python3 -m unittest tests.test_repair_parent_context_cli -v`

Expected: script/module import or CLI failure because the executable is not present.

- [ ] **Step 3: Implement streaming two-pass CLI**

Pass 1 indexes outer parents and every nested child. Pass 2 copies enhanced rows and only changes `input` for uniquely matched child rows whose parent `stem` is non-empty and not already represented in the input; the parent context is placed before the child text so the original final task instruction remains last. Write one audit row per enhanced record and refuse existing output files.

- [ ] **Step 4: Run focused and regression tests**

Run:

```bash
python3 -m unittest tests.test_parent_context_repair tests.test_repair_parent_context_cli -v
python3 -m unittest tests.test_source_profile tests.test_composite_audit -v
```

Expected: all selected tests PASS。

- [ ] **Step 5: Commit the CLI**

```bash
git add english_knowledge_tagger/parent_context_repair.py scripts/repair_parent_context.py tests/test_repair_parent_context_cli.py
git commit -m "feat: add streaming parent context repair CLI"
```

### Task 3: Add source invariants and documentation

**Files:**
- Modify: `english_knowledge_tagger/parent_context_repair.py`
- Modify: `scripts/repair_parent_context.py`
- Modify: `docs/current-data-loop.md`
- Modify: `docs/data-cleaning-playbook.md`
- Test: `tests/test_parent_context_repair.py`

- [ ] **Step 1: Add invariant tests**

Assert unchanged row count, identity tuple, `output`, `contain_audio`, `whole_image`, and `images`; assert only child `input` may differ and audit records include old/new hashes plus raw source line.

- [ ] **Step 2: Implement report and manifest**

Record source paths, SHA-256, row counts, index schema version, repair version, status counts, changed-row count, and conflict count. The report must distinguish `already_present`, `added`, `missing_child_match`, `missing_parent`, `ambiguous_parent`, `identity_conflict`, and `not_child`.

- [ ] **Step 3: Document the new derived source**

Document that raw nested records are context donors, that parent labels never flow to children, and that every downstream DS packet must be rebuilt from the v3 source.

- [ ] **Step 4: Run the full available unittest suite**

Run: `python3 -m unittest discover -s tests -p 'test_*.py' -v`

Expected: all runnable tests pass; any environment-only missing dependency is reported separately.

### Task 4: Run the 35-host audit and controlled materialization

**Files:**
- No source files modified by the run; outputs live under `$RUNTIME/source-audit/parent-context-v1-<run-id>/`.

- [ ] **Step 1: Freeze paths and hashes**

Verify raw and enhanced paths, line counts, free disk, and SHA-256 before creating the output directory.

- [ ] **Step 2: Run the repair CLI**

Write a new SQLite index, repaired JSONL, audit JSONL, report, and manifest. Never write over `cleaned_final_enhanced_v2.jsonl` or the raw file.

- [ ] **Step 3: Validate the report**

Check row-count and identity invariants, inspect status counts, and sample at least 20 `added` children, 20 `already_present` children, and every conflict status before selecting the v3 source for any DS run.

- [ ] **Step 4: Rebuild downstream packets**

Only after audit acceptance, rebuild label/gate/tree packets from v3 and record the new source SHA; do not reuse v2 packet results.
