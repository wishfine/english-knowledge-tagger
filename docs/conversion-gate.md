# 转化法目标标签 Gate

## 目的

`conversion-gate-v1` 是针对
`知识点@词汇@构词法@转化法` 的目标标签判定器。它只回答“这道题是否实际考查转化法”，不从整棵知识树中选择替换标签，也不修改源数据。

## 判定契约

模型输出三种决策：

| decision | 含义 | 后续动作 |
|---|---|---|
| `target_conversion` | 词形完全不变，词性/句法功能改变，且答案依赖该关系 | 保留转化法候选；如需补充其它标签，另行进入多标签流程 |
| `non_target` | 派生、屈折、普通词义/翻译、固定搭配或其它非目标关系 | 不打转化法；不要自动猜 replacement |
| `insufficient` | 题面、答案或解析无法确认源词、目标词或实际考查关系 | `hold`，补齐信息后再判 |

每条候选还必须给出：

- `source_forms`、`target_forms`；
- `form_unchanged`；
- `pos_or_function_changed`；
- `answer_depends_on_relation`；
- `confidence` 和简短 `evidence`。

`target_conversion` 只有在后三个结构字段均为 `true` 时才接受；`insufficient` 至少有一个结构字段为 `null`。不符合契约的响应记录为 `error`，不会自动降级为其它标签。

代码还会对 `source_forms` 和 `target_forms` 做确定性校验：去除词性括注和标点后，两组词形必须完全相同；若模型声称是转化法但两组词形不同，结果会被安全降为低置信度 `insufficient`，而不是相信模型的文字解释。

## 运行

先用已有的 label-blind packet：

```bash
python3 scripts/build_conversion_relation_packet.py \
  --input /path/to/materialized-conversion-500.jsonl \
  --output "$RUN/packet.jsonl" \
  --report "$RUN/packet.report.json"
```

调用 DS（两个 endpoint 各承担一半请求时，总并发建议不超过 10）：

```bash
python3 scripts/validate_conversion_gate.py \
  --input "$RUN/packet.jsonl" \
  --output "$RUN/gate-evidence.jsonl" \
  --report "$RUN/gate-report.json" \
  --endpoint http://172.22.0.35:9102/v1/chat/completions \
  --endpoint http://172.22.0.35:9103/v1/chat/completions \
  --model DeepSeek-V4-Flash \
  --concurrency 10 \
  --timeout-seconds 180
```

`gate-evidence.jsonl` 是只读证据，包含原始 DS 响应、结构字段、耗时、endpoint 和 prompt 版本；`gate-report.json` 汇总状态、决策和置信度。

## 与知识树的关系

本 Gate 必须先于 replacement tree：

```text
题目 → conversion gate
       ├─ target_conversion → 转化法候选（可继续独立找共标）
       ├─ non_target        → 不生成转化法 replacement
       └─ insufficient      → hold
```

只有明确需要寻找“其它知识点去向”的 `non_target` 题，才另建 tree packet；不能因为 tree 的 `knowledge_policy=required` 而把它们强行路由成任意知识点。Gate 结果也不能直接覆盖历史 `output_all`，正式 patch 仍需人工抽检和版本化发布。

## 已知边界

该 Gate 能处理 `plant(v.) → plant(n.)`、`water(n.) → water(v.)` 等清晰同形转化，但不替代人工校准。`direct→director`、`final→finally`、`say→says` 和只列出兼类词义的题应分别落到 `non_target` 或 `insufficient`。混合多关系题若不能确认转化关系对答案是否必要，应保守判 `insufficient`。
