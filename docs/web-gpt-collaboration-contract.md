# 网页 GPT 协作契约

> 目标：把高 token、重复性强的题面复核与边界归因交给网页 GPT；Codex 只承担可复现的数据管道、产物校验、统计、代码与最终发布门禁。任何一方均不得直接改写源 JSONL。

## 1. 固定分工

| 工作 | 网页 GPT | Codex |
|---|---|---|
| 逐题判断标签是否适用 | 主责 | 仅处理少量争议题或复核网页 GPT 的异常结果 |
| 题面缺失、释义冲突、边界案例说明 | 主责 | 汇总为规则候选与待老师裁决清单 |
| 批量 JSONL 输出 | 主责：严格按 `review_id` 回传 | 主责：生成盲审包、校验、回连 audit index |
| DS / tree / 数据清洗脚本、数据血缘、统计 | 不做 | 主责 |
| 修改 source、发布 silver/HQ、替换标签 | 禁止 | 仅在老师规则与独立验收满足后执行 versioned patch |
| Git、环境、服务部署 | 不做 | 主责；服务器命令仍由用户执行 |

网页 GPT 的结论是 reviewer evidence，不是金标；Codex 的聚合报告也不是业务老师的最终裁决。

## 2. 最小交接包

一次只发送一个标签的一个 packet，优先 20--60 条。不要发送整个项目聊天记录、源文件、audit index、DS 原始 response 或旧标签全集。

发送给网页 GPT 的内容仅包括：

1. 本次固定指令；
2. `true-blind-review-*.jsonl` 或 `false-blind-review-*.jsonl`；
3. packet 行中自带的当前 active taxonomy 路径、老师释义、题面与 `review_id`。

**绝不能发送** `review-audit-index.jsonl`。其中含 DS `match`、`should_be`、历史输出和抽样分层，会锚定 reviewer。

## 3. 网页 GPT 返回契约

网页 GPT 必须只返回 JSONL：一题一行，一个对象，顺序保持输入顺序。不得使用 Markdown 代码块、标题、解释段落或省略任何输入题。

```json
{"review_id":"输入中的原值","decision":"keep|remove|uncertain","reason":"不超过两句，引用实际决定答案的结构或说明信息不足"}
```

字段规则：

- `review_id` 必须原样回传，不能新建、截断或改写。
- `keep`：当前 active taxonomy 标签满足老师释义，且结构、语义或选项关系实际参与作答；允许与其他知识点共标。
- `remove`：标签只是句中背景，答案并不依赖该标签所定义的知识；不负责猜 replacement。
- `uncertain`：题干、选项、答案或解析不足，或者 CSV 通用释义与题目解析的业务分类冲突。
- `reason` 必须说明宾语/双宾语/宾补/被动/及不及物对比、时态、词义、题面缺失等实际证据；不能只写“主考点不是它”。

## 4. 复核原则

1. 老师 CSV 的当前启用释义优先；题面解析可作为实例证据，但不能在没有记录的情况下扩张标签边界。
2. 多标签允许共存。不能仅因题目“还有更具体考点”就删除当前标签。
3. 同时，标签不能因自然出现就保留；必须判断该标签定义的结构是否约束答案或句型判断。
4. 单词拼写、时态变化、助动词、固定搭配等题中出现一个及物动词，不自动意味着应保留“及物动词”。
5. 发现标准语法与题目解析/业务 taxonomy 的归类冲突时，输出 `uncertain`，并在 `reason` 以 `CONFLICT:` 开头说明冲突；不要自行选边。

## 5. Codex 的接收门禁

收到网页 GPT 输出后，Codex 必须依次检查：

```text
JSONL 可解析
→ review_id 数量、集合、顺序与 packet 一致
→ decision 仅为 keep/remove/uncertain，reason 非空
→ 回连 audit index 统计 true / false / route / 建议族
→ 检查与已有校准的冲突
→ 输出 hold / silver_candidate / tree-candidate 建议
```

任何缺行、重复 ID、未知 ID、非 JSONL 输出、理由明显未引用题面，均退回网页 GPT 重做；不能由 Codex 猜测补齐。

## 6. Token 节省策略

- 网页 GPT 一次只处理一个标签、一个 packet；优先先审 direct true，再审分层 false。
- 不让网页 GPT 读代码、跑统计、设计 schema、写 shell 命令或解释整个 pipeline。
- 不让 Codex 重复逐题审已交给网页 GPT 的完整批次；Codex 只抽争议簇、校验冲突和设计下一轮实验。
- 输出理由限制为两句；不要求长链式推理。
- 对同一标签的边界规则一旦经老师冻结，写入 policy；后续网页 GPT只处理新增/冲突簇，不重审已验证样本。

## 7. 当前及物动词交接状态

`知识点@语法词法@动词@实义动词@及物动词` 的 93 条 T0 审核已完成并回连。当前结论是 `hold_true_review_has_non_keep`，不能全量 rollout。下一次网页 GPT 只应处理工作台中列出的 7 条业务边界裁决题；不再重新审核已完成的 93 条。

## 8. 可直接复制的网页 GPT 启动 prompt

```text
你是“英语知识点数据复核员”，不是项目架构师，也不需要读代码、设计数据管道、运行命令或讨论训练。

我会发送一个 JSONL 盲审 packet。请逐行审核其中的当前 active taxonomy 标签是否应保留。packet 已含老师释义、题面、选项、答案、解析与 review_id；不要要求我补发历史标签、DS 结果或 audit index。

判定原则：
1. 老师释义优先。多标签可以共存，不能因为存在更具体考点就删除当前标签。
2. 但标签不能只因自然出现在句中就保留；它定义的结构/语义必须实际约束答案或句型判断。
3. 题面、选项、答案或解析不足时写 uncertain。
4. 如果 CSV 通用释义与题目解析/业务分类明显冲突，写 uncertain，reason 用“CONFLICT:”开头；不要自行发明新规则。
5. 不要推荐 replacement label；replacement 由后续流程处理。

你必须只返回 JSONL：每个输入 review_id 恰好一行、顺序不变、无 Markdown 代码块、无标题、无额外解释。
每行严格为：
{"review_id":"原样复制","decision":"keep|remove|uncertain","reason":"最多两句，引用实际题面结构或说明信息不足"}

现在等待我发送 packet。
```
