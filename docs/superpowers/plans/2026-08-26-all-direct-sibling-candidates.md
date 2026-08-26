# All Direct Sibling Candidates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a knowledge-validation route explicitly include every active direct terminal sibling of the historical label, while retaining type-constrained retrieval as a cross-branch escape channel and producing an auditable old/new candidate-pool comparison.

**Architecture:** Keep `child-knowledge-presence-v0.1.json` immutable as the historical `limited_direct_leaves` baseline. Add a `sibling_selection` field to the exact-route policy; the v0.2 grammar routes select `all_direct_leaves`. The validation-packet builder records both the selection strategy and direct sibling count, and a comparison CLI joins two frozen packet runs by `review_id` to emit only newly exposed sibling candidates for human coverage review.

**Tech Stack:** Python standard library, existing JSONL packet schema, teacher CSV rulebook, `unittest`.

## Global Constraints

- Source JSONL and v0.1 policy remain read-only; this implementation creates new packets and reports only.
- `all_direct_leaves` means all active terminal labels with exactly the same immediate taxonomy parent as the target label, after exact-route prefix filtering.
- The 12-item retrieval shortlist remains separate; it can surface a correct label outside the historical label's branch.
- Do not send a broad sibling group automatically to DS merely because it is present; the comparison packet is reviewed before v0.2 is used for a model batch.
- Preserve explicit `forbidden` and `unresolved` no-model behavior.
- No candidate output mutates history or creates an HQ patch.

---

### Task 1: Express direct-sibling selection in the policy and rulebook

**Files:**

- Modify: `english_knowledge_tagger/knowledge_candidate_policy.py`
- Modify: `english_knowledge_tagger/knowledge_rulebook.py`
- Test: `tests/test_knowledge_candidate_policy_configs.py`
- Test: `tests/test_knowledge_validation_packet.py`

**Interfaces:**

```python
KnowledgeCandidateRule.sibling_selection: str
# "limited_direct_leaves" | "all_direct_leaves" | "none"

KnowledgeRulebook.direct_active_leaf_siblings(path: str) -> tuple[KnowledgeRulebookRecord, ...]
```

- [x] **Step 1: Write failing policy and sibling tests**

```python
rule = load_knowledge_candidate_policy(v02_policy).match("child", "复合题", "语法选择")
self.assertEqual(rule.sibling_selection, "all_direct_leaves")
self.assertIsNone(rule.max_sibling_candidates)

siblings = rulebook.direct_active_leaf_siblings(target_path)
self.assertEqual({item.path for item in siblings}, expected_all_siblings)
```

- [x] **Step 2: Verify red**

Run: `.venv/bin/python -m pytest tests/test_knowledge_candidate_policy_configs.py tests/test_knowledge_validation_packet.py -q`

Expected: FAIL because `sibling_selection` and `direct_active_leaf_siblings` do not exist.

- [x] **Step 3: Implement the minimum schema and helper**

```python
SIBLING_SELECTIONS = frozenset({"limited_direct_leaves", "all_direct_leaves", "none"})

def direct_active_leaf_siblings(self, path: str) -> tuple[KnowledgeRulebookRecord, ...]:
    parent, _, _ = path.rpartition("->")
    return tuple(
        record for candidate_path, record in sorted(self.records.items())
        if candidate_path != path
        and record.status == "active"
        and candidate_path.startswith(f"{parent}->")
        and candidate_path.count("->") == path.count("->")
    )
```

For `all_direct_leaves`, parse `max_sibling_candidates` as absent and expose `None`. For legacy v0.1 `limited_direct_leaves`, retain its existing 1–8 validation. For `forbidden` and `unresolved`, selection is `none` and pool sizes remain zero.

- [x] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_knowledge_candidate_policy_configs.py tests/test_knowledge_validation_packet.py -q`

Expected: PASS.

### Task 2: Build v0.2 packets with all direct siblings and provenance

**Files:**

- Create: `configs/knowledge_candidate_policies/child-knowledge-presence-v0.2.json`
- Modify: `english_knowledge_tagger/knowledge_validation_packet.py`
- Modify: `tests/test_knowledge_validation_packet.py`

**Interfaces:**

```json
"candidate_pool": {
  "sibling_selection": "all_direct_leaves",
  "max_sibling_candidates": null,
  "direct_sibling_count": 10
}
```

- [x] **Step 1: Write a failing wide-sibling packet test**

Create a teacher CSV fixture with one target and nine active direct terminal siblings. Build a v0.2 packet and assert all nine sibling labels occur with `source: "sibling"`, while an off-parent type-retrieval candidate remains separately marked `source: "type_retrieval"`.

- [x] **Step 2: Verify red**

Run: `.venv/bin/python -m pytest tests/test_knowledge_validation_packet.py -q`

Expected: FAIL because the current 8-item limit truncates the ninth sibling and does not expose the new provenance fields.

- [x] **Step 3: Implement packet selection**

```python
if candidate_rule.sibling_selection == "all_direct_leaves":
    all_siblings = rulebook.direct_active_leaf_siblings(canonical_label)
else:
    all_siblings = rulebook.nearby_active_records(
        canonical_label, limit=candidate_rule.max_sibling_candidates
    )
```

Filter siblings by the route's allowed prefixes exactly as before. Preserve deterministic path ordering and deduplicate against the retrieval list. Add strategy, configured limit and actual direct sibling count to `candidate_pool`.

- [x] **Step 4: Add v0.2 policy**

Copy only the currently confirmed exact routes from v0.1. Set the two grammar-selection routes to `sibling_selection: "all_direct_leaves"`; keep `max_retrieved_candidates: 12` and `max_output_labels: 3`. Keep forbidden routes unchanged.

- [x] **Step 5: Verify green**

Run: `.venv/bin/python -m pytest tests/test_knowledge_validation_packet.py tests/test_knowledge_candidate_policy_configs.py -q`

Expected: PASS.

### Task 3: Compare frozen v0.1/v0.2 packets before model calls

**Files:**

- Create: `english_knowledge_tagger/knowledge_candidate_pool_comparison.py`
- Create: `scripts/compare_knowledge_candidate_pools.py`
- Create: `tests/test_knowledge_candidate_pool_comparison.py`

**Interfaces:**

```python
def compare_knowledge_candidate_pools(
    baseline_packet: Path, candidate_packet: Path, *, output_path: Path
) -> dict[str, object]: ...
```

The JSONL output contains only rows whose direct sibling set grew, with `review_id`, source identifiers, route key, target label, baseline/new sibling labels, newly exposed labels and counts. It does not duplicate question text, raw definitions or DS responses.

- [x] **Step 1: Write a failing comparison test**

```python
report = compare_knowledge_candidate_pools(old, new, output_path=output)
self.assertEqual(report["expanded_rows"], 1)
self.assertEqual(row["newly_exposed_sibling_labels"], ["知识点->词法->被动语态->一般过去时的被动语态"])
```

- [x] **Step 2: Verify red**

Run: `.venv/bin/python -m pytest tests/test_knowledge_candidate_pool_comparison.py -q`

Expected: FAIL because the comparison module and CLI do not exist.

- [x] **Step 3: Implement strict packet join and CLI**

Require unique non-empty `review_id` values in each packet. Fail if a candidate packet row has no baseline peer, if route/target differ between peers, or if output exists. Emit deterministic JSONL sorted by baseline packet order and a JSON report with `matched_rows`, `expanded_rows`, `unchanged_rows`, and expanded rows grouped by target parent path.

- [x] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_knowledge_candidate_pool_comparison.py -q`

Expected: PASS.

### Task 4: Document the v0.1 → v0.2 coverage experiment and complete verification

**Files:**

- Modify: `docs/knowledge-label-validation.md`
- Modify: `docs/current-data-loop.md`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-26-all-direct-sibling-candidates.md`

- [x] **Step 1: Document exact server sequence**

```bash
python3 scripts/build_knowledge_validation_packet.py ... --candidate-policy "$KP_POLICY_V01" ...
python3 scripts/build_knowledge_validation_packet.py ... --candidate-policy "$KP_POLICY_V02" ...
python3 scripts/compare_knowledge_candidate_pools.py \
  --baseline "$V01_PACKET" --candidate "$V02_PACKET" \
  --output "$CALIBRATION_PACKET" --report "$CALIBRATION_REPORT"
```

Document that DS is called only after reviewing the expanded rows; use v0.2 first for the four affected word/syntax groups, not globally.

- [x] **Step 2: Run full verification**

Run: `.venv/bin/python -m pytest -q && git diff --check`

Expected: PASS.

- [x] **Step 3: Commit and push**

```bash
git add configs/knowledge_candidate_policies/child-knowledge-presence-v0.2.json \
  english_knowledge_tagger/knowledge_candidate_policy.py \
  english_knowledge_tagger/knowledge_rulebook.py \
  english_knowledge_tagger/knowledge_validation_packet.py \
  english_knowledge_tagger/knowledge_candidate_pool_comparison.py \
  scripts/compare_knowledge_candidate_pools.py tests/test_knowledge_candidate_policy_configs.py \
  tests/test_knowledge_validation_packet.py tests/test_knowledge_candidate_pool_comparison.py \
  docs/knowledge-label-validation.md docs/current-data-loop.md README.md \
  docs/superpowers/plans/2026-08-26-all-direct-sibling-candidates.md
git commit -m "feat: audit all direct knowledge siblings"
git push origin HEAD:main
```
