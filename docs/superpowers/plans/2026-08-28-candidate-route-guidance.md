# Candidate Route Guidance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze an auditable interpretation of teacher CSV route language for the 69-label positive-candidate snapshot, so only explicit exclusions become hard packet filters and all other routes remain diagnostic strata.

**Architecture:** A small route-guidance loader validates a snapshot-bound JSON configuration against the candidate manifest and teacher rulebook. The configuration has a default `soft_typical` mode and only four explicit `hard_exclusive` overrides; it never modifies source labels or releases data. A CLI writes a report that makes the remaining labels and any unacknowledged exclusive wording visible before later packet materialization.

**Tech Stack:** Python standard library, JSON, existing candidate manifest and knowledge rulebook, `unittest`.

## Global Constraints

- “常见题型” is evidence for stratified diagnostics, never an automatic filter.
- Only teacher wording that explicitly limits the label to a route may produce a `hard_exclusive` rule.
- The four POS-discrimination labels are the only currently verified hard exclusions: `parent × 单选题 × 选择题`.
- Route metadata must remain outside the final discriminator prompt.
- All generated reports and configurations are non-releasing; no source label, silver state or training set may be modified.

---

### Task 1: Write failing route-guidance validation tests

**Files:**
- Create: `tests/test_candidate_route_guidance.py`

**Interfaces:**

```python
def load_candidate_route_guidance(
    path: Path, *, manifest_path: Path, rulebook: KnowledgeRulebook
) -> CandidateRouteGuidance: ...

def build_candidate_route_guidance_report(
    guidance: CandidateRouteGuidance
) -> dict[str, object]: ...
```

- [x] **Step 1: Write a test that accepts a default soft label and one exact hard override.**

```python
guidance = load_candidate_route_guidance(config, manifest_path=manifest, rulebook=rulebook)
assert guidance.mode_for(SOFT_LABEL).mode == "soft_typical"
assert guidance.mode_for(HARD_LABEL).allowed_routes == (
    "parent × 单选题 × 选择题",
)
```

- [x] **Step 2: Run the focused test and verify it fails because the module is absent.**

Run: `python3 -m pytest tests/test_candidate_route_guidance.py -q`

Expected: failure caused by a missing module.

### Task 2: Implement snapshot-bound route guidance and its CLI

**Files:**
- Create: `english_knowledge_tagger/candidate_route_guidance.py`
- Create: `scripts/validate_candidate_route_guidance.py`
- Create: `configs/candidate_batches/positive-candidates-20260827.route-guidance.json`

**Interfaces:**

```python
@dataclass(frozen=True)
class LabelRouteGuidance:
    legacy_label: str
    canonical_label: str
    mode: Literal["hard_exclusive", "soft_typical"]
    allowed_routes: tuple[str, ...]
    csv_evidence: str
```

- [x] **Step 1: Implement config loading with exact manifest membership and canonical-path checks.**
- [x] **Step 2: Reject an override that names a non-candidate label, a hard override without allowed routes, or a soft override with allowed routes.**
- [x] **Step 3: Implement a report containing hard labels, soft labels and teacher CSV excerpts.**
- [x] **Step 4: Freeze the four explicit POS rules and use `soft_typical` as the default for every other candidate.**
- [x] **Step 5: Run the focused tests and verify they pass.**

### Task 3: Document the route interpretation and register it

**Files:**
- Create: `docs/candidate-route-guidance.md`
- Modify: `docs/document-status.md`

- [x] **Step 1: Explain the difference between hard exclusions, soft typical route guidance and runtime input-completeness gates.**
- [x] **Step 2: Record the four hard labels and explain that all other 65 labels remain all-route candidates for final semantic validation.**
- [x] **Step 3: Provide the server command to validate the frozen configuration and write a report without calling DS.**

### Task 4: Verify and commit

**Files:**
- Test: `tests/test_candidate_route_guidance.py`
- Test: existing `tests/test_positive_candidate_manifest.py`
- Test: existing `tests/test_positive_candidate_inventory.py`

- [x] **Step 1: Run focused and adjacent test suites.**

Run: `python3 -m pytest tests/test_candidate_route_guidance.py tests/test_positive_candidate_manifest.py tests/test_positive_candidate_inventory.py -q`

Expected: all pass.

- [x] **Step 2: Validate the committed snapshot config against the committed manifest and teacher CSV.**
- [x] **Step 3: Commit only the route-guidance implementation, tests, configuration and documentation.**
