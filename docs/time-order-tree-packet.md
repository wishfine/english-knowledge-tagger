# Order-1：时间顺序标签 tree packet

目标标签：`知识点@语用@时间@顺序`。

本实验只处理已有网页 GPT 复核结果中的可判样本：全部 60 条 `remove` 加固定种子抽取的 12 条 `keep` 控制，共 72 条。25 条 `uncertain` 不进入 tree；它们通常缺少听力原文、具体小题或图片信息。

## 离线建包

source 必须是 mentor 对该标签的完整明细，evidence 必须是同一批题的网页 GPT 逐题复核。构建器会严格校验 `question_id + parent_id`，并要求 remove 分层为 `31/16/8/5`：

```bash
python3 scripts/build_time_order_tree_packet.py \
  --source "$ORDER_SOURCE" \
  --evidence "$ORDER_EVIDENCE" \
  --output "$ORDER_RUN/tree-input-72.jsonl" \
  --audit-index "$ORDER_RUN/audit-index.jsonl" \
  --report "$ORDER_RUN/packet.report.json" \
  --seed time-order-order1-v1
```

DS 输入只含清洗后的题面、route 和 tree 参数；历史标签、网页 GPT decision 和抽样分层只保存在 audit index。

## DS 运行

两个 DS endpoint 各并发 5，总并发 10：

```bash
python3 scripts/route_knowledge_tree.py \
  --input "$ORDER_RUN/tree-input-72.jsonl" \
  --teacher-csv data/rulebooks/初中英语知识点题型方法释义.csv \
  --output "$ORDER_RUN/tree-results.jsonl" \
  --report "$ORDER_RUN/tree-timing.report.json" \
  --endpoint http://172.22.0.35:9102/v1/chat/completions \
  --endpoint http://172.22.0.35:9103/v1/chat/completions \
  --model DeepSeek-V4-Flash \
  --limit 72 \
  --concurrency 10 \
  --max-steps 8 \
  --max-backtracks 2 \
  --terminal-definition-mode compressed \
  --timeout-seconds 180
```

## 验收

- keep 控制题不能系统性离开“时间-顺序”；
- remove 的候选叶子必须真实解释题目，或合理返回 `uncovered`；
- `uncovered`、音频缺失和父/子题 route 要分开统计；
- 每个 `tree_candidate/uncovered × route × 音频状态` 簇需独立复核，未达到门禁时保持 `hold`；
- 任何 tree 结果都只是 `relabel_candidate` 证据，不直接删除或替换源标签。
