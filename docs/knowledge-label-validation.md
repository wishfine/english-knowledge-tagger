# 小题知识点历史标签验证

本流程验证一条历史知识点标签是否合理；它不重新训练模型、不直接写 patch，也不修改源 JSONL。

每个验证项由以下内容组成：

1. 小题题干、选项、答案、解析和必要上下文；
2. 一个历史知识点标签及其老师 CSV 中的原始打标释义；
3. 由小题题型候选策略限制的标签池；
4. 历史标签的同级近邻和从受限池检索出的至多 12 个候选标签的压缩释义。

模型只可返回 `keep`、`replace`、`drop` 或 `uncertain`。`replace` 的目标必须在包中提供的候选标签内；否则结果标为 `unparsed`，不会作为候选结论。大题知识点绝不参与小题候选池。

## 语法选择小题的首轮校准

当前仓库提供了两个已确认的候选池路由：

```text
child × 复合题 × 语法选择
child × 完形填空 × 语法选择
```

两者只允许从 `知识点->词法` 和 `知识点->句法` 选择，不允许从语篇主题、语篇体裁、语用或父题标签中继承。每题最多输出 3 个知识点。

在服务器运行前，需要将老师 CSV 放到一个稳定、可读但不进入 Git 的位置，并设置 `TEACHER_CSV`。

```bash
export KP_POLICY=configs/knowledge_candidate_policies/child-grammar-selection-v0.1.json
export KP_PACKET="$ROUTE_DIR/child-kp-grammar-validation.packet.jsonl"
export KP_PACKET_REPORT="$ROUTE_DIR/child-kp-grammar-validation.packet.report.json"
export KP_VERDICTS="$ROUTE_DIR/child-kp-grammar-validation.ds-v4.jsonl"

python3 scripts/build_knowledge_validation_packet.py \
  --source "$FINAL_SOURCE" \
  --review-packet "$CHILD_KP_CAL" \
  --teacher-csv "$TEACHER_CSV" \
  --candidate-policy "$KP_POLICY" \
  --output "$KP_PACKET" \
  --report "$KP_PACKET_REPORT"

python3 scripts/validate_knowledge_labels.py \
  --input "$KP_PACKET" \
  --output "$KP_VERDICTS" \
  --limit 50 \
  --sleep-seconds 0.1
```

第二个命令最多处理 50 条**标签验证项**，不是 50 道题。若一题有多个历史知识点标签，它会生成多个验证项。

## 结果处理

| 验证状态 | 含义 | 后续去向 |
|---|---|---|
| `candidate` + `keep` | 旧标签与题面、释义一致 | 作为 silver 候选，仍需分层抽检 |
| `candidate` + `replace` | 候选池有更合适的标签 | `relabel_candidates`，不得直接替换 |
| `candidate` + `drop` | 旧标签并非解题必需 | `relabel_candidates` |
| `candidate` + `uncertain` | 题面不足或候选池不覆盖 | 人工/二次模型复核 |
| `unparsed` / `error` / `skipped` | 模型输出、服务或 taxonomy 映射异常 | 隔离并保留原始证据 |
