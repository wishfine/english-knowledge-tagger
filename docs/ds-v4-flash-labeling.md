# DS-V4-Flash candidate labeling

This component calls the internal OpenAI-compatible service at
`http://172.22.0.35:6636/v1/chat/completions` with model `ds-v4-flash`.
It generates **review candidates only**. It never edits source JSONL, current
labels, or any `hq-v*` dataset directly.

## Boundary and workflow

```text
review packet -> DS-V4 candidate JSONL -> human decision -> patch JSONL -> hq dataset build
```

The service output is evidence for a reviewer, not a ground-truth label. A
candidate record preserves the original output label string, the raw service
completion, extracted candidate labels, prompt version, model name, and request
ID. Only approved `keep/drop/replace/add` patch records may affect an hq data
version.

## Prompt contract

`english_knowledge_tagger/candidate_labeling.py` owns prompt version
`child-kp-ds-v4-v1`. It asks for exact, semicolon-separated hierarchical labels
using the `新知识树@...` prefix. The parser also accepts legacy `知识点@...`
responses but never silently promotes explanatory prose to a label.

For one-to-many hard cases, include a `candidate_definitions` string in the
review packet. This should contain the approved short definition and exclusion
condition for a small candidate set. Do not send the full taxonomy by default.

Changing prompt wording, label prefix, output format, or parser behavior requires:

1. a new `PROMPT_VERSION`;
2. regression tests with representative teacher-verified examples;
3. a note in this document and the run manifest.

## Review packet input

The CLI consumes JSONL. Each row must contain `question_id` and `input`. The
existing SFT `input` is deliberately retained: this project is back-labeling
existing questions, so question type structure/name, answers, analyses, and
parent context are valid evidence.

Optional fields are `parent_id`, `is_sub_question`, `output`, and
`candidate_definitions`.

```json
{
  "question_id": "child-123",
  "parent_id": "parent-100",
  "is_sub_question": true,
  "input": "题型名称为：语法填空\n题目答案：...\n题目解析：...",
  "output": "知识点@...",
  "candidate_definitions": "新知识树@...：何时使用；不包括什么。"
}
```

## Run a small batch

The explicit `--limit` is mandatory to prevent accidental full-dataset calls.
Start with a reviewed, homogeneous packet of 20 items.

```bash
python3 scripts/label_candidates.py \
  --input /local_data/zhangyonglin/english-knowledge-tagger-runtime/review_packets/child_kp_batch_001.jsonl \
  --output /local_data/zhangyonglin/english-knowledge-tagger-runtime/candidates/child_kp_batch_001.ds-v4.jsonl \
  --limit 20 \
  --sleep-seconds 0.1
```

The default endpoint can be overridden without changing source code:

```bash
export ENGLISH_TAGGER_DS_V4_ENDPOINT=http://172.22.0.35:6636/v1/chat/completions
export ENGLISH_TAGGER_DS_V4_API_KEY=""  # only set when the service later requires one
```

The CLI refuses to overwrite an existing output. Use a new batch/run name to
rerun a request. Records with service or input errors are written with
`status: "error"` for diagnosis; they are never discarded silently.

## Verification

```bash
python3 -m unittest discover -s tests -p 'test_candidate_labeling.py' -v
python3 -m unittest discover -s tests -p 'test_label_candidates_cli.py' -v
```
