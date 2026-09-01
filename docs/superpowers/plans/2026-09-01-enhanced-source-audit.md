# Enhanced Source Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对 `cleaned_final_enhanced_v2.jsonl` 做一次全量、可复现的题型与内容形态画像，并生成便于人工查看的分层样本，不修改源数据或调用 DS。

**Architecture:** 单次流式扫描 source，解析 parent/child scope、声明题型、内容完整度、音频/图片状态和历史标签基数；使用 SQLite 记录复合身份重复与 child→parent 孤儿关系；以确定性 hash reservoir 为每个题型桶和内容形态桶抽样。

**Tech Stack:** Python 3 标准库、SQLite、JSONL、`unittest`。

## Global Constraints

- `cleaned_final_enhanced_v2.jsonl` 只读，不覆盖任何输入。
- 题型元信息仅用于画像，不作为知识点真值。
- 画像样本保留 input/output 供人工检查，但不调用 DS、不产生标签 patch。
- 分层样本必须按稳定 seed 可复现；索引、报告、样本分别输出并拒绝覆盖。

### Task 1: Implement streaming profile and sampler

**Files:**
- Create: `english_knowledge_tagger/enhanced_source_audit.py`
- Create: `scripts/profile_enhanced_source.py`
- Test: `tests/test_enhanced_source_audit.py`
- Test: `tests/test_profile_enhanced_source_cli.py`

- [x] Write failing tests for scope, type, content shape, modality, duplicate identity, and CLI artifacts.
- [x] Implement one-pass JSONL scan, SQLite identity/orphan checks, deterministic type/shape samples, and report generation.
- [x] Add progress logging for long runs.
- [x] Run focused tests and compile checks.

### Task 2: Document interpretation and downstream boundary

**Files:**
- Modify: `README.md`
- Modify: `docs/current-data-loop.md`

- [x] Document that parent-shell records and child context gaps follow different repair branches.
- [x] Document that profile output is audit-only and all downstream DS packets must be rebuilt from any later derived source.

### Task 3: Run on host 35 and review before repair

**Files:**
- Runtime-only: `$RUNTIME/source-audit/enhanced-v2-profile-<run-id>/`

- [ ] Freeze source SHA, line count, disk space, and code commit.
- [ ] Run `profile_enhanced_source.py` with `--progress-every 100000` and `--sample-per-bucket 3`.
- [ ] Inspect all type buckets and representative parent-shell/child-missing-stem/multimodal samples.
- [ ] Decide which shapes enter `v3_parent_context`, which require parent-aggregate review, and which stay hold.
