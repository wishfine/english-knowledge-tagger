# 小题知识点历史标签验证

本流程验证一条历史知识点标签是否合理；它不重新训练模型、不直接写 patch，也不修改源 JSONL。

每个验证项由以下内容组成：

1. 小题题干、选项、答案、解析和必要上下文；
2. 一个历史知识点标签及其老师 CSV 中的原始打标释义；
3. 由小题题型候选策略限制的标签池；
4. 历史标签的同级近邻和从受限池检索出的至多 12 个候选标签的压缩释义。

源数据中的 `题型结构为：...`、`题型名称为：...` 仅在本地用于命中候选池策略；生成验证包时会从发送给 DS-V4 的题目上下文中移除。这样模型不能直接复述历史题型名称，但仍保留题干、选项、答案、解析和必要上下文。

同一道题的所有历史标签共享同一份“题型受限检索 shortlist”；不会因正在验证的旧标签不同而更换 top-k 候选。每个历史标签仍可附加自身、且仍在允许前缀内的同级近邻。旧标签若落在小题允许范围之外，可以作为待验证对象展示，但不能作为 `keep` 或 `replace` 的可选结果。

模型只可返回 `keep`、`replace`、`drop` 或 `uncertain`。`replace` 的目标必须在包中提供的候选标签内；否则结果标为 `unparsed`，不会作为候选结论。大题知识点绝不参与小题候选池。

模型还必须输出 `candidate_coverage`：

- `covered`：候选池足以判断，才允许 `keep`、`replace` 或 `drop`；
- `insufficient`：正确标签可能未出现在候选池中，必须输出 `uncertain`；
- `unknown`：题面不足以判断候选池覆盖，必须输出 `uncertain`。

历史源数据使用的路径可能仍带有旧根节点，例如 `知识点->语法词法` 和 `知识点->语法句法`。验证包先通过版本化 migration 配置映射到老师规则本的 `知识点->词法`、`知识点->句法`，同时保留原始历史路径和映射规则。映射失败是 taxonomy 问题，不等于内容错标。

## 语法选择小题的首轮校准

当前仓库提供了两个已确认的候选池路由：

```text
child × 复合题 × 语法选择
child × 完形填空 × 语法选择
```

两者只允许从 `知识点->词法` 和 `知识点->句法` 选择，不允许从语篇主题、语篇体裁、语用或父题标签中继承。每题最多输出 3 个知识点。

老师 CSV 已随仓库版本化。默认使用仓库内规则本；如需试验新版本，可用环境变量覆盖，但新文件必须先完成版本审查。

```bash
export TEACHER_CSV=data/rulebooks/初中英语知识点题型方法释义.csv
export KP_POLICY=configs/knowledge_candidate_policies/child-grammar-selection-v0.1.json
export KP_MIGRATION=configs/knowledge_taxonomy_migrations/legacy-rendered-to-teacher-v1.json
export KP_PACKET="$ROUTE_DIR/child-kp-grammar-validation.packet.jsonl"
export KP_PACKET_REPORT="$ROUTE_DIR/child-kp-grammar-validation.packet.report.json"
export KP_VERDICTS="$ROUTE_DIR/child-kp-grammar-validation.ds-v4.jsonl"

python3 scripts/build_knowledge_validation_packet.py \
  --source "$FINAL_SOURCE" \
  --review-packet "$CHILD_KP_CAL" \
  --teacher-csv "$TEACHER_CSV" \
  --candidate-policy "$KP_POLICY" \
  --taxonomy-migration "$KP_MIGRATION" \
  --output "$KP_PACKET" \
  --report "$KP_PACKET_REPORT"

python3 scripts/validate_knowledge_labels.py \
  --input "$KP_PACKET" \
  --output "$KP_VERDICTS" \
  --limit 50 \
  --concurrency 128
```

第二个命令最多处理 50 条**标签验证项**，不是 50 道题。若一题有多个历史知识点标签，它会生成多个验证项。

`--concurrency` 取值为 1–128，默认 1。高并发时输出仍按输入 JSONL 顺序写入，便于与审查包逐行比对。`--concurrency` 大于 1 时，`--sleep-seconds` 必须为 0；如需降低服务压力，应直接降低并发数。

## 结果处理

| 验证状态 | 含义 | 后续去向 |
|---|---|---|
| `candidate` + `keep` | 旧标签与题面、释义一致 | 作为 silver 候选，仍需分层抽检 |
| `candidate` + `replace` | 候选池有更合适的标签 | `relabel_candidates`，不得直接替换 |
| `candidate` + `drop` + `covered` | 旧标签并非解题必需 | `relabel_candidates` |
| `candidate` + `uncertain` + `insufficient/unknown` | 题面不足或候选池不覆盖 | 人工/二次模型复核，并扩充候选池 |
| `unparsed` / `error` / `skipped` | 模型输出、服务或 taxonomy 映射异常 | 隔离并保留原始证据 |
