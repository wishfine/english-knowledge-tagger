# Knowledge Presence Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each exact `scope × 题型结构 × 题型名称` route state whether knowledge-point labels are forbidden, optional, required, or unresolved, so DS is never asked to add labels where the teacher matrix says none should exist.

**Architecture:** Extend the versioned candidate-pool policy. The packet builder writes the resolved policy onto every audit record. `forbidden` records retain historical labels as correction evidence but never form a DS request; unknown routes remain `unresolved` rather than silently becoming empty labels.

**Tech Stack:** Python 3 standard library, JSON configuration, `unittest`.

## Global Constraints

- Source JSONL is read-only; corrections are separate artifacts.
- Parent knowledge points are never inherited by children.
- Historical labels are evidence, not policy truth.
- Policies are exact routes only: no blanket reading rule.
- `forbidden` means expected final knowledge-point set is empty; it does not delete the record.

---

### Task 1: Parse and validate knowledge-presence policies

**Files:**

- Modify: `english_knowledge_tagger/knowledge_candidate_policy.py`
- Modify: `configs/knowledge_candidate_policies/child-grammar-selection-v0.1.json`
- Test: `tests/test_knowledge_validation_packet.py`

**Interfaces:** `KnowledgeCandidateRule.knowledge_policy` is one of `forbidden`, `optional`, `required`, `unresolved`. `optional` and `required` require a bounded non-empty pool; `forbidden` and `unresolved` have no candidates and zero limits.

- [x] **Step 1: Write the failing tests**

```python
def test_forbidden_rule_has_no_retrieval_pool(self):
    rule = load_knowledge_candidate_policy(write_candidate_policy(path, [{
        "scope": "child", "declared_type_structure": "复合题",
        "declared_type_name": "阅读理解", "knowledge_policy": "forbidden",
    }])).match("child", "复合题", "阅读理解")
    self.assertEqual(rule.knowledge_policy, "forbidden")
    self.assertEqual(rule.max_output_labels, 0)

def test_required_rule_rejects_empty_candidate_pool(self):
    with self.assertRaisesRegex(ValueError, "required"):
        load_knowledge_candidate_policy(write_candidate_policy(path, [{
            "scope": "child", "declared_type_structure": "复合题",
            "declared_type_name": "语法选择", "knowledge_policy": "required",
            "allowed_knowledge_prefixes": [], "max_retrieved_candidates": 0,
            "max_sibling_candidates": 0, "max_output_labels": 0,
        }]))
```

- [x] **Step 2: Verify red**

Run: `python3 -m unittest tests.test_knowledge_validation_packet -v`

Expected: FAIL because `knowledge_policy` has no parsed interface.

- [x] **Step 3: Implement the parser**

```python
KNOWLEDGE_POLICIES = frozenset({"forbidden", "optional", "required", "unresolved"})

@dataclass(frozen=True)
class KnowledgeCandidateRule:
    # existing fields
    knowledge_policy: str

# optional/required validate the existing positive bounded fields;
# forbidden/unresolved accept only absent/empty/zero pool fields.
```

Make the two existing grammar-selection rules explicit `required` rules.

- [x] **Step 4: Verify green**

Run: `python3 -m unittest tests.test_knowledge_validation_packet -v`

Expected: PASS.

### Task 2: Keep policy-excluded history as an audit record

**Files:**

- Modify: `english_knowledge_tagger/knowledge_validation_packet.py`
- Test: `tests/test_knowledge_validation_packet.py`

**Interfaces:** Every packet row gets `knowledge_policy` and `validation_action`. `forbidden` gets `skip_policy_forbidden`, empty alternatives, zero candidate pool, and is counted as `policy_forbidden_items`; `unresolved` gets `skip_policy_unresolved`. `optional` and `required` retain the current type-constrained retrieval behavior.

- [x] **Step 1: Write the failing tests**

```python
def test_forbidden_route_preserves_historical_label_as_a_policy_conflict(self):
    report = build_knowledge_validation_packet(...)
    row = json.loads(packet.read_text(encoding="utf-8"))
    self.assertEqual(row["knowledge_policy"], "forbidden")
    self.assertEqual(row["validation_action"], "skip_policy_forbidden")
    self.assertEqual(row["alternative_labels"], [])
    self.assertEqual(row["candidate_pool"]["max_output_labels"], 0)
    self.assertEqual(report["policy_forbidden_items"], 1)
```

- [x] **Step 2: Verify red**

Run: `python3 -m unittest tests.test_knowledge_validation_packet -v`

Expected: FAIL because packet rows do not contain a policy action.

- [x] **Step 3: Implement packet routing**

```python
if candidate_rule is None:
    policy, action = "unresolved", "skip_policy_unresolved"
elif candidate_rule.knowledge_policy == "forbidden":
    policy, action = "forbidden", "skip_policy_forbidden"
elif candidate_rule.knowledge_policy == "unresolved":
    policy, action = "unresolved", "skip_policy_unresolved"
else:
    policy, action = candidate_rule.knowledge_policy, "validate_with_model"
```

Only the final branch retrieves candidates and target definitions.

- [x] **Step 4: Verify green**

Run: `python3 -m unittest tests.test_knowledge_validation_packet -v`

Expected: PASS.

### Task 3: Deterministically skip excluded packet rows before DS-V4

**Files:**

- Modify: `scripts/validate_knowledge_labels.py`
- Test: `tests/test_validate_knowledge_labels_cli.py`

**Interfaces:** `skip_policy_forbidden` produces `status="skipped"`, `skip_reason="policy_forbidden"`, and `recommended_final_knowledge_labels=[]`; `skip_policy_unresolved` produces `skip_reason="policy_unresolved"` and no recommendation. Neither creates an HTTP call.

- [x] **Step 1: Write the failing test**

```python
def test_cli_skips_forbidden_packet_without_sending_ds_request(self):
    item = validation_item()
    item.update({"knowledge_policy": "forbidden", "validation_action": "skip_policy_forbidden"})
    # Run against the recording local HTTP server.
    self.assertEqual(row["status"], "skipped")
    self.assertEqual(row["skip_reason"], "policy_forbidden")
    self.assertEqual(row["recommended_final_knowledge_labels"], [])
    self.assertEqual(_Handler.requests, [])
```

- [x] **Step 2: Verify red**

Run: `python3 -m unittest tests.test_validate_knowledge_labels_cli -v`

Expected: FAIL because the current CLI sends all known labels to DS.

- [x] **Step 3: Implement the deterministic skips**

```python
if row.get("validation_action") == "skip_policy_forbidden":
    return _skipped_output(base, reason="policy_forbidden", recommended=[]), "skipped"
if row.get("validation_action") == "skip_policy_unresolved":
    return _skipped_output(base, reason="policy_unresolved", recommended=None), "skipped"
```

- [x] **Step 4: Verify green**

Run: `python3 -m unittest tests.test_validate_knowledge_labels_cli -v`

Expected: PASS with zero recording-server requests.

### Task 4: Document the exact policy and verify the repository

**Files:**

- Modify: `docs/knowledge-label-validation.md`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-25-knowledge-presence-policy.md`
- Test: `tests/test_build_knowledge_validation_packet_cli.py`

**Interfaces:** DS-eligible packet rows expose `knowledge_policy="required"` or `"optional"`. Documentation records teacher-matrix facts: cloze children are `forbidden`; grammar-selection children are `required`; reading, restoration, matching, question-answer and table routes require exact-route approval and cannot be configured by a broad family default.

- [x] **Step 1: Assert the completed packet schema**

```python
self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["knowledge_policy"], "required")
```

- [x] **Step 2: Run the focused schema test**

Run: `python3 -m unittest tests.test_build_knowledge_validation_packet_cli -v`

Expected: PASS; the field was added as part of Task 2's test-driven packet routing change.

- [x] **Step 3: Update documentation and output fields**

Document build/validation commands, expected skip statuses, and that a forbidden result is an auditable candidate for a later patch, not a source overwrite.

- [x] **Step 4: Verify full repository**

Run: `python3 -m unittest discover -s tests -v`

Expected: PASS.

- [x] **Step 5: Commit and push**

```bash
git add english_knowledge_tagger/knowledge_candidate_policy.py \
  english_knowledge_tagger/knowledge_validation_packet.py \
  scripts/validate_knowledge_labels.py configs/knowledge_candidate_policies \
  tests/test_knowledge_validation_packet.py tests/test_validate_knowledge_labels_cli.py \
  tests/test_build_knowledge_validation_packet_cli.py README.md \
  docs/knowledge-label-validation.md docs/superpowers/plans/2026-08-25-knowledge-presence-policy.md
git commit -m "feat: enforce knowledge presence policies"
git push origin HEAD:main
```

## Self-Review

- Exact route keys are the only policy lookup; no parent inheritance or blanket reading default exists.
- Forbidden history remains auditable and cannot silently disappear.
- Unresolved does not mean an empty label set.
- Existing grammar-selection limits remain 12 retrieved, 8 siblings, 3 final labels.
- No step rewrites the source JSONL or treats a DS result as ground truth.
