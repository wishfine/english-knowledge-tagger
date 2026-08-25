# Knowledge Label Validation Implementation Plan

> For agentic workers: use the executing-plans workflow task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Validate historical knowledge-point labels against teacher definitions and local near-label candidates without mutating source labels.

**Architecture:** A knowledge-rulebook loader reads only terminal knowledge-point rows from the teacher CSV. A versioned candidate-pool policy maps an exact child route to the knowledge-tree prefixes allowed by the teacher's large-question/small-question rule. A packet builder joins selected blind-review source lines to original labels, retrieves a bounded set from that allowed pool, and combines it with the old label's sibling alternatives. A DS-V4 client returns an auditable structured verdict; invalid or unknown taxonomy mappings remain review records rather than corrections.

**Tech Stack:** Python 3 standard library: csv, dataclasses, hashlib, json, pathlib, urllib, argparse, unittest.

## Global Constraints

- Historical labels are candidate evidence, never truth.
- Source JSONL and review packets remain read-only.
- Every output is append-only JSONL and every CLI rejects existing destinations.
- A validation verdict never changes a label or writes a patch.
- The exact target uses the original teacher interpretation; alternative labels use compressed definitions.
- Candidate pools are selected from the small question's routed type, never from parent knowledge labels.
- A route may supply at most 12 retrieved labels plus at most 8 sibling labels to DS-V4.
- Missing or unmapped historical labels are emitted for review and never sent to DS-V4 as invented labels.
- Historical root aliases must map to the teacher taxonomy before target definitions or sibling candidates are resolved.

---

### Task 1: Load knowledge definitions and build validation packets

**Files:**

- Create: english_knowledge_tagger/knowledge_rulebook.py
- Create: english_knowledge_tagger/knowledge_candidate_policy.py
- Create: english_knowledge_tagger/knowledge_validation_packet.py
- Create: scripts/build_knowledge_validation_packet.py
- Create: tests/test_knowledge_validation_packet.py

**Interfaces:**

- Consumes: teacher CSV, rendered source JSONL, and a blind-review packet containing source_line.
- Produces: load_knowledge_rulebook(path), load_knowledge_candidate_policy(path), and build_knowledge_validation_packet(source_path, review_packet_path, rulebook, candidate_policy, output_path).

- [ ] **Step 1: Write the failing tests**

~~~python
def test_packet_unions_type_allowed_retrieval_with_target_siblings_without_using_parent_labels():
    report = build_knowledge_validation_packet(
        source, review_packet_path=review, rulebook=rulebook, output_path=output,
    )
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    self.assertEqual(report["known_validation_items"], 1)
    self.assertEqual(rows[0]["legacy_label"], "知识点->语法->冠词->a/an的区别")
    self.assertIn("原始释义", rows[0]["target_definition"])
    self.assertEqual(rows[0]["candidate_pool"]["allowed_prefixes"], ["知识点->词法", "知识点->句法"])
    self.assertIn("知识点->词法->动词->时态", [item["label"] for item in rows[0]["alternative_labels"]])

def test_packet_records_unmapped_legacy_labels_without_model_definitions():
    ...
    self.assertEqual(report["unmapped_legacy_labels"], 1)
    self.assertEqual(row["taxonomy_status"], "unmapped_legacy_label")
~~~

- [ ] **Step 2: Run tests to verify they fail**

Run: python3 -m unittest tests/test_knowledge_validation_packet.py -v  
Expected: FAIL because the packet builder does not exist.

- [ ] **Step 3: Write minimal implementation**

~~~python
def build_knowledge_validation_packet(
    source_path: Path, *, review_packet_path: Path, rulebook: KnowledgeRulebook,
    output_path: Path, max_alternatives: int = 8,
) -> dict[str, Any]:
    # Select exact source_line values from the blind packet.
    # Canonicalize historical 知识点@ paths to 知识点-> paths.
    # Retrieve at most 12 compressed definitions under route-allowed prefixes,
    # merge at most 8 siblings of the historical target, then emit one item per label.
    # Parent knowledge labels are never an input to candidate selection.
~~~

- [ ] **Step 4: Run focused tests to verify they pass**

Run: python3 -m unittest tests/test_knowledge_validation_packet.py -v  
Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add english_knowledge_tagger/knowledge_rulebook.py english_knowledge_tagger/knowledge_validation_packet.py scripts/build_knowledge_validation_packet.py tests/test_knowledge_validation_packet.py
git commit -m "feat: build knowledge label validation packets"
~~~

### Task 2: Generate and parse structured DS-V4 validation verdicts

**Files:**

- Create: english_knowledge_tagger/knowledge_validation.py
- Create: tests/test_knowledge_validation.py

**Interfaces:**

- Consumes: KnowledgeValidationRequest with context, historical target, teacher definition, and alternatives.
- Produces: KnowledgeValidationClient.validate(request) -> KnowledgeValidationResult.

- [ ] **Step 1: Write the failing test**

~~~python
def test_validator_sends_target_and_alternatives_then_parses_replace_verdict():
    result = client.validate(request)
    self.assertEqual(result.verdict, "replace")
    self.assertEqual(result.best_label, "知识点->语法->冠词->the的用法")
    self.assertIn("待验证历史标签", captured["payload"]["messages"][0]["content"])
    self.assertIn("原始释义", captured["payload"]["messages"][0]["content"])
~~~

- [ ] **Step 2: Run test to verify it fails**

Run: python3 -m unittest tests/test_knowledge_validation.py -v  
Expected: FAIL because the validation client does not exist.

- [ ] **Step 3: Write minimal implementation**

~~~python
def build_knowledge_validation_prompt(request: KnowledgeValidationRequest) -> str:
    # Request only JSON: verdict keep/replace/drop/uncertain, best_label, evidence, reason.
    # The model may choose only the historical target, a supplied alternative, or null.

def parse_validation_response(text: str, allowed_labels: frozenset[str]) -> ParsedVerdict:
    # Preserve raw response. Mark invalid JSON and unsupported labels as unparsed.
~~~

- [ ] **Step 4: Run focused tests to verify they pass**

Run: python3 -m unittest tests/test_knowledge_validation.py -v  
Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add english_knowledge_tagger/knowledge_validation.py tests/test_knowledge_validation.py
git commit -m "feat: validate historical knowledge labels with ds v4"
~~~

### Task 3: Add a non-overwriting validation CLI and handoff documentation

**Files:**

- Create: scripts/validate_knowledge_labels.py
- Create: tests/test_validate_knowledge_labels_cli.py
- Create: docs/knowledge-label-validation.md
- Modify: README.md

**Interfaces:**

- Consumes: validation packet JSONL from Task 1 and DS-V4 endpoint settings.
- Produces: one candidate verdict JSONL retaining review item, raw completion, parsed verdict, model and request provenance.

- [ ] **Step 1: Write failing CLI tests**

~~~python
def test_cli_writes_candidate_verdict_without_mutating_packet():
    completed = run_cli(packet, output, mock_endpoint)
    row = json.loads(output.read_text(encoding="utf-8"))
    self.assertEqual(completed.returncode, 0, completed.stderr)
    self.assertEqual(row["validation"]["verdict"], "keep")
    self.assertEqual(row["status"], "candidate")

def test_cli_refuses_existing_output():
    ...
    self.assertIn("refusing to overwrite", completed.stderr)
~~~

- [ ] **Step 2: Run tests to verify they fail**

Run: python3 -m unittest tests/test_validate_knowledge_labels_cli.py -v  
Expected: FAIL because the validation CLI does not exist.

- [ ] **Step 3: Write minimal implementation and docs**

~~~bash
python3 scripts/build_knowledge_validation_packet.py   --source "$FINAL_SOURCE"   --review-packet "$CHILD_KP_CAL"   --teacher-csv "$TEACHER_CSV"   --output "$ROUTE_DIR/child-kp-validation.packet.jsonl"   --report "$ROUTE_DIR/child-kp-validation.packet.report.json"

python3 scripts/validate_knowledge_labels.py   --input "$ROUTE_DIR/child-kp-validation.packet.jsonl"   --output "$ROUTE_DIR/child-kp-validation.ds-v4.jsonl"   --limit 50
~~~

- [ ] **Step 4: Run focused suites**

Run:

~~~bash
python3 -m unittest tests/test_knowledge_validation_packet.py -v
python3 -m unittest tests/test_knowledge_validation.py -v
python3 -m unittest tests/test_validate_knowledge_labels_cli.py -v
python3 -m unittest tests/test_candidate_labeling.py -v
~~~

Expected: all PASS.

- [ ] **Step 5: Commit**

~~~bash
git add scripts/validate_knowledge_labels.py tests/test_validate_knowledge_labels_cli.py docs/knowledge-label-validation.md README.md
git commit -m "docs: document knowledge label validation workflow"
~~~

## Spec Coverage Review

- Teacher definitions and near-label contrast: Task 1.
- Structured model verdicts, evidence, and no direct replacement: Task 2.
- Small bounded DS-V4 runs and reproducible output: Task 3.
- Existing source/legacy preservation: all tasks.

## Placeholder Scan

The plan contains no deferred implementation placeholders. Labels that cannot map to the teacher taxonomy are explicitly emitted as unmapped evidence rather than guessed.
