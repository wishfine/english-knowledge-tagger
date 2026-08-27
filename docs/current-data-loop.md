# 当前数据处理 Loop（题型 + 知识点）

> 本文记录当前工程运行状态与已完成实验；按步骤执行时优先阅读 [数据清洗执行手册](data-cleaning-playbook.md)，文档适用性见 [文档状态](document-status.md)。

## 目的与边界

本项目不是把约 320 万历史题目“一次性洗干净”，而是持续产出可以训练生成式 SFT 的 `hq-v*` 高质量数据。当前正式基座数据为 mentor 提供的增强版本：

```text
cleaned_final_enhanced_v2.jsonl
3,203,122 条；SHA-256：995191fb78f9ef0b9e9958563704b8d3bd2752809ef838815c443a80fe2b77ec
```

该数据中的历史 `output` 同时含题型和知识点，可能错标、漏标或使用旧 taxonomy。因此它是只读的 `legacy` 证据，不能直接视为训练真值。

本 loop 的四条底线：

1. 不覆盖源 JSONL；所有结论都以审计结果或 versioned patch 追加。
2. 大题知识点不继承给小题。父子关系只用于上下文、血缘和题型结构判断。
3. DS-V4、Doubao、Gemini 的结果都是候选证据，不会直接改标签或进入 HQ。
4. 未确认的题型路由或知识点规则必须隔离，不能因为“无标签”就默认打空。

从 2026-08-26 起，**历史末级知识点的直接判别**是小题知识点高质量提取的主入口：
`题目 × 现有末级标签 → 该标签是否合理`。题型 route 仍是父/子范围、抽检和错误分析的重要维度，但不再作为“这个标签能否被直接判别”的硬候选前缀。flat shortlist 与知识点树只处理直接判别的 false、错误、未校准或缺标难例。

## 数据层与版本

| 层 | 含义 | 是否可训练 | 关键约束 |
|---|---|---:|---|
| `legacy` | mentor 提供的增强源与历史标签 | 否 | 只读、可错标/漏标 |
| `audit` | 题型路由、标签验证、树搜索等审计 JSONL | 否 | 记录全部证据与风险码 |
| `silver` | 规则、历史标签、模型候选一致，且经过分层抽检的候选 | 仅实验 | 不能替代人工确认 |
| `patch` | 人工确认的 `keep/drop/replace/add` 变更 | 间接 | 必须带来源、规则版本、审查证据 |
| `hq-v*` | `legacy + 已批准 patch` 构造的冻结数据版本 | 是 | 可复现、有独立评测集 |

首期节奏：`hq-v0.1（2–3 万）→ SFT pilot → 错误切片补数 → hq-v1.0（10 万+）`。后续可按“适用的题型路由 × 知识点”观察覆盖，目标在业务允许的前提下逐步达到每个有效单元约 400 题，而不是对全部长尾标签盲目补数。

## 总体闭环

```text
只读增强源 + 老师 CSV
        │
        ├─ ① 逐末级历史标签直接判别（当前主入口）
        │       │
        │       ├─ 标签级人工校准 policy
        │       ├─ match=true → silver_label_candidate 或 hold
        │       ├─ match=false → relabel_candidate 或 hold
        │       └─ 全历史标签正向覆盖 → silver_question_candidate
        │
        ├─ ② 题型 inventory / 盲审 / 精确题型策略（并行审计）
        │       │
        │       └─ 决定 parent/child、知识点存在性和 HQ 门禁
        │
        └─ ③ false / 未校准 / 缺标 / 冲突难例
                │
                ├─ flat 候选验证或分层树搜索（DS-V4）
                ├─ 人工或 Gemini 盲审、按标签与 route 分组复核
                └─ 确认 patch
                         │
                         ├─ 构造并冻结 hq-v* + dev/test
                         └─ SFT 评测错误 → 新问题簇 → 回到 ①/②/③
```

当前主线一次 loop 的最小单位是一个**末级知识点标签**；需要时可扩展为一个定义和根因一致的同质问题簇，例如“介词中的时间/地点/其他边界”。route 只是该标签的分层维度，不是先决候选池。

对于 `match=true` 低、且已确认 direct verifier 同时有 false positive/false negative 的标签，进入“whole-tree 纠错实验”支路：先把原始判别明细分为 tree task 与 hold，再以小批树搜索探索一个 active 末级候选。树的结论仍只是 `relabel_candidate`，不产生 patch；详见[知识点标签验证](knowledge-label-validation.md#mentor-直接判别低产量标签whole-tree-纠错实验包)。

## 0. 每个 batch 先冻结输入

每次运行先创建独立目录和 manifest，至少记录：

- 源文件绝对路径、行数和 SHA-256；
- 老师规则本 CSV、题型策略、知识点策略、taxonomy migration 的 SHA-256；
- 精确 route key、抽样规则、随机种子/稳定排序规则、源行号；
- DS endpoint、模型名、prompt version、并发与搜索预算；
- 输出文件路径、运行时间和人工复核批次号。

输出文件一律新建，脚本拒绝覆盖。不要把不同源文件、不同规则版本或不同抽样包的结果混在同一个统计中。

## 1. 题型路由 Loop（大题与小题分别处理）

### 输入

- 增强源中的 `is_sub_question`、`question_id`、`parent_id`、渲染题面；
- 老师 CSV 的题型方法树与“打标解读”；
- 历史题型标签，只作为 evidence。

### 执行

1. 用 `scripts/inventory_question_types.py` 枚举所有精确组合：

   ```text
   scope(parent | child) × 题型结构 × 题型名称
   ```

2. 用 `scripts/sample_type_review_packet.py` 对一个精确组合抽取盲审包；默认隐藏历史 `output`，避免被旧题型标签锚定。
3. 根据老师题型矩阵和盲审结果，填写 versioned type-routing policy。策略唯一键仍是上述三元组，不使用通配符或“未命中就沿用旧标签”。
4. 用 `scripts/route_question_types.py` 对该策略做审计路由，输出候选题型树、历史标签证据和风险码，不改源数据。
5. 对抽样结果做人工确认后，才把该 route 标为 `approved`。

### 输出状态与去向

| 状态 | 含义 | 去向 |
|---|---|---|
| `approved` | 当前父/子题的题型打标规则已确认 | 可进入对应知识点 loop |
| `needs_review` / `unmapped` | 题型名称、结构或内容仍有歧义 | 继续同质盲审，不进 HQ |
| `legacy_type_deprecated` / `legacy_type_not_in_rulebook` | 旧 taxonomy 与老师规则本不一致 | taxonomy/迁移问题，单独处理 |
| `legacy_type_outside_candidate_prefix` | 历史题型与已确认题型族冲突 | 高优先级错标候选 |

### 硬规则

- 大题和小题各有独立策略行。
- 小题不继承大题的语篇体裁、语篇主题或语法词汇知识点。
- “小题不继承”不等价于“小题没有知识点”；是否需要知识点由下一节的精确路由策略决定。

题型规则的详细字段及命令见 [题型打标策略映射](type-policy-mapping.md)。

## 2. 小题知识点 Loop（当前主线）

小题知识点的首个门是直接末级标签判别，而不是先把 386 个标签压缩成一个 route-specific candidate pool。每条证据必须保留 parent/child scope；题型 route 用于分层统计、抽检与后续难例处理，不作为直接正向判别的放行条件。这样可以在题型清洗并行时继续做标签质量提取，但绝不能把未校准结果提前当训练真值。

### 2.1 直接末级标签判别 → 保守 silver（当前高质量提取入口）

单位是 `question_id × canonical terminal label`。判别器只回答“该历史标签是否确为本题解题所需”；它不负责凭空补齐遗漏标签，也不直接替换错误标签。

```text
mentor/DS 原始判别 JSONL
    → 显式 field-map 适配为 versioned evidence
    → sparse calibration policy gate
        ├─ 校准后的 match=true → silver_label_candidate
        ├─ 显式批准的 match=false → relabel_candidate
        └─ 其余（含所有未完成校准标签）→ hold
    → 只有同一题全部历史 active 标签都有正向 silver evidence
      才成为 silver_question_candidate
```

这里有三个绝不能混淆的结论：

1. `match=true` 是模型产出率，不是标签准确率；必须经该标签的人审校准台账放行。
2. `silver_label_candidate` 仅证明**一个标签**经校准后可保留；`silver_question_candidate` 也仍无法证明题目没有漏标，所以两者都不是 `hq-v*`。
3. `match=false` 默认 hold。只有该标签的 false 样本也被完整人审且 policy 明确允许时，才能进入 `relabel_candidate`。

当前校准台账尚未完成，因此 policy 必须是**稀疏白名单**：未列出的任何末级标签都强制 `hold`。`screened_12` 只能用于 preliminary silver；建议完成独立 post-sweep 的 60 条零误差正样本复核后，才可作为更强的 95% 单侧约 95% precision 下界发布门槛。即使达到该门槛，仍需以冻结评测集决定能否进入 HQ。

先按规则本生成审核骨架；它不是自动放行 policy：

```bash
export TEACHER_CSV=data/rulebooks/初中英语知识点题型方法释义.csv
python3 scripts/build_terminal_label_calibration_template.py \
  --teacher-csv "$TEACHER_CSV" \
  --output "$RUNTIME/calibration/terminal-label-review-template.jsonl"
```

待人工审核完成后，人工将**已完成标签**整理为一个 `terminal-label-calibration-policy-v1` JSON；空 policy 合法，但会把全部记录放进 hold。对某一份上游判别器导出，field-map 必须显式声明每个源字段的位置，禁止通过“看起来像 match/label”的字段名猜测：

```bash
python3 scripts/normalize_terminal_label_discriminator.py \
  --input "$RAW_DISCRIMINATOR_JSONL" \
  --field-map "$RUNNER_FIELD_MAP_JSON" \
  --output "$RUN_DIR/direct-evidence.normalized.jsonl"

python3 scripts/gate_terminal_label_discriminator.py \
  --input "$RUN_DIR/direct-evidence.normalized.jsonl" \
  --teacher-csv "$TEACHER_CSV" \
  --policy "$CALIBRATION_POLICY_JSON" \
  --silver-output "$RUN_DIR/silver-label-evidence.jsonl" \
  --relabel-output "$RUN_DIR/relabel-candidates.jsonl" \
  --hold-output "$RUN_DIR/direct-hold.jsonl" \
  --report "$RUN_DIR/direct-gate.report.json"

python3 scripts/assemble_silver_questions.py \
  --source "$FINAL_SOURCE" \
  --silver-evidence "$RUN_DIR/silver-label-evidence.jsonl" \
  --teacher-csv "$TEACHER_CSV" \
  --taxonomy-migration configs/knowledge_taxonomy_migrations/legacy-rendered-to-teacher-v1.json \
  --output "$RUN_DIR/silver-question-candidates.jsonl" \
  --hold-output "$RUN_DIR/silver-question-hold.jsonl" \
  --report "$RUN_DIR/silver-question-assembly.report.json"
```

三个脚本均拒绝覆盖输出，且不会改写上游 source 或其 `output`。组装时核对 `question_id`、`parent_id`、`is_sub_question` 和 `source_line`，因此错 source version 或旧行号的 positive evidence 会留在 hold。

### 2.2 先判断“该类小题是否应该有知识点”

策略文件：`configs/knowledge_candidate_policies/child-knowledge-presence-v0.1.json`。该版本保留为历史 baseline；`v0.2` 仅在两个已确认语法选择 route 上试验“完整直接末级兄弟”候选覆盖，必须先人工审查其 coverage packet。

| `knowledge_policy` | 行为 |
|---|---|
| `required` | 最终必须有至少一个知识点；缺标会进入补充候选流程 |
| `optional` | 可以有零或多个知识点；不能把空标签自动当作正确 |
| `forbidden` | 最终知识点集合应为空；不调用 DS，历史知识点仅记为 policy conflict |
| `unresolved` | 老师规则未确认；隔离，不调用 DS，也不输出空 |

当前只把已由老师图片、CSV 与真实题型清单共同支持的五个 exact route 写入策略。示例：

```text
required:
  child × 复合题 × 语法选择
  child × 完形填空 × 语法选择

forbidden:
  child × 复合题 × 完形填空
  child × 完形填空 × 完形填空
  child × 复合题 × 阅读理解
```

其余阅读还原、阅读匹配、阅读问答、阅读填表等不是被“一刀切判空”，而是 `unresolved`，需按老师矩阵逐项确认。

### 2.3 Flat 验证：判断一条历史标签是否合理

对 `required` 或已确认的 `optional` route，使用：

```text
build_knowledge_validation_packet.py
    → validate_knowledge_labels.py (DS-V4)
    → keep / replace / drop / uncertain
```

发送给 DS-V4 的内容是：小题题干、选项、答案、解析和必要父题上下文；**源文本中的“题型结构/题型名称”会移除**。每条历史知识点携带自己的原始老师释义；flat 验证从该 route 的允许前缀内按题面检索至多 12 个候选（`type_retrieval`），再附历史标签的直接末级兄弟（`sibling`）。v0.1 最多附 8 个；v0.2 在首个语法选择试验中附全部 type-allowed 直接兄弟。检索候选是跨分支逃逸通道，兄弟候选负责近似标签精判；因此 flat 的 alternatives 并非“当前树层的全部叶子”，且总数可能大于 12；不能向模型发送整棵 576 标签树。

`candidate_coverage` 进一步限制结论：

- `covered`：才允许 `keep`、`replace`、`drop`；
- `insufficient` / `unknown`：只能 `uncertain`，需扩充候选池或人工复核。

Flat 验证按“标签实例”运行：一题有多个历史知识点就有多个验证项。最终仍要以题为单位合并标签集合，不能把单个 `replace` 直接覆盖该题全部知识点。

### 2.4 Tree 候选：只服务难例，不替代最终多标签输出

触发条件：flat `replace`、`uncertain + insufficient`、或 `required` 路由缺少任何知识点。

```text
build_knowledge_tree_tasks.py
    → route_knowledge_tree.py
    → 一个 active 末级“补充候选” + 完整回退 trace
```

树从老师 CSV 的 active 知识点路径构建；每一步显示**当前父节点的全部直接子节点**，再加 `__NO_MATCH__` 控制项。它不使用 flat 的“检索 12 个 + 同级近邻 8 个”限制，也不会把当前节点以下的全部末级叶子一次性摊平：中间层给的是子分类节点，走到末层时才给该父节点下全部末级叶子。`__NO_MATCH__` 不是真实“其他”标签，会触发回退和排除失败分支。默认上限为 8 步、2 次回退。

树路由当前**每题只返回一个候选**，不能直接成为最终集合。若审查发现“比较级用法 + 比较级变化规则”这类关联标签，应生成 `add` patch 或多标签人工结论，而不是强迫两个正确标签二选一。

### 2.5 人工/模型复核与 patch

候选进入 `relabel_candidates` 后，按知识点、父节点、题型 route、候选数和风险码分组复核。每个确认 patch 至少应能回溯到：

```text
question_id / parent_id / source_line
route key / 原始标签集合 / 最终标签集合
action(keep|drop|replace|add)
rulebook + policy + prompt version
模型候选 / 人工证据 / 审核人 / 批次号
```

在 patch 批次完成抽检前，不写入 HQ，也不覆盖 `legacy`。

知识点策略和命令细节见 [知识点标签验证](knowledge-label-validation.md)。

## 3. 大题知识点 Loop

大题也单独处理，不由小题标签反推。阅读、完形、任务型阅读等大题通常关注语篇体裁、语篇主题，以及老师规则规定应有的题型方法；具体词法、句法考点通常应留在对应小题。

执行形式与小题相同：先通过 `parent × 题型结构 × 题型名称` 审批题型路由，再根据 CSV 建立大题知识点存在性/候选前缀策略，最后使用历史标签验证、人工复核和 patch。当前大题知识点策略尚未批量固化，因此不得拿小题策略套用到大题。

## 4. 释义与树搜索的实验 Loop

老师 CSV 同时提供标签路径、原始释义和压缩释义。释义不是默认越长越好：它可能帮助区分近邻标签，也可能把模型锚定在不恰当的例子上。

当前对首个语法选择小题切片运行了 3×2 消融：

```text
固定任务、模型、并发与搜索预算
compressed（末级附压缩释义）× 3
none（只发末级路径）× 3
```

当前 126 个树任务上，两种模式内部稳定性接近，但有 17 条“各自在三次内稳定、两模式输出不同”的题。Gemini 对这 17 条盲审的结论为 `A=8`、`B=8`、`both=1`；因此不能全局决定“永远发”或“永远不发”释义。

下一步必须先将盲审的 `A/B` 映射还原为 `{模式, 标签路径}`，再按末级标签/父节点统计：

1. 单标签命中；
2. 多标签集合的 precision、recall 和 exact match；
3. `other`、时间/地点/原因介词、主谓一致、比较级等边界簇的人工正确率；
4. 各模式的 `uncovered`、`budget_exhausted` 与不稳定比例。

对于审查结果为 `both` 的题，两个模式都不能被严格记为“最终集合完全正确”；它应进入多标签补充 patch 的校准集。全局模式选择需等解盲后的分层结果；更可能的最终方案是“按知识点节点决定是否发释义”。

同级叶子候选覆盖的 v0.1/v0.2 对照已在 983 个标签验证项上定位到 20 条完整 alternatives 集合实际增长的题。后续只对这 20 条运行 `v0.1/v0.2 × 3` 的 DS 消融：稳定选择新增叶子和跨版本稳定分歧都进入人工盲审；不能把 DS 偏好解释为新增标签正确。

## 5. 性能观测 Loop

每次新的树路由可通过 `--report` 生成独立的 `timing.report.json`。它记录：

- 整批 wall time；
- 每题 `queue_elapsed_ms`、`task_elapsed_ms`；
- 每层 `choice_elapsed_ms`、`model_call_elapsed_ms`；
- 节点候选数、prompt/response 长度、`NO_MATCH` 次数；
- p50/p95/p99、前 20 个慢任务及按 `parent_path` 聚合的热点。

性能调整必须先做小批对照：

| 现象 | 优先排查 |
|---|---|
| 排队 p95 高、单层 DS 调用正常 | 并发过高或 DS 服务饱和；比较 16/32/64 |
| 某节点慢，候选数和 prompt 长度也高 | 该分支需要检索/剪枝或压缩释义 |
| `NO_MATCH`、回退或 trace 长度高 | taxonomy 或释义边界问题，不应仅当性能问题优化 |
| 任务慢、每层调用正常 | 本地调度/序列化；先 profiler 再改实现 |

已有运行没有这些字段，不能事后可靠补算。性能报告不保存题干、答案、解析、原始回复或 evidence。

## 5.1 实验金标与候选预算 Loop

老师验证工作簿中的“`小题知识点`”sheet 是现有最高价值的金标种子：每行以 `父题ID` 和 `(1)/(2)/…` 小问编号给出人工标签集合。导入器将其保留为只读 JSONL，并迁移到老师规则本的 canonical taxonomy；不会把 Excel 直接当作最终 source child。

当前已在真实样例验证的 source 映射规则是：

```text
child_question_id = int(parent_question_id) + subquestion_index
```

最终源文件的物理行顺序并不代表小问顺序，渲染文本中的“小题序号：0”也不可靠。因此 resolver 必须全量扫描 source，验证计算出的 child ID、`parent_id` 和 `is_sub_question=true` 同时匹配，才标记为 `approved`。之后用：

```text
老师 gold − 历史标签 = missing_gold_labels
历史标签 − 老师 gold = spurious_historical_labels
```

每个 `spurious_historical_label → missing_gold_labels` 才是候选预算的有效错标校准记录。它避免把一个多标签题的所有 gold 都错误归因给某一个历史标签。

在 approved 错标校准记录上，离线比较候选策略时不调用 DS：

```text
fixed sibling=8, retrieval k=4/8/12
fixed retrieval=12, sibling=4/8/all（仅宽分支）
```

报告按历史标签父节点、gold 标签父节点及二者混淆对分层，记录 gold 处于 `historical_target / sibling / type_retrieval / absent` 的比例、候选总数和定义字符数。选择每个混淆簇“最小但不显著降低 gold coverage”的预算；不寻找一个全局 k。

只有离线 coverage 明确不同的混淆簇，才进入同输入、同并发、三次重复的 DS 纠错/稳定性实验。flat DS 运行的 `--report` 同时记录 p50/p95/p99、排队、模型调用、prompt 长度和按历史标签父节点的热点；性能报告不保留题号或题面。

## 6. 当前进度快照（2026-08-26）

| 项目 | 当前状态 | 下一步 |
|---|---|---|
| 增强源 | 已确定为正式上游源，已从 45 同步到 35 并核验 SHA-256 | mentor 新版到来时作为新 source version 审计，不覆盖本版 |
| 题型 inventory | 已对旧版源形成 112 个 `scope × 结构 × 名称` 观察行 | 以最终增强源重跑并逐 route 填写 policy |
| 首个小题 route | `child × 复合题 × 语法选择` 已抽取 500 题同质包 | 固化审查结论，继续介词/主谓一致/比较级切片 |
| flat 验证 | 983 个标签验证项：917 可解析，其中 keep 659、replace 152、drop 105、uncertain 1；63 unparsed、3 legacy taxonomy 未映射。20 条有效 sibling 增量的 v0.1/v0.2×3 结果完全一致，v0.2 未选中新增叶子且平均耗时 +8.97% | flat 默认保留 v0.1；先聚类 63 个 unparsed，并建立“已知错标且正确叶子被 v0.1 截断”的人工对抗校准集，再重评 v0.2 |
| tree 候选 | 126 个任务，其中 125 个由 replace 触发、1 个候选池不足 | 先完成 A/B 解盲与多标签评测，不直接 patch |
| 释义消融 | 3×2 已完成，不能依据稳定性单独选模式 | 解盲后按知识点节点比较；保留两种模式 |
| 性能埋点 | 已加入树路由 trace、任务和批次报告 | 新 batch 启用 `--report`，再做并发与节点热点对照 |
| 老师小题金标 | 评测 workbook 可解析为 12,240 个小问集合、21,639 个标签；其中 21,338 个为 active taxonomy，301 个未映射 | 在 35 上完成 parent+index → child 全量验证，只用 approved 错标对做 k/sibling 离线 coverage |
| HQ 与 SFT | 尚未启动 | 完成 `hq-v0.1`、冻结 dev/test 后再启动 Qwen3-VL-8B 全参 SFT |

## 7. 协作分工与交接规则

| 角色 | 负责 | 不应做 |
|---|---|---|
| mentor/老师 | 数据补全、标签业务释义、题型与知识点边界裁决、人工金标方案 | 直接覆盖历史源或让模型输出直接入训 |
| 题型负责人 | 题型 inventory、盲审、exact route policy、题型 patch | 用知识点结果反推题型真值 |
| 小题知识点负责人 | 存在性策略、候选池、flat/tree 审计、难例簇复核、知识点 patch | 从父题继承标签；把 tree 单候选当最终集合 |
| 工程负责人 | schema、版本化、脚本、测试、运行 manifest、性能报告、HQ 构建与 SFT | 替老师作业务裁决 |
| DS-V4 / Gemini / Doubao | 候选、分歧发现、审查辅助 | 直接写源数据或批准 patch |

交接时必须提供：输入 manifest、命令、输出目录、统计摘要、抽检样本、未决边界与下一步负责人。任何人发现新的系统性错标，都应新建“问题簇”，先小批复核，再扩大覆盖；不要在未验证的情况下全量重打。

## 8. 一个问题簇的完成定义

某个问题簇只有同时满足下列条件，才可以贡献给 `hq-v*`：

1. 精确题型 route 已 `approved`；
2. 大/小题粒度和知识点存在性策略已确认；
3. 候选池与 taxonomy 版本已冻结，无法映射和 unparsed 已单独处理；
4. `replace/drop/add` 候选完成分层人工抽检，形成可回放 patch；
5. 已在独立 dev/test 中保留该簇样本，训练集不混入评测真值；
6. 数据量、标签分布、图片/音频状态、风险码和抽检通过率已写入 manifest。

达到这些条件后，才把该簇并入 HQ；SFT 的错误切片会生成下一轮问题簇，而不是推翻已确认的核心数据。
