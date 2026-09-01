# 题型分层抽样与 DS 开放式题型发现

该流程只处理 `is_sub_question` 严格等于 `false` 的完整大题，再从其 `output` 字段中提取
每个精确的 `题型@...` 标签；`知识点@...` 标签不参与抽样。每类稳定抽取最多 1000 题，
不足 1000 题的类别全部保留。没有题型标签的大题、子题以及 `is_sub_question` 缺失或类型
异常的记录均跳过并计入抽样报告。同一道题若同时被多个类别抽中，样本包只保留一行，并在
`sampled_type_labels` 中记录全部抽样类别，避免重复调用模型。

模型只接收仓库内的 `question-type-discovery-v1.txt` 与清洗后的源 `input`。清洗会删除：

- `题型结构为：...`
- `题型名称为：...`

历史 `instruction`、`output` 和当前题型标签只保留在样本及结果中作审计，不进入模型请求。
模型不接收旧题型树，流式返回一个 19 字段 JSON 对象。程序严格校验字段、枚举、数组和
`confidence`；合法结果以 `candidate_type_label` 为主候选标签，其余字段保留材料、作答机制、
设问功能、目标语言形式、写作要求和新增区分角度。结果不会修改源数据。

## 服务器执行

先拉取代码并创建独立运行目录：

```bash
cd /local_data/zhangyonglin/english-knowledge-tagger
git pull --ff-only origin main

export FINAL_SOURCE=/local_data/zhangyonglin/english-knowledge-tagger-data/sources/cleaned_final_enhanced_v2.jsonl
export TYPE_RUN=/local_data/zhangyonglin/english-knowledge-tagger-runtime/type-discovery-v1-20260831
mkdir -p "$TYPE_RUN"
```

按当前精确题型标签抽样：

```bash
python3 scripts/reclassify_question_types.py sample \
  --input "$FINAL_SOURCE" \
  --output "$TYPE_RUN/type-sample.jsonl" \
  --report "$TYPE_RUN/type-sample.report.json" \
  --per-type 1000 \
  --seed 20260828
```

先用 20 题验证两个流式端点：

```bash
python3 scripts/reclassify_question_types.py run \
  --input "$TYPE_RUN/type-sample.jsonl" \
  --output "$TYPE_RUN/type-results.smoke.jsonl" \
  --report "$TYPE_RUN/type-results.smoke.report.json" \
  --endpoint http://172.22.0.35:9102/v1/chat/completions \
  --endpoint http://172.22.0.35:9103/v1/chat/completions \
  --model DeepSeek-V4-Flash \
  --per-endpoint-concurrency 15 \
  --max-tokens 1024 \
  --limit 20
```

确认 smoke 报告中 `error` 为 0 后执行全量：

```bash
python3 scripts/reclassify_question_types.py run \
  --input "$TYPE_RUN/type-sample.jsonl" \
  --output "$TYPE_RUN/type-results.jsonl" \
  --report "$TYPE_RUN/type-results.report.json" \
  --endpoint http://172.22.0.35:9102/v1/chat/completions \
  --endpoint http://172.22.0.35:9103/v1/chat/completions \
  --model DeepSeek-V4-Flash \
  --per-endpoint-concurrency 15 \
  --timeout-seconds 60 \
  --max-tokens 1024 \
  --max-retries 3 \
  --allow-full
```

请求体固定包含 `"stream": true`。两个端点各自拥有独立的 15 线程池，因此总并发为 30，
同时每个 vLLM 进程不会超过 15 个并发。每个完成结果立即以一行 JSON 刷入磁盘。

全量进程意外中断后，使用完全相同的命令并追加 `--resume`。程序会读取已有结果，跳过已完成的
`review_id` 并继续追加；报告会更新为本次续跑统计。
