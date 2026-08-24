# English Knowledge Tagger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tested Qwen3.5-4B LoRA/QLoRA pipeline that learns to assign one or more controlled English knowledge-point labels to a question.

**Architecture:** A small pure-Python core owns the JSONL schema, taxonomy validation, deterministic content-grouped split, prompt rendering, response parsing, and metrics. Thin CLI scripts call that core; the training CLI applies PEFT LoRA to a causal language model and masks all prompt tokens, leaving loss only on canonical assistant JSON.

**Tech Stack:** Python 3.10+, PyTorch, Transformers, PEFT, Accelerate, Datasets, bitsandbytes, pytest.

## Global Constraints

- Base model default: `Qwen/Qwen3.5-4B`; local server model path overrides it.
- Supervision is UTF-8 JSONL with one non-empty `id`, `question`, and non-empty `knowledge_points` list per record.
- Every gold and predicted label must occur in `data/taxonomy/knowledge_points.json`.
- Raw data, model files, checkpoints, and reports must never be committed.
- Train/validation partition uses stable content hashes and seed `42`.
- Only the assistant completion contributes to training loss.
- Do not upgrade the pre-existing server PyTorch/CUDA installation during deployment.

---

### Task 1: Establish the contract and data-core tests

**Files:**
- Create: `tests/test_data_contract.py`
- Create: `english_knowledge_tagger/data.py`
- Create: `data/taxonomy/knowledge_points.json`
- Create: `data/examples/labeled_example.jsonl`

**Interfaces:**
- Consumes: `load_taxonomy(path: Path) -> frozenset[str]`, JSONL records.
- Produces: `QuestionRecord`, `load_records(path, taxonomy) -> list[QuestionRecord]`, `split_records(records, validation_ratio, seed) -> tuple[list[QuestionRecord], list[QuestionRecord]]`.

- [ ] **Step 1: Write the failing test**

```python
def test_split_keeps_duplicate_question_content_in_one_partition(tmp_path):
    taxonomy = {"一般过去时", "动词时态"}
    records = load_records(write_jsonl(tmp_path, [
        {"id": "a", "question": "She went home.", "knowledge_points": ["一般过去时"]},
        {"id": "b", "question": "She went home.", "knowledge_points": ["动词时态"]},
        {"id": "c", "question": "He is home.", "knowledge_points": ["动词时态"]},
    ]), taxonomy)
    train, validation = split_records(records, validation_ratio=0.5, seed=42)
    assert ({r.id for r in train} & {"a", "b"}) in ({"a", "b"}, set())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_data_contract.py -v`

Expected: FAIL because `english_knowledge_tagger.data` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
@dataclass(frozen=True)
class QuestionRecord:
    id: str
    question: str
    options: tuple[str, ...]
    answer: str | None
    analysis: str | None
    knowledge_points: tuple[str, ...]

def split_records(records, validation_ratio, seed):
    groups = group_by_content_hash(records)
    validation_hashes = choose_hashes(groups, validation_ratio, seed)
    return partition(records, validation_hashes)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_data_contract.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add english_knowledge_tagger/data.py data/taxonomy/knowledge_points.json data/examples/labeled_example.jsonl tests/test_data_contract.py
git commit -m "feat: add validated grouped dataset contract"
```

### Task 2: Define canonical prompt and response behavior

**Files:**
- Create: `tests/test_prompting.py`
- Create: `english_knowledge_tagger/prompting.py`
- Create: `english_knowledge_tagger/parsing.py`

**Interfaces:**
- Consumes: `QuestionRecord`, `frozenset[str]` taxonomy, model text.
- Produces: `build_messages(record) -> list[dict[str, str]]`, `canonical_response(labels) -> str`, `parse_response(text, taxonomy) -> list[str]`.

- [ ] **Step 1: Write the failing test**

```python
def test_parse_response_filters_unknown_labels_and_sorts_known_labels():
    result = parse_response('{"knowledge_points":["未知", "动词时态", "动词时态"]}', {"动词时态"})
    assert result == ["动词时态"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_prompting.py -v`

Expected: FAIL because `parse_response` is undefined.

- [ ] **Step 3: Write minimal implementation**

```python
def parse_response(text: str, taxonomy: AbstractSet[str]) -> list[str]:
    payload = json.loads(extract_json_object(text))
    labels = payload["knowledge_points"]
    return sorted({label.strip() for label in labels if isinstance(label, str) and label.strip() in taxonomy})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_prompting.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add english_knowledge_tagger/prompting.py english_knowledge_tagger/parsing.py tests/test_prompting.py
git commit -m "feat: add canonical tagging prompts and parser"
```

### Task 3: Add preparation and evaluation CLIs

**Files:**
- Create: `tests/test_metrics.py`
- Create: `english_knowledge_tagger/metrics.py`
- Create: `scripts/prepare_data.py`
- Create: `scripts/evaluate.py`

**Interfaces:**
- Consumes: source records, prepared/prediction JSONL.
- Produces: split JSONL, `manifest.json`, and metrics dictionary with exact-match and micro/macro F1.

- [ ] **Step 1: Write the failing test**

```python
def test_metrics_reports_exact_match_and_micro_f1():
    scores = multilabel_metrics([["A"], ["B"]], [["A"], ["A", "B"]])
    assert scores["exact_match"] == 0.5
    assert scores["micro_f1"] == 0.8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_metrics.py -v`

Expected: FAIL because `multilabel_metrics` is undefined.

- [ ] **Step 3: Write minimal implementation**

```python
def multilabel_metrics(gold: list[list[str]], predicted: list[list[str]]) -> dict[str, float]:
    counts = accumulate_set_counts(gold, predicted)
    return format_exact_micro_macro_scores(counts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_metrics.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add english_knowledge_tagger/metrics.py scripts/prepare_data.py scripts/evaluate.py tests/test_metrics.py
git commit -m "feat: add dataset preparation and evaluation"
```

### Task 4: Add completion-only PEFT training and batch inference

**Files:**
- Create: `tests/test_training_data.py`
- Create: `english_knowledge_tagger/training_data.py`
- Create: `scripts/train.py`
- Create: `scripts/predict.py`
- Create: `configs/qwen35_4b_qlora.json`
- Create: `requirements.txt`
- Create: `requirements-dev.txt`

**Interfaces:**
- Consumes: prepared JSONL and a tokenizer with `apply_chat_template`.
- Produces: tokenized dictionaries containing `input_ids`, `attention_mask`, and labels masked with `-100` before the assistant response; LoRA adapter output and prediction JSONL.

- [ ] **Step 1: Write the failing test**

```python
def test_completion_labels_mask_every_prompt_token():
    item = tokenize_completion(FakeTokenizer(), [{"role": "user", "content": "Q"}], '{"knowledge_points":["A"]}')
    assert item["labels"][:2] == [-100, -100]
    assert item["labels"][2:] == item["input_ids"][2:]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_training_data.py -v`

Expected: FAIL because `tokenize_completion` is undefined.

- [ ] **Step 3: Write minimal implementation**

```python
def tokenize_completion(tokenizer, prompt_messages, completion):
    prompt_ids = tokenizer.apply_chat_template(prompt_messages, tokenize=True, add_generation_prompt=True)
    completion_ids = tokenizer(completion + tokenizer.eos_token, add_special_tokens=False)["input_ids"]
    return {"input_ids": prompt_ids + completion_ids, "attention_mask": [1] * (len(prompt_ids) + len(completion_ids)), "labels": [-100] * len(prompt_ids) + completion_ids}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_training_data.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add english_knowledge_tagger/training_data.py scripts/train.py scripts/predict.py configs/qwen35_4b_qlora.json requirements.txt requirements-dev.txt tests/test_training_data.py
git commit -m "feat: add QLoRA training and batch prediction"
```

### Task 5: Package repeatable server deployment

**Files:**
- Create: `scripts/check_environment.py`
- Create: `scripts/server_smoke.sh`
- Create: `scripts/server_train.sh`
- Create: `docs/server-deployment.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: environment path, model path, source JSONL.
- Produces: a fail-fast JSON environment report and an idempotent command path for smoke/full training.

- [ ] **Step 1: Write the failing test**

```python
def test_environment_report_marks_missing_cuda_as_not_ready(monkeypatch):
    report = build_environment_report(cuda_available=lambda: False, package_versions={})
    assert report["ready"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_environment.py -v`

Expected: FAIL because `build_environment_report` is undefined.

- [ ] **Step 3: Write minimal implementation**

```python
def build_environment_report(cuda_available, package_versions):
    required = {"transformers", "peft", "accelerate", "datasets"}
    return {"ready": bool(cuda_available()) and required.issubset(package_versions), "packages": package_versions}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_environment.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/check_environment.py scripts/server_smoke.sh scripts/server_train.sh docs/server-deployment.md README.md tests/test_environment.py
git commit -m "docs: add server validation and training workflow"
```

### Task 6: Verify, publish, and synchronize

**Files:**
- Modify: all tracked project files only if verification exposes a defect.

**Interfaces:**
- Consumes: the complete repository and GitHub SSH remote.
- Produces: a clean test run, a local commit, an SSH-pushed `main`, and a server checkout at the same revision.

- [ ] **Step 1: Run all tests**

Run: `pytest -q`

Expected: all tests pass.

- [ ] **Step 2: Run static syntax check**

Run: `python -m compileall english_knowledge_tagger scripts`

Expected: exit status 0.

- [ ] **Step 3: Commit verified implementation**

```bash
git add .
git commit -m "feat: initialize English knowledge tagger training pipeline"
```

- [ ] **Step 4: Push and deploy**

```bash
git push -u origin main
ssh xdf-35 'cd ~/english-knowledge-tagger && git pull --ff-only origin main && git rev-parse HEAD'
```

Expected: local and server commits match. If authentication or SSH is unavailable, report the exact blocking error without claiming deployment.
