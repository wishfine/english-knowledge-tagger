# 分层知识点候选路由设计（历史设计，保留为难例组件说明）

> 树搜索仍可用于 direct `match=false`、未校准、候选不足或已知漏标的替换候选；但它不再是“历史标签是否正确”的首入口。本文中的 route 限制仅适用于该难例组件。请先阅读 [数据清洗执行手册](../data-cleaning-playbook.md) 与 [知识点标签验证](../knowledge-label-validation.md)。

## 目标

为小题知识点的 `replace` 与缺标 `add` 生成一个可审计的单标签候选路径。它不直接产生整题最终标签集合，不改写历史 JSONL，也不替代既有的平铺历史标签验证。

## 输入与触发

树路由只接受已经受精确题型策略约束的小题，并且只在下列情况创建任务：

1. 现有标签验证结论为 `candidate + replace`；
2. 现有标签验证结论为 `candidate + uncertain` 且候选池覆盖为 `insufficient`；
3. 路由的 `knowledge_policy=required`，但该小题历史知识点为空。

同一 `source_line` 合并为一个任务，保留所有触发来源作为 provenance。模型仅看到清理后的题面、答案、解析及必要上下文，不看到历史标签、历史题型名称或上一步模型的标签判断。

## Taxonomy 树

树从老师 CSV 的 386 个 active terminal `知识点->...` 路径构造。当前实测最大为 5 条边：

```text
知识点 -> 词法 -> 非谓语动词 -> 动词不定式 -> 动词不定式的结构 -> 省略to的动词不定式
```

没有 terminal 节点同时拥有子节点。每个任务的根候选只允许来自其精确题型策略的 `allowed_knowledge_prefixes`；后续层只能进入该前缀下的子节点。真实 taxonomy 中的 `知识点->其他` 是普通标签；控制符使用固定字符串 `__NO_MATCH__`，绝不使用“其他”。

## 搜索状态机

每一步将“当前节点的尚未排除子节点 + `__NO_MATCH__`”发送给 DS-V4。中间节点显示路径名称；末级节点额外显示老师 CSV 的压缩释义。

```text
选择子节点 -> 子节点是末级：成功，得到一个 tree_candidate
            -> 子节点有子节点：下钻

选择 __NO_MATCH__（当前节点非根）
            -> 在父节点中排除刚刚失败的子节点
            -> 回退到父节点，重新在未排除兄弟中选择

选择 __NO_MATCH__（受限根）
            -> uncovered；不是 drop，也不是空知识点
```

搜索记录完整 `trace`：每一步的 parent、候选、已排除分支、模型选择、证据和原始响应。首轮硬限制为 `max_steps=8`、`max_backtracks=2`；耗尽时输出 `budget_exhausted`，而非继续遍历整棵树。

## 输出与人工闭环

每个完成任务写一条独立 JSONL：`tree_candidate`、`uncovered`、`budget_exhausted`、`unparsed` 或 `error`。成功项保留候选末级标签、路径轨迹、策略版本、源行号、触发原因和服务原始响应。

`tree_candidate` 与既有 flat `replace` 结果并存，供分层抽检比较；两者都只能进入 `relabel_candidates`，不能自动写 patch 或进入 hq。多标签集合、标签关联/互斥和最终 cardinality 仍留在后续 set-level 选择阶段。

## 失败语义

- `required` 根节点无匹配：`uncovered`，优先扩展规则、人工复核或补 taxonomy；
- `optional` 根节点无匹配：同样先 `uncovered`，不能仅根据树搜索直接确认空集合；
- `forbidden` / `unresolved`：不创建树任务；
- HTTP/JSON/候选路径异常：保留请求上下文和错误，输出 `error` / `unparsed`。
