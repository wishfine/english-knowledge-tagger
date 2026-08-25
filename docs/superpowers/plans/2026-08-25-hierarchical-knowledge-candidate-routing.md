# Hierarchical Knowledge Candidate Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an auditable, bounded taxonomy-tree search that proposes one knowledge-point candidate only for historical `replace` cases and required-policy missing labels.

**Architecture:** Construct a read-only tree from active terminal records in the teacher CSV, then route a task through sibling choices plus a sentinel `__NO_MATCH__`. A pure state machine owns descent, branch exclusion, root termination and budgets; a DS-V4 client only makes one constrained decision at a time. A separate task builder joins source rows, type policy and existing label-validation verdicts, so tree prompts never see historical labels or declared type metadata.

**Tech Stack:** Python 3 standard library, existing OpenAI-compatible DS-V4 client transport, JSONL, `unittest`.

## Global Constraints

- Never modify source JSONL or promote tree output to a final patch/HQ label automatically.
- Tree routing produces one candidate per task; it is not a multi-label set decoder.
- `__NO_MATCH__` is a control token and must never be rendered as the real taxonomy label `知识点->其他`.
- Only `candidate + replace`, `candidate + uncertain + insufficient`, and `required` rows with no historical knowledge label create tasks.
- Tree prompts use stripped question context only; no historical knowledge labels, validation verdicts, or declared type structure/name.
- Root no-match is `uncovered`, never `drop` or an empty knowledge-point set.
- Initial limits are `max_steps=8`, `max_backtracks=2`; all budget exits are auditable.

---

### Task 1: Build a deterministic active taxonomy tree

**Files:**

- Create: `english_knowledge_tagger/knowledge_taxonomy_tree.py`
- Test: `tests/test_knowledge_taxonomy_tree.py`

**Interfaces:**

```python
NO_MATCH = "__NO_MATCH__"

@dataclass(frozen=True)
class KnowledgeTaxonomyTree:
    root_path: str
    children_by_parent: Mapping[str, tuple[str, ...]]
    terminal_records: Mapping[str, KnowledgeRulebookRecord]

    @classmethod
    def from_rulebook(cls, rulebook: KnowledgeRulebook) -> "KnowledgeTaxonomyTree": ...
    def children(self, parent_path: str) -> tuple[str, ...]: ...
    def root_candidates(self, allowed_prefixes: tuple[str, ...]) -> tuple[str, ...]: ...
    def is_terminal(self, path: str) -> bool: ...
    def definition(self, path: str) -> str | None: ...
```

- [x] **Step 1: Write failing tree tests**

```python
def test_tree_uses_active_terminal_paths_and_keeps_real_other_distinct_from_control_token(self):
    tree = KnowledgeTaxonomyTree.from_rulebook(rulebook)
    self.assertEqual(tree.root_candidates(("知识点->词法",)), ("知识点->词法",))
    self.assertIn("知识点->其他", tree.children("知识点"))
    self.assertNotIn(NO_MATCH, tree.children("知识点"))

def test_tree_rejects_a_policy_prefix_that_is_not_a_taxonomy_node(self):
    with self.assertRaisesRegex(ValueError, "not in taxonomy"):
        tree.root_candidates(("知识点->杜撰",))
```

- [x] **Step 2: Verify red**

Run: `.venv/bin/python -m pytest tests/test_knowledge_taxonomy_tree.py -v`

Expected: FAIL with import error because the tree module does not exist.

- [x] **Step 3: Implement the tree module**

```python
def _parent(path: str) -> str:
    parent, separator, _ = path.rpartition("->")
    if not separator:
        raise ValueError(f"taxonomy path has no parent: {path}")
    return parent

@classmethod
def from_rulebook(cls, rulebook):
    terminal_records = {path: record for path, record in rulebook.records.items() if record.status == "active"}
    children = defaultdict(set)
    for terminal in terminal_records:
        parts = terminal.split("->")
        for index in range(1, len(parts)):
            children["->".join(parts[:index])].add("->".join(parts[: index + 1]))
    return cls("知识点", {parent: tuple(sorted(paths)) for parent, paths in children.items()}, terminal_records)
```

- [x] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_knowledge_taxonomy_tree.py -v`

Expected: PASS.

### Task 2: Implement pure bounded descent and backtracking

**Files:**

- Create: `english_knowledge_tagger/knowledge_tree_search.py`
- Test: `tests/test_knowledge_tree_search.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class TreeChoiceRequest:
    question_context: str
    parent_path: str
    candidate_paths: tuple[str, ...]
    excluded_paths: tuple[str, ...]

@dataclass(frozen=True)
class TreeChoice:
    choice: str
    candidate_coverage: str
    evidence: str
    raw_response: str = ""

@dataclass(frozen=True)
class TreeSearchResult:
    status: str  # tree_candidate|uncovered|budget_exhausted|unparsed
    candidate_label: str | None
    trace: tuple[dict[str, object], ...]

def search_one_candidate(tree, *, question_context, allowed_prefixes, choose, max_steps=8, max_backtracks=2) -> TreeSearchResult: ...
```

- [x] **Step 1: Write failing state-machine tests**

```python
def test_search_descends_to_a_terminal_leaf_without_backtracking(self):
    result = search_one_candidate(tree, question_context="Q", allowed_prefixes=("知识点->词法",), choose=choices("词法", "名词", "可数名词"))
    self.assertEqual(result.status, "tree_candidate")
    self.assertEqual(result.candidate_label, "知识点->词法->名词->可数名词")

def test_no_match_backtracks_and_excludes_the_failed_child(self):
    result = search_one_candidate(tree, question_context="Q", allowed_prefixes=("知识点->词法",), choose=choices("词法", "名词", NO_MATCH, "冠词", "a/an的区别"))
    self.assertEqual(result.candidate_label, "知识点->词法->冠词->a/an的区别")
    self.assertIn("知识点->词法->名词", result.trace[3]["excluded_paths"])

def test_root_no_match_returns_uncovered_not_an_empty_label(self):
    result = search_one_candidate(tree, question_context="Q", allowed_prefixes=("知识点->词法",), choose=choices(NO_MATCH))
    self.assertEqual((result.status, result.candidate_label), ("uncovered", None))
```

- [x] **Step 2: Verify red**

Run: `.venv/bin/python -m pytest tests/test_knowledge_tree_search.py -v`

Expected: FAIL with import error because the search engine does not exist.

- [x] **Step 3: Implement the state machine**

```python
parent = tree.root_path
excluded: dict[str, set[str]] = defaultdict(set)
steps = backtracks = 0
while steps < max_steps:
    choices = tuple(path for path in candidates(parent) if path not in excluded[parent])
    if not choices:
        if parent == tree.root_path:
            return uncovered(trace)
        failed_child = parent
        parent = _parent(parent)
        excluded[parent].add(failed_child)
        continue
    decision = choose(TreeChoiceRequest(question_context, parent, choices, tuple(sorted(excluded[parent]))))
    steps += 1
    if decision.choice == NO_MATCH:
        if parent == tree.root_path:
            return uncovered(trace)
        backtracks += 1
        if backtracks > max_backtracks:
            return budget_exhausted(trace)
        failed_child = parent
        parent = _parent(parent)
        excluded[parent].add(failed_child)
        continue
    if tree.is_terminal(decision.choice):
        return tree_candidate(decision.choice, trace)
    parent = decision.choice
return budget_exhausted(trace)
```

Reject a choice not in `candidate_paths` or `NO_MATCH` as `unparsed`.

- [x] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_knowledge_tree_search.py -v`

Expected: PASS.

### Task 3: Add the DS-V4 one-step tree-choice client

**Files:**

- Create: `english_knowledge_tagger/knowledge_tree_choice.py`
- Test: `tests/test_knowledge_tree_choice.py`

**Interfaces:**

```python
PROMPT_VERSION = "knowledge-tree-choice-ds-v4-v1"

class KnowledgeTreeChoiceClient:
    def __init__(self, config: LabelingServiceConfig, tree: KnowledgeTaxonomyTree, *, transport: Transport | None = None): ...
    def choose(self, request: TreeChoiceRequest) -> TreeChoice: ...

def build_tree_choice_prompt(request: TreeChoiceRequest, tree: KnowledgeTaxonomyTree) -> str: ...
def parse_tree_choice_response(text: str, *, allowed_choices: frozenset[str]) -> ParsedTreeChoice: ...
```

- [x] **Step 1: Write failing client tests**

```python
def test_client_only_allows_current_siblings_and_no_match(self):
    result = client.choose(TreeChoiceRequest("题干...", "知识点->词法", ("知识点->词法->冠词",), ()))
    self.assertEqual(result.choice, "知识点->词法->冠词")
    self.assertIn("__NO_MATCH__", captured["payload"]["messages"][0]["content"])
    self.assertNotIn("历史标签", captured["payload"]["messages"][0]["content"])

def test_parser_rejects_a_child_not_offered_by_the_current_step(self):
    parsed = parse_tree_choice_response('{"choice":"知识点->词汇","candidate_coverage":"covered","evidence":"x"}', allowed_choices=frozenset({"知识点->词法"}))
    self.assertEqual(parsed.status, "unparsed")
```

- [x] **Step 2: Verify red**

Run: `.venv/bin/python -m pytest tests/test_knowledge_tree_choice.py -v`

Expected: FAIL with import error because the client does not exist.

- [x] **Step 3: Implement prompt, strict parser and client**

```python
payload = {
    "model": self._config.model,
    "messages": [{"role": "user", "content": build_tree_choice_prompt(request, self._tree)}],
    "max_tokens": self._config.max_tokens,
    "temperature": 0.0,
}

allowed = frozenset((*request.candidate_paths, NO_MATCH))
if choice not in allowed:
    return ParsedTreeChoice(status="unparsed", error="choice is outside current tree step")
```

Terminal candidate entries include `tree.definition(path)`; non-terminals include only their full canonical path.

- [x] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_knowledge_tree_choice.py -v`

Expected: PASS.

### Task 4: Build grouped replace/add tasks and route their tree searches

**Files:**

- Create: `english_knowledge_tagger/knowledge_tree_tasks.py`
- Create: `scripts/build_knowledge_tree_tasks.py`
- Create: `scripts/route_knowledge_tree.py`
- Test: `tests/test_knowledge_tree_tasks.py`
- Test: `tests/test_build_knowledge_tree_tasks_cli.py`
- Test: `tests/test_route_knowledge_tree_cli.py`

**Interfaces:**

```python
def build_knowledge_tree_tasks(
    source_path: Path, *, review_packet_path: Path, validation_packet_path: Path,
    validation_verdict_path: Path, candidate_policy: KnowledgeCandidatePolicy,
    output_path: Path,
) -> dict[str, object]: ...

def route_knowledge_tree_tasks(input_path: Path, *, output_path: Path, client: KnowledgeTreeChoiceClient,
                               tree: KnowledgeTaxonomyTree, limit: int, concurrency: int) -> dict[str, object]: ...
```

- [x] **Step 1: Write failing builder and CLI tests**

```python
def test_builder_groups_replace_trigger_and_required_missing_label_by_source_line(self):
    report = build_knowledge_tree_tasks(...)
    rows = read_jsonl(output)
    self.assertEqual(len(rows), 2)
    self.assertEqual(rows[0]["trigger_kinds"], ["replace"])
    self.assertEqual(rows[1]["trigger_kinds"], ["add_missing_required"])
    self.assertNotIn("题型名称为：", rows[0]["question_context"])

def test_router_writes_trace_without_calling_the_flat_label_validator(self):
    completed = run_router_against_local_server(...)
    self.assertEqual(result["status"], "tree_candidate")
    self.assertEqual(result["candidate_label"], "知识点->词法->冠词->a/an的区别")
```

- [x] **Step 2: Verify red**

Run: `.venv/bin/python -m pytest tests/test_knowledge_tree_tasks.py tests/test_build_knowledge_tree_tasks_cli.py tests/test_route_knowledge_tree_cli.py -v`

Expected: FAIL with import/script errors because the task builder and router do not exist.

- [x] **Step 3: Implement task builder and scripts**

```python
if validation["status"] == "candidate" and verdict == "replace":
    add_trigger(source_line, {"kind": "replace", "review_id": review_id})
if validation["status"] == "candidate" and verdict == "uncertain" and coverage == "insufficient":
    add_trigger(source_line, {"kind": "uncertain_insufficient", "review_id": review_id})
if rule.knowledge_policy == "required" and not legacy_labels:
    add_trigger(source_line, {"kind": "add_missing_required"})
```

Each script rejects existing output paths, requires positive `--limit`, supports `--concurrency 1..128`, and preserves input task order in output. The router sets `max_steps=8` and `max_backtracks=2` unless explicit bounded CLI overrides are supplied.

- [x] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_knowledge_tree_tasks.py tests/test_build_knowledge_tree_tasks_cli.py tests/test_route_knowledge_tree_cli.py -v`

Expected: PASS.

### Task 5: Document the experiment and verify the repository

**Files:**

- Modify: `docs/knowledge-label-validation.md`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-25-hierarchical-knowledge-candidate-routing.md`

- [x] **Step 1: Document exact server commands**

```bash
python3 scripts/build_knowledge_tree_tasks.py --source "$FINAL_SOURCE" --review-packet "$REVIEW_PACKET" --validation-packet "$KP_PACKET" --validation-verdicts "$KP_VERDICTS" --candidate-policy "$KP_POLICY" --output "$TREE_TASKS" --report "$TREE_TASK_REPORT"
python3 scripts/route_knowledge_tree.py --input "$TREE_TASKS" --teacher-csv "$TEACHER_CSV" --output "$TREE_RESULTS" --limit 100 --concurrency 32
```

- [x] **Step 2: Verify full test suite**

Run: `.venv/bin/python -m pytest -q`

Expected: PASS.

- [x] **Step 3: Commit and push**

```bash
git add english_knowledge_tagger/knowledge_taxonomy_tree.py english_knowledge_tagger/knowledge_tree_search.py english_knowledge_tagger/knowledge_tree_choice.py english_knowledge_tagger/knowledge_tree_tasks.py scripts/build_knowledge_tree_tasks.py scripts/route_knowledge_tree.py tests/test_knowledge_taxonomy_tree.py tests/test_knowledge_tree_search.py tests/test_knowledge_tree_choice.py tests/test_knowledge_tree_tasks.py tests/test_build_knowledge_tree_tasks_cli.py tests/test_route_knowledge_tree_cli.py README.md docs/knowledge-label-validation.md docs/superpowers/plans/2026-08-25-hierarchical-knowledge-candidate-routing.md
git commit -m "feat: add hierarchical knowledge candidate routing"
git push origin HEAD:main
```

## Self-Review

- The design covers real taxonomy depth five, `__NO_MATCH__` collision avoidance, backtracking, 8/2 budgets, replace, uncertain-insufficient and required-missing triggers.
- The state machine is independently testable without DS network calls.
- The DS client validates only current siblings plus the control token.
- Task builder grouping prevents a multi-label historical record from causing duplicate tree traversals.
- The output stays a candidate artifact; no source rewrite or multi-label finalization is introduced.
