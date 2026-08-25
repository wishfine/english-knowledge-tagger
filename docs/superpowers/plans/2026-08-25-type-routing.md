# Type Routing Implementation Plan

> For agentic workers: use the executing-plans workflow task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Route every rendered SFT record to an explicit, versioned question-type policy without treating historical labels as truth.

**Architecture:** The type-rulebook loader reads the teacher CSV as a read-only taxonomy source and exposes active, deprecated, and discouraged terminal type paths. A versioned policy JSON maps the exact key scope × declared type structure × declared type name to a routing family and candidate type-tree prefixes. A streaming CLI emits one compact, auditable route record per source line plus a summary report; it never rewrites the source or emits corrected labels.

**Tech Stack:** Python 3 standard library: csv, dataclasses, json, pathlib, collections, argparse, unittest.

## Global Constraints

- The final source JSONL stays read-only; type routes are separate JSONL artifacts.
- Output labels are historical evidence only and are emitted as legacy_type_labels.
- Parent labels must never be inherited by a child route.
- Rules use only exact (scope, declared_type_structure, declared_type_name) matches; there is no wildcard fallback.
- A route with incomplete policy remains unmapped or needs_review; it never becomes approved by inference.
- No runtime data, source data, generated route artifact, or local teacher CSV enters Git.

---

### Task 1: Read the teacher type rulebook with explicit lifecycle states

**Files:**

- Create: english_knowledge_tagger/type_rulebook.py
- Create: tests/test_type_rulebook.py

**Interfaces:**

- Consumes: teacher CSV whose 末级知识点 column contains 题型->... terminal paths.
- Produces: load_type_rulebook(path: Path) -> TypeRulebook and TypeRulebook.candidates_for_prefixes(prefixes: tuple[str, ...]) -> tuple[str, ...].

- [ ] **Step 1: Write the failing test**

~~~python
def test_rulebook_filters_explicitly_deprecated_types_but_keeps_discouraged_types(tmp_path):
    source = tmp_path / "teacher.csv"
    source.write_text(
        "末级知识点,打标解读（标绿的标签，新题不再打）\n"
        "题型->阅读理解->阅读选择->细节理解,小题打此标签\n"
        "题型->阅读理解->阅读理解（综合）,新题不用打\n"
        "题型->阅读理解->其他任务型阅读->阅读填空,新题基本不用打\n",
        encoding="utf-8",
    )
    rulebook = load_type_rulebook(source)
    self.assertEqual(
        rulebook.candidates_for_prefixes(("题型->阅读理解",)),
        (
            "题型->阅读理解->其他任务型阅读->阅读填空",
            "题型->阅读理解->阅读选择->细节理解",
        ),
    )
    self.assertEqual(rulebook.status_for("题型->阅读理解->阅读理解（综合）"), "deprecated")
    self.assertEqual(
        rulebook.status_for("题型->阅读理解->其他任务型阅读->阅读填空"),
        "discouraged",
    )
~~~

- [ ] **Step 2: Run the test to verify it fails**

Run: python3 -m unittest tests/test_type_rulebook.py -v  
Expected: FAIL because english_knowledge_tagger.type_rulebook does not exist.

- [ ] **Step 3: Write the minimal implementation**

~~~python
@dataclass(frozen=True)
class TypeRulebook:
    records: Mapping[str, TypeRulebookRecord]

    def candidates_for_prefixes(self, prefixes: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(
            path for path, record in sorted(self.records.items())
            if record.status != "deprecated" and any(path.startswith(prefix) for prefix in prefixes)
        )

def load_type_rulebook(path: Path) -> TypeRulebook:
    # Read CSV with utf-8-sig; ignore non-题型 rows and reject duplicate terminal paths.
    # "新题不用打" / "新题不再打" -> deprecated.
    # "新题基本不用打" -> discouraged, retained for reviewer visibility.
~~~

- [ ] **Step 4: Run the focused test to verify it passes**

Run: python3 -m unittest tests/test_type_rulebook.py -v  
Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add english_knowledge_tagger/type_rulebook.py tests/test_type_rulebook.py
git commit -m "feat: load type rulebook from teacher csv"
~~~

### Task 2: Define, validate, and bootstrap exact route policies

**Files:**

- Create: english_knowledge_tagger/type_routing.py
- Create: scripts/bootstrap_type_routing_policy.py
- Create: tests/test_type_routing.py

**Interfaces:**

- Consumes: JSON policy with schema_version type-routing-policy-v1 and rules keyed by scope, structure, and name.
- Produces: load_type_routing_policy(path: Path) -> TypeRoutingPolicy, bootstrap_type_routing_policy(inventory: Mapping[str, Any]) -> dict[str, Any], and TypeRoutingPolicy.match(scope, structure, name) -> TypeRoutingRule | None.

- [ ] **Step 1: Write the failing tests**

~~~python
def test_policy_rejects_duplicate_exact_keys_and_approved_rules_without_candidates(tmp_path):
    duplicate = write_policy(tmp_path / "duplicate.json", rules=[RULE, RULE])
    with self.assertRaisesRegex(ValueError, "duplicate"):
        load_type_routing_policy(duplicate)

    invalid = write_policy(
        tmp_path / "invalid.json",
        rules=[{**RULE, "policy_status": "approved", "candidate_type_prefixes": []}],
    )
    with self.assertRaisesRegex(ValueError, "approved"):
        load_type_routing_policy(invalid)

def test_bootstrap_creates_one_unmapped_rule_for_each_inventory_key():
    policy = bootstrap_type_routing_policy(
        {"rows": [{"scope": "child", "declared_type_structure": "复合题", "declared_type_name": "阅读理解"}]}
    )
    self.assertEqual(policy["rules"][0]["policy_status"], "unmapped")
    self.assertEqual(policy["rules"][0]["knowledge_inheritance"], "never")
~~~

- [ ] **Step 2: Run the tests to verify they fail**

Run: python3 -m unittest tests/test_type_routing.py -v  
Expected: FAIL because routing policy interfaces do not exist.

- [ ] **Step 3: Write the minimal implementation**

~~~python
@dataclass(frozen=True)
class TypeRoutingRule:
    rule_id: str
    scope: str
    declared_type_structure: str
    declared_type_name: str
    policy_status: str
    canonical_family: str
    type_selection_mode: str
    candidate_type_prefixes: tuple[str, ...]
    knowledge_inheritance: str
    knowledge_policy: str
    review_notes: str

def bootstrap_type_routing_policy(inventory: Mapping[str, Any]) -> dict[str, Any]:
    # Stable sort inventory rows and create exactly one unmapped rule per key.
    # Every child starts with knowledge_inheritance="never"; this is not a claim
    # that child knowledge labels are forbidden.
~~~

- [ ] **Step 4: Run focused tests to verify they pass**

Run: python3 -m unittest tests/test_type_routing.py -v  
Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add english_knowledge_tagger/type_routing.py scripts/bootstrap_type_routing_policy.py tests/test_type_routing.py
git commit -m "feat: add versioned type routing policies"
~~~

### Task 3: Stream source records into auditable type routes

**Files:**

- Modify: english_knowledge_tagger/type_routing.py
- Create: scripts/route_question_types.py
- Modify: tests/test_type_routing.py

**Interfaces:**

- Consumes: rendered SFT JSONL, a TypeRoutingPolicy, and a teacher TypeRulebook.
- Produces: route_sft_record(record, source_line, policy, rulebook) -> dict[str, Any], route_sft_jsonl(...) -> dict[str, Any], and one non-overwriting route JSONL plus report JSON.

- [ ] **Step 1: Write the failing test**

~~~python
def test_router_marks_legacy_labels_as_evidence_and_detects_out_of_family_and_deprecated_labels(tmp_path):
    route = route_sft_record(
        {
            "question_id": "child-1",
            "parent_id": "parent-1",
            "is_sub_question": True,
            "input": "题型结构为：复合题\n题型名称为：阅读理解\n当前小题题干：...",
            "output": "题型@阅读理解@阅读理解（综合）;知识点@语篇主题@学校生活",
        },
        source_line=7,
        policy=approved_reading_policy(),
        rulebook=reading_rulebook(),
    )
    self.assertEqual(route["legacy_type_labels"], ["题型->阅读理解->阅读理解（综合）"])
    self.assertEqual(route["route"]["knowledge_inheritance"], "never")
    self.assertIn("legacy_type_deprecated", route["risk_codes"])
    self.assertEqual(route["source_line"], 7)
~~~

- [ ] **Step 2: Run the test to verify it fails**

Run: python3 -m unittest tests/test_type_routing.py -v  
Expected: FAIL because route_sft_record does not exist.

- [ ] **Step 3: Write the minimal implementation**

~~~python
def route_sft_record(
    record: Mapping[str, Any], *, source_line: int,
    policy: TypeRoutingPolicy, rulebook: TypeRulebook,
) -> dict[str, Any]:
    # Extract scope and declared type with the same parser as type_inventory.
    # Normalize historical 题型@... to canonical 题型->... paths.
    # Emit no corrected labels. Add only deterministic risk codes:
    # missing_declared_type, unmapped_policy, legacy_type_deprecated,
    # legacy_type_outside_candidate_prefix.
~~~

- [ ] **Step 4: Run focused tests to verify they pass**

Run: python3 -m unittest tests/test_type_routing.py -v  
Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add english_knowledge_tagger/type_routing.py scripts/route_question_types.py tests/test_type_routing.py
git commit -m "feat: route question types without mutating labels"
~~~

### Task 4: Document the source-to-policy workflow and correct the stale reading claim

**Files:**

- Modify: docs/type-policy-mapping.md
- Modify: README.md
- Modify: tests/test_type_routing.py

**Interfaces:**

- Consumes: inventory JSON, teacher CSV, and policy JSON.
- Produces: exact commands for bootstrap, policy editing, routing, and a report interpretation guide.

- [ ] **Step 1: Write the failing CLI integration test**

~~~python
def test_route_cli_refuses_existing_outputs_and_writes_summary(tmp_path):
    completed = run_route_cli(tmp_path)
    self.assertEqual(completed.returncode, 0, completed.stderr)
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    self.assertEqual(report["route_status_counts"], {"approved": 1})
~~~

- [ ] **Step 2: Run it to verify it fails**

Run: python3 -m unittest tests/test_type_routing.py -v  
Expected: FAIL because the route CLI is unavailable or incomplete.

- [ ] **Step 3: Implement docs and remaining CLI wiring**

~~~markdown
1. Run inventory_question_types.py on the final source.
2. Run bootstrap_type_routing_policy.py to create an all-unmapped policy file.
3. Fill only evidence-backed policy rows; do not derive them from historical output.
4. Run route_question_types.py; inspect risk-code counts and review only selected route slices.
~~~

The documentation must state: all children have knowledge_inheritance=never; whether a child has no knowledge labels remains a separately approved knowledge_policy, particularly for reading restoration and task-reading variants.

- [ ] **Step 4: Run all new and existing focused tests**

Run:

~~~bash
python3 -m unittest tests/test_type_rulebook.py -v
python3 -m unittest tests/test_type_routing.py -v
python3 -m unittest discover -s tests -p 'test_type_inventory.py' -v
python3 -m unittest discover -s tests -p 'test_composite_audit.py' -v
~~~

Expected: all PASS.

- [ ] **Step 5: Commit**

~~~bash
git add README.md docs/type-policy-mapping.md tests/test_type_routing.py
git commit -m "docs: document auditable type routing workflow"
~~~

## Spec Coverage Review

- Exact parent/child separation: Tasks 2 and 3.
- Historical labels are non-authoritative evidence: Tasks 2–4.
- Teacher CSV is the rule source: Task 1 and Task 3.
- Reading-child correction: Task 4 records non-inheritance without a blanket no-knowledge rule.
- Large source support and non-destructive processing: Task 3.
- Reproducible, two-developer workflow: Task 4.

## Placeholder Scan

The plan contains no deferred implementation placeholders; the policy values themselves are deliberately created as unmapped records until supported by the CSV and review evidence.

### Task 5: Generate blind, stratified type-review packets

**Files:**

- Create: english_knowledge_tagger/type_review_packet.py
- Create: scripts/sample_type_review_packet.py
- Create: tests/test_type_review_packet.py
- Modify: docs/type-policy-mapping.md

**Interfaces:**

- Consumes: rendered SFT JSONL and a positive per-route sample limit.
- Produces: build_type_review_packet(input_path, output_path, per_route, include_legacy_labels) -> dict[str, Any], with at most the requested count for every exact scope, structure, and name group.

- [ ] **Step 1: Write the failing test**

~~~python
def test_packet_stratifies_by_exact_route_and_hides_legacy_labels_by_default():
    report = build_type_review_packet(source, output_path=output, per_route=1)
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    self.assertEqual(report["records"], 2)
    self.assertEqual({row["route_key"]["scope"] for row in rows}, {"parent", "child"})
    self.assertNotIn("legacy_type_labels", rows[0])
    self.assertIn("question_context", rows[0])
~~~

- [ ] **Step 2: Run the test to verify it fails**

Run: python3 -m unittest tests/test_type_review_packet.py -v
Expected: FAIL because the packet builder does not exist.

- [ ] **Step 3: Write the minimal implementation**

~~~python
def build_type_review_packet(input_path, *, output_path, per_route=5, include_legacy_labels=False):
    # Keep the per-route records with the smallest SHA-256 score computed from
    # exact route key and question_id/source line. Memory is O(route_count × per_route).
    # The default packet supplies input and source identifiers but no legacy labels.
~~~

- [ ] **Step 4: Run focused tests to verify they pass**

Run: python3 -m unittest tests/test_type_review_packet.py -v
Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add english_knowledge_tagger/type_review_packet.py scripts/sample_type_review_packet.py tests/test_type_review_packet.py docs/type-policy-mapping.md
git commit -m "feat: sample blind type review packets"
~~~
