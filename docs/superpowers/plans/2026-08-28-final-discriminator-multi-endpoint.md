# Final Discriminator Multi-Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow final-v1 calibration and rollout jobs to distribute one global concurrency budget across the two recovered DS-V4 vLLM endpoints (`9102`, `9103`) without changing prompt or evidence semantics.

**Architecture:** The final verifier CLI accepts repeatable `--endpoint` values. It constructs one client per endpoint and assigns submitted packet rows round-robin; the existing bounded thread pool still enforces a single global concurrency limit. Each evidence row records the endpoint that handled it for throughput/error diagnostics, while the final prompt and retry contract remain unchanged.

**Tech Stack:** Python standard library, existing OpenAI-compatible client, `ThreadPoolExecutor`, `unittest`.

## Global Constraints

- Global `--concurrency` is the aggregate limit across all endpoints; day default for this deployment is 30 and night use may raise it to 50 only with approval.
- The model must receive the same final-v1 prompt regardless of endpoint.
- No fallback to a different prompt/version or automatic label release is permitted after endpoint errors.
- Endpoint is evidence provenance only; calibration policy remains label × prompt-version specific.
- Existing single `--endpoint` invocation must remain compatible.

---

### Task 1: Write failing dual-endpoint CLI test

**Files:**
- Modify: `tests/test_validate_final_label_discriminator_cli.py`

- [x] **Step 1: Start two local HTTP servers and invoke the CLI with both repeatable endpoints and two packet rows.**
- [x] **Step 2: Assert both servers receive a request, global report lists both endpoints, and each evidence row records its handling endpoint.**
- [x] **Step 3: Run the focused test and verify it fails before multi-endpoint support exists.**

### Task 2: Implement endpoint pool support

**Files:**
- Modify: `scripts/validate_final_label_discriminator.py`

- [x] **Step 1: Change `--endpoint` to a repeatable argument with the old default only when no explicit endpoint is supplied.**
- [x] **Step 2: Construct endpoint-specific clients and send rows round-robin while preserving the global bounded pending queue.**
- [x] **Step 3: Add `endpoint` to candidate and error evidence and list endpoints in the report.**
- [x] **Step 4: Run the focused test and verify it passes.**

### Task 3: Document deployment-safe invocation

**Files:**
- Modify: `docs/final-discriminator-ready-data.md`
- Modify: `docs/positive-candidate-batch-workflow.md`

- [x] **Step 1: Document the two endpoints, exact model string, global concurrency semantics and smoke-first command.**
- [x] **Step 2: State that 30 is total rather than 30 per vLLM worker.**

### Task 4: Verify and commit

**Files:**
- Test: `tests/test_validate_final_label_discriminator_cli.py`
- Test: `tests/test_final_label_discriminator.py`

- [x] **Step 1: Run focused and full suites, plus `git diff --check`.**
- [x] **Step 2: Commit only the multi-endpoint runner, tests, documentation and plan.**
