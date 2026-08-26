# DS-V4-Flash 候选打标与直接判别接入

> `scripts/label_candidates.py` 是早期的“生成候选标签”工具，不是当前高质量提取的首入口。当前首入口是逐末级历史标签的直接判别，再经过人工 calibration policy 分流；完整流程见 [数据清洗执行手册](data-cleaning-playbook.md)，文档状态见 [文档状态](document-status.md)。

This component calls the internal OpenAI-compatible service at
`http://172.22.0.35:6636/v1/chat/completions` with model `ds-v4-flash`.
It generates **review candidates only**. It never edits source JSONL, current
labels, or any `hq-v*` dataset directly.

## 两种不应混淆的 DS 使用方式

### A. 当前：外部直接判别器结果接入

mentor/DS 批量判别的语义是：`题目 × 某个已有末级标签 → match true/false`。原始 runner 的 JSON 字段可能不同，因此必须先显式映射为统一 evidence，再交给本地 gate：

```text
raw discriminator JSONL
  → normalize_terminal_label_discriminator.py（field-map）
  → gate_terminal_label_discriminator.py（人工校准 policy）
  → silver_label_candidate / relabel_candidate / hold
```

这个阶段不发送 top-k 备选标签，也不使用 `label_candidates.py` 的生成 prompt。模型的 `reason`、`confidence` 只用于人工复核；`match=true` 只有在标签已完成校准时才可进入 silver。

### B. 历史：生成替换候选

本文件其余 `label_candidates.py` 流程属于替换/补标的辅助链路：

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
existing SFT `input` is deliberately retained for this historical candidate
tool. For the **current direct-label discriminator**, the upstream rendered
`题型结构为：...` / `题型名称为：...` text must be removed from the prompt body;
it may remain in local audit provenance but must not let the model echo dirty
type metadata.

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
