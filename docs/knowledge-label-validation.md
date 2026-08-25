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

## 知识点存在性策略

每一条策略只匹配一个精确 `scope × 题型结构 × 题型名称`，`knowledge_policy` 的含义如下：

| 策略 | 含义 | DS-V4 行为 | 是否可直接写回源数据 |
|---|---|---|---|
| `required` | 小题必须有 1 个或多个知识点 | 在该题型受限候选池中验证/补充候选 | 不可，仍需抽检和 patch |
| `optional` | 小题可以有 0 个或多个知识点 | 允许 DS 结论为不保留任何标签 | 不可 |
| `forbidden` | 该小题最终知识点集合应为空 | 不请求 DS；历史知识点写成可审计的 policy conflict | 不可 |
| `unresolved` | 业务规则还未确认 | 不请求 DS，也不把它解释成空标签 | 不可 |

当前 `configs/knowledge_candidate_policies/child-knowledge-presence-v0.1.json` 只固化了老师图片和真实 112 组清单都能对齐的五个路由：

```text
required:
  child × 复合题 × 语法选择
  child × 完形填空 × 语法选择

forbidden:
  child × 复合题 × 完形填空
  child × 完形填空 × 完形填空
  child × 复合题 × 阅读理解
```

两个 `required` 路由只允许从 `知识点->词法` 和 `知识点->句法` 选择，不允许从语篇主题、语篇体裁、语用或父题标签中继承。每题最多输出 3 个知识点。三个 `forbidden` 路由的历史知识点即使未来出现在上游数据中，也只生成 `policy_forbidden` 审计项，不能被 DS 重新解释为合法标签。

这不是“所有阅读题小题永远不打知识点”的通配规则；它只作用于上述精确路由。阅读还原、阅读匹配、阅读问答、阅读填表等若以不同结构/名称出现，仍是 `unresolved`，需要继续按老师矩阵和盲审样本逐项确认。

老师 CSV 已随仓库版本化。默认使用仓库内规则本；如需试验新版本，可用环境变量覆盖，但新文件必须先完成版本审查。

```bash
export TEACHER_CSV=data/rulebooks/初中英语知识点题型方法释义.csv
export KP_POLICY=configs/knowledge_candidate_policies/child-knowledge-presence-v0.1.json
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

第二个命令最多处理 50 条**标签验证项**，不是 50 道题。若一题有多个历史知识点标签，它会生成多个验证项；`forbidden` 或 `unresolved` 的项会写入结果文件，但不会占用 DS-V4 请求。

`--concurrency` 取值为 1–128，默认 1。高并发时输出仍按输入 JSONL 顺序写入，便于与审查包逐行比对。`--concurrency` 大于 1 时，`--sleep-seconds` 必须为 0；如需降低服务压力，应直接降低并发数。

## 分层树候选：replace 与 required 缺标的第二阶段

平铺验证只负责判断已有历史标签是否可保留，并给出受限 pool 内的初步替换建议。若结论为 `replace`，或为 `uncertain + insufficient`，以及 `required` 小题完全没有历史知识点时，可以启动树搜索来**额外生成一个**末级候选。

树从老师 CSV 的 active 知识点路径构建。每一步只给 DS 当前兄弟节点和控制符 `__NO_MATCH__`；终端兄弟节点才携带压缩释义。真实标签 `知识点->其他` 与控制符完全不同。`__NO_MATCH__` 会回退并排除刚失败的分支；在题型受限根节点仍无匹配时输出 `uncovered`，绝不自动置空。

树搜索不是最终多标签输出，也不替换原有 flat 验证。输出只进入 `relabel_candidates`，应和 flat `replace` 分层抽检比较。首轮每题最多 8 次选择、最多 2 次回退。

```bash
export TREE_RUN=knowledge-tree-v0.1-$(date +%Y%m%d-%H%M%S)
export TREE_DIR="$RUNTIME/knowledge-tree/$TREE_RUN"
mkdir -p "$TREE_DIR"

export TREE_TASKS="$TREE_DIR/tasks.jsonl"
export TREE_TASK_REPORT="$TREE_DIR/tasks.report.json"
export TREE_RESULTS="$TREE_DIR/ds-v4-results.jsonl"

python3 scripts/build_knowledge_tree_tasks.py \
  --source "$FINAL_SOURCE" \
  --review-packet "$CHILD_KP_CAL" \
  --validation-packet "$KP_PACKET" \
  --validation-verdicts "$KP_VERDICTS" \
  --candidate-policy configs/knowledge_candidate_policies/child-knowledge-presence-v0.1.json \
  --output "$TREE_TASKS" \
  --report "$TREE_TASK_REPORT"

python3 scripts/route_knowledge_tree.py \
  --input "$TREE_TASKS" \
  --teacher-csv data/rulebooks/初中英语知识点题型方法释义.csv \
  --output "$TREE_RESULTS" \
  --limit 100 \
  --concurrency 16 \
  --max-steps 8 \
  --max-backtracks 2
```

树 CLI 的 `--concurrency` 是并行任务数；每项任务最多会产生 8 个 DS 请求。先以 16 或 32 启动，在服务稳定后再提高，不要沿用平铺验证的 128 作为默认值。

### 末级压缩释义的 3×2 消融

该实验固定同一份 `$TREE_TASKS`、老师 CSV、模型、并发、搜索预算和 DS endpoint，仅改变末级候选是否附带“压缩释义”。`compressed` 是当前默认行为，`none` 只发末级完整路径。每个模式独立运行三次；即使 temperature 为 0，服务端仍可能出现输出波动，因此必须保留三份结果。

```bash
export ABLATION_DIR="$TREE_DIR/terminal-definition-ablation"
mkdir -p "$ABLATION_DIR"
sha256sum "$TREE_TASKS" data/rulebooks/初中英语知识点题型方法释义.csv \
  configs/knowledge_candidate_policies/child-knowledge-presence-v0.1.json \
  > "$ABLATION_DIR/input-manifest.sha256"

for spec in compressed:1 none:1 none:2 compressed:2 compressed:3 none:3; do
  mode="${spec%:*}"
  repeat="${spec#*:}"
  python3 scripts/route_knowledge_tree.py \
    --input "$TREE_TASKS" \
    --teacher-csv data/rulebooks/初中英语知识点题型方法释义.csv \
    --output "$ABLATION_DIR/$mode-$repeat.jsonl" \
    --limit 100 \
    --concurrency 16 \
    --max-steps 8 \
    --max-backtracks 2 \
    --terminal-definition-mode "$mode"
done

python3 scripts/analyze_knowledge_tree_runs.py \
  --with-definitions compressed-1="$ABLATION_DIR/compressed-1.jsonl" \
  --with-definitions compressed-2="$ABLATION_DIR/compressed-2.jsonl" \
  --with-definitions compressed-3="$ABLATION_DIR/compressed-3.jsonl" \
  --without-definitions none-1="$ABLATION_DIR/none-1.jsonl" \
  --without-definitions none-2="$ABLATION_DIR/none-2.jsonl" \
  --without-definitions none-3="$ABLATION_DIR/none-3.jsonl" \
  --output "$ABLATION_DIR/summary.json"
```

`summary.json` 的 `groups.*.replace.all_three_candidate_agreement` 是 replace 任务三次得到同一末级候选的比例；`all_three_decision_agreement` 同时要求状态也相同。`comparison.unanimous_candidate_disagreements` 只计算两种模式内部均完全一致、但候选不同的题，适合人工优先抽看。

不要只按一致率自动决定是否保留释义：先人工复核两个模式都稳定但互相不同的题，以及任一模式不稳定的 replace 题。若压缩释义在 replace 切片上稳定性不下降、`uncovered/budget_exhausted` 未上升、且人工正确率更高，才保留；若效果无差异，优先 `none` 以缩短 prompt。

## 结果处理

| 验证状态 | 含义 | 后续去向 |
|---|---|---|
| `candidate` + `keep` | 旧标签与题面、释义一致 | 作为 silver 候选，仍需分层抽检 |
| `candidate` + `replace` | 候选池有更合适的标签 | `relabel_candidates`，不得直接替换 |
| `candidate` + `drop` + `covered` | 旧标签并非解题必需 | `relabel_candidates` |
| `candidate` + `uncertain` + `insufficient/unknown` | 题面不足或候选池不覆盖 | 人工/二次模型复核，并扩充候选池 |
| `skipped` + `policy_forbidden` | 已确认该精确小题路由不应有知识点 | `relabel_candidates`；建议最终知识点集合为 `[]`，仍需人工抽检后出 patch |
| `skipped` + `policy_unresolved` | 尚无可执行的业务规则 | 隔离，补充题型路由和规则确认，不能按空标签入库 |
| `tree_candidate` | 树路由到一个 active 末级知识点 | 与 flat 结果一起进入 `relabel_candidates`，分层抽检，不直接 patch |
| `uncovered` / `budget_exhausted` | 受限 taxonomy 根无匹配，或搜索预算耗尽 | 保留 trace，补 taxonomy/释义或人工复核；不能输出空标签 |
| `unparsed` / `error` / `skipped` | 模型输出、服务或 taxonomy 映射异常 | 隔离并保留原始证据 |
