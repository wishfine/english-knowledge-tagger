# 最终知识点判别器设计

## 目标

为已经完成业务 route 过滤的逐标签数据，构建一个不携带历史标签锚定信息的最终判别器。模型输入只包含候选标签（及其老师释义）和清洗后的题目内容；模型不接收题型结构、题型名称、历史 `output_all` 或其他历史标签。

## 选择的方案

采用独立的 `final-label-discriminator-v1`，而不是给 `mentor-direct-v1` 增加开关。

`mentor-direct-v1` 的校准 prompt 有意包含 `output_all`，适合复现 mentor 的 500 条初筛；最终判别器不包含该字段，属于不同实验条件。独立版本使 prompt version、packet schema、人工校准和 60 条发布复核可分别追溯，避免把 v1 的人审结论错误迁移到 v2。

## 数据流

```text
final source（只读）
  → 历史标签 exact packet
  → route policy：eligible / quarantine
  → final-label packet（仅题目内容 + 候选标签）
  → final-label-discriminator-v1
  → 标准 evidence
  → 人审冻结的 label × route policy
  → silver_label_candidate
  → 同题所有 active 历史知识点均已通过
  → silver_question_candidate
  → 每标签独立 60 条复核通过
  → released silver / 可进入训练候选集
```

单条标签判别为 true 只产生 `silver_label_candidate`，不能单独证明一道多标签题目可以进入训练。必须经过 `assemble_silver_questions.py` 的完整标签覆盖检查。

## Prompt 契约

模型可见字段：

1. 候选历史末级标签；
2. 该标签在 mentor definition JSON 中的老师释义；
3. 从 `input` 中去掉 `题型结构为：...`、`题型名称为：...`、图片占位提示与末尾 SFT 分类指令后的题目内容。

模型不可见字段：`route_key`、`scope`、`instruction`、`output_all`、其他历史标签、题型名称、题型结构。route 是模型外的业务硬规则，在请求前通过 `eligible.packet.jsonl` 执行。

模型回复固定 JSON：

```json
{"match": true, "confidence": "high", "reason": "题目直接在多个介词选项中辨析固定搭配。"}
```

`confidence` 只用于抽检和误判簇分析，不单独决定 silver/hold；正式放行仍取决于人工冻结 policy。

## 当前已准备的 route 合规数据

数据源 SHA：`995191fb78f9ef0b9e9958563704b8d3bd2752809ef838815c443a80fe2b77ec`。

| 标签 | eligible | quarantine | 当前状态 |
|---|---:|---:|---|
| 名词（短语）辨析 | 32,747 | 7,009 | 待构建 final packet、最终判别 |
| 副词（短语）辨析 | 17,495 | 4,056 | 待构建 final packet、最终判别 |
| 动词（短语）辨析 | 55,236 | 7,750 | 待构建 final packet、最终判别 |
| 形容词（短语）辨析 | 29,769 | 5,983 | 待构建 final packet、最终判别 |

介词（短语）辨析尚未进入此表：它需要先构建 route packet，并在合规单选子集重新完成 12 条 true 人审校准。
