# 低质量知识点标签问题工作台

> 目的：本文件是“劣质标签问题”处理 session 的唯一工作台。它不记录最终训练数据，也不替代人工台账；它记录哪些末级标签需要处理、证据指向什么根因、下一项最小实验是什么，以及在什么条件下才允许形成 `silver` 或 `patch` 候选。

## 1. 使用边界

- 历史增强源的 `output` 是只读 `legacy` 证据，可能同时有错标、漏标、旧 taxonomy 和题型元数据错误。
- DS、Gemini、规则、知识点树都只生成证据。任何 `keep`、`replace`、`drop`、`uncovered` 都不能直接改写 source。
- 500 条初筛的 `match=true` 是**模型产量**，不是准确率；它只能帮助定位问题簇。
- 人工完整样本的 `true` 和 `false` 复核应分开解读。`false` 中存在应保留题时，禁止按 DS false 批量删除。
- 本文件以“一个末级标签”或“定义与根因一致的问题簇”为最小单位；所有结论必须保留 `scope × 题型结构 × 题型名称`、数据源版本和 prompt 版本。

### 1.1 证据优先级

从高到低：

1. 老师 CSV 的当前释义、启停状态和明确题型限定；
2. 有完整题面、选项、答案、解析的人工复核；
3. 同一 source / 同一 prompt / 同一 taxonomy 版本下的 500 条 DS 初筛；
4. 历史标签、历史题型名称和模型 `should_be` 建议。

较早的人工工作稿与完整样本台账结论冲突时，以完整题面人工复核为准；冲突本身要记为数据血缘风险，而不是挑一个更方便的结论。

## 2. 通用处理闭环

```text
末级历史标签的 500 条初筛
        ↓
true / false 各自人工抽检
        ↓
根因分诊
├─ A. 历史标签错标为主        → 树广搜纠错 / 定向重标候选
├─ B. 判别器理解边界错误      → 受控 prompt / route 实验
├─ C. 题面、图片或音频不足    → hold，补信息后再判
└─ D. 题型元数据与定义冲突    → route quarantine，交题型链路复核
        ↓
小批实验 + 人工复核
        ↓
标签 × route × 根因模式的 versioned policy
        ↓
仅输出 silver / relabel_candidate / hold / patch candidate
```

### 2.1 允许的状态

| 状态 | 含义 | 是否可训练/改源 |
|---|---|---|
| `hold` | 证据不足、模型结果矛盾、题面缺失或规则未校准 | 否 |
| `route_quarantine` | 与当前题型限定冲突；知识点或题型至少一方可能有问题 | 否 |
| `silver_label_candidate` | 已通过该标签正例校准的可保留候选 | 仅实验，不改源 |
| `relabel_candidate` | tree / flat 找到的可能新标签 | 否，必须人工抽检 |
| `patch_candidate` | 已完成对应问题簇人工确认的变更建议 | 否，等待版本化批准 |
| `released_silver` | 全量正例后又独立人工复核通过 | 可参与后续 HQ 评估，仍不覆盖 source |

### 2.2 两条不同的实验路径

| 问题形态 | 先做什么 | 不能做什么 |
|---|---|---|
| 高 `match=true` 且 true 人审全对 | route 过滤（如老师明确限定）→ 全量正例 → 独立 60 条复核 | 因 false 直接删标 |
| 低 `match=true` 且 false 多数应删 | 识别根因簇 → tree 广搜纠错候选 → 人工确认候选叶子 | 把 false 直接清空 |
| 低 `match=true` 但 false 多数应留 | 修订 prompt / 释义表达 / 输入完整性 → 小批重测 | 把低产量当历史脏数据率 |
| true、false 都有明显错误 | true 与 false 都进入重查；先做小批 tree / prompt 实验 | 直接全量 rollout |

## 3. 当前问题标签队列

以下“人工复核”数字均来自已有完整题面样本；它们是当前工作结论，不是对全量真实准确率的估计。

| 优先级 | 标签 / 问题簇 | 初筛信号 | 当前根因 | 当前状态 | 下一动作 |
|---|---|---|---|---|---|
| P0 | `知识点@词汇@构词法@转化法` | 70/500 true（14.0%）；true 9/12，false 1/12 应留 | DS 将“任何词性变化”误作同形转化；历史标签混入派生、屈折、默写、固定搭配 | whole-tree 实验包已就绪 | 树广搜小批 + 人审候选叶子 |
| P0 | `知识点@词汇@词汇辨析@词汇辨析（混合词性）` | 217/500 true（43.4%）；完整复核 true 2/12 | 完形、复合题、词性变化和语法结构混入；“混合词性”本身边界不清 | 禁止 rollout | 先做题型/选项词性诊断实验 |
| P1 | `知识点@词汇@词汇辨析@介词（短语）辨析` | 404/500 true（80.8%）；true 10/12，false 3/12 应留 | 直接判别没有题型硬限制；固定介词搭配被“核心考点排他”逻辑误删 | 未校准 | 先 route 预过滤，再重新校准 |
| P1 | `词汇（音/形/义）` 的介词、动词、名词、副词子类 | 介词 157/500、动词 194/500、副词 205/500 等低产量 | DS 把“填空实际写出该词”错误压缩成唯一主考点；固定搭配、时态和语篇共标被漏掉 | 禁止 false 清洗 | 按“填空写词”业务规则做 prompt 对照实验 |
| P2 | `…@限制性定语从句@whom引导…` | 完整复核 true 9/12 | 非限制性 `whom` 被误作限制性从句 | 未校准 | 加逗号/非限制性反例的小批校准 |
| P2 | `…@限制性定语从句@where引导…` | 完整复核 true 11/12，false 3/10 应留 | 综合关系词题、抽象地点先行词的共标被漏 | 正例待补验 | 补 true 12 条；false 保持 hold |

## 4. P0：转化法

### 4.1 当前定义与已确认反例

老师释义的必要条件是：**同一单词不改变词形，直接转化为不同词性使用**。词缀、拼写增删、时态、复数、比较级、固定搭配和普通默写不属于转化法；同形多词性题可与词汇辨析共标。

| 类型 | 题目示例 | 当前正确结论 |
|---|---|---|
| 同形转化 | `text n./v.`、`wonder v./n.`、`glue n./v.` | 保留转化法候选 |
| 派生/词形变化 | `develop→development`、`Britain→British`、`warmth→warm`、`weigh→weight` | 不能保留转化法；tree 应探索派生法或其他叶子 |
| 屈折变化 | `say→says` | 不能保留转化法；可能是主谓一致等其他知识点 |
| 普通翻译/默写/搭配 | 仅翻译 `memory`、`stay at home` | 不保留转化法；tree 可给其他叶子或 `uncovered` |
| 同形边界 | `loud` 的形容词/副词并列用法 | 应允许回到转化法；不能因同时有词汇辨析就删标 |

### 4.2 已生成的离线实验包

输入是 mentor 判别器的 500 条转化法明细：

```text
/Users/wishfine/Desktop/xdf/ai题库/english-knowledge-tagger-runtime/知识点_词汇_构词法_转化法.jsonl
```

当前本地运行输出：

```text
knowledge-tree/conversion-v0.1-20260827-152549/
├─ tasks.jsonl          475 条
├─ hold.jsonl            25 条
└─ tasks.report.json
```

分流如下：

```text
70  direct_match_recheck  # 原 DS true 也要重查，不能自动 keep
405 direct_mismatch       # 原 DS false，进入树广搜
9   direct_contract_conflict hold
16  direct_insufficient hold
```

树任务的根是整个 active taxonomy，而非只搜索“词汇→构词法”：`say→says` 等题可能应到词法分支。每次搜索只产出一个候选叶子，或 `uncovered` / `budget_exhausted`；它不产生多标签最终答案。

### 4.3 转化法实验设计

#### 实验 T1：树广搜可用性小批

从 475 条 task 分层固定 60 条，至少覆盖：

- 15 条 `direct_match_recheck`，其中包含明确派生/拼写变化和同形转化；
- 20 条 `direct_mismatch`，且 mentor 建议为派生法/词汇音形义；
- 15 条 `direct_mismatch`，且 mentor 建议为词汇辨析、固定搭配或语法；
- 10 条来自翻译、单词拼写、语法填空等不同 route。

DS 恢复后运行 whole-tree，首轮预算固定为：`max_steps=8`、`max_backtracks=2`、`concurrency=16`，保留 timing report。人工审核的对象不是“模型是否和旧标签相同”，而是：

```text
tree_candidate 是否是本题的合理末级知识点；
uncovered / budget_exhausted 是否应当保持 hold；
原转化法错误时树是否仍错误返回转化法；
同形转化题是否能返回转化法。
```

通过条件：四个边界簇（同形、派生、屈折、普通翻译）都不能出现系统性方向错误；`tree_candidate` 的人工正确率达到预先约定阈值后，才扩大到其同质簇。无论结果如何，第一轮只生成 `relabel_candidate`，不生成 patch。

T1 的离线 packet builder 已完成。它以固定 SHA-256 排序构造 60 条 DS 输入：9 条已知同形转化、3 条已知派生/拼写反例、3 条 direct-true 补样、35 条按 direct false 建议分层的候选，以及 10 条翻译/拼写/父题填空 route 覆盖。DS 输入保持 `knowledge-tree-task-v1` 原样，stratum 只存在独立 audit index 中。

```bash
export TASKS=/path/to/conversion-v0.1/tasks.jsonl
export T1_DIR="$RUNTIME/low-quality-label-experiments/conversion-t1-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$T1_DIR"

python3 scripts/build_conversion_tree_t1_packet.py \
  --input "$TASKS" \
  --output "$T1_DIR/tree-input-60.jsonl" \
  --audit-index "$T1_DIR/audit-index.jsonl" \
  --report "$T1_DIR/packet.report.json" \
  --seed 'conversion-tree-t1-20260827'

# DS 服务恢复后才运行；结果仍只是 relabel_candidate evidence。
python3 scripts/route_knowledge_tree.py \
  --input "$T1_DIR/tree-input-60.jsonl" \
  --teacher-csv data/rulebooks/初中英语知识点题型方法释义.csv \
  --output "$T1_DIR/tree-results.jsonl" \
  --report "$T1_DIR/tree-timing.report.json" \
  --limit 60 \
  --concurrency 16 \
  --max-steps 8 \
  --max-backtracks 2
```

#### 实验 T2：候选叶子分簇验证

按 T1 的 tree 候选叶子分组，例如“派生法”“词汇音形义”“主谓一致”“无覆盖”。每个达到可用数量的 `原转化法 × 候选叶子 × route` 簇独立抽 12 条人工复核：

- 12/12 通过：该簇可生成 patch candidate，并再从放大结果独立抽 60 条；
- 任一错误或 uncertain：停止该簇放大，把错误例加入下一轮树/释义实验；
- `uncovered`：不强迫置空，转人工或 taxonomy/释义问题队列。

### 4.4 明确禁止的动作

- 不因 430 条 direct false 直接删除“转化法”；
- 不因 70 条 direct true 直接保留“转化法”；
- 不把 mentor `llm_should_be` 当最终 replacement；
- 不只限制在构词法子树；
- 在 T1/T2 通过前不扫描或调用转化法的全量历史数据。

## 5. P0：词汇辨析（混合词性）

### 根因假设

老师定义要求“非复合单选，选项确实含不同词性的词汇/短语”。完整复核中只有 `whenever/whatever/...`、`another/more/other/others` 等少数题符合；复合题、完形和词性变化语法题被错误继承该标签。

### M1 基线诊断（mentor 500 条明细）

输入：`知识点_词汇_词汇辨析_词汇辨析（混合词性）.jsonl`，共 500 条；mentor direct verifier 给出 `true=217`、`false=283`。

| 切片 | true | false | 解读 |
|---|---:|---:|---|
| `child × 完形填空 × 语法选择` | 90 | 71 | CSV 明确排除，所有历史标签先 route quarantine |
| `child × 复合题 × 语法选择` | 70 | 46 | CSV 明确排除，所有历史标签先 route quarantine |
| `parent × 填空题 × 选词填空` | 4 | 10 | CSV 明确排除，先 route quarantine |
| `parent × 完形填空 × 完形填空` | 1 | 4 | CSV 明确排除，先 route quarantine |
| `parent × 单选题 × 选择题` | 52 | 131 | 唯一可进入“选项与语义”二次诊断的 route |
| 其他复合/阅读/判断 route | 0 | 21 | CSV 明确排除，先 route quarantine |

因此 direct true 中至少 `165/217 = 76.0%` 已被题型硬规则否定；这不是可用于评价语义判别能力的 true。过滤到老师允许的单选大题后，direct true 仅 `52/183 = 28.4%`，仍不能直接放行。

对这 52 条 true 的题面级快速形态统计：

- 16 条是纯 `how` 疑问词组（`how often/how long/...`）；完整人工样本已显示这类通常应归特殊疑问句，而非混合词性。
- 3 条是普通 `what/where/who/...` 疑问句；需与 `wh-ever` 分开，不能混用规则。
- 2 条全为 `wh-ever` 形式、3 条混有 `wh-ever`；完整人工样本中 `whenever/whatever/...` 可能是可保留边界，必须人工审。
- 28 条是其他混合候选，混有真实语义辨析（`another/more/other/others`、`other/else`、`alone/lonely` 等）以及明显语法主导的词性/数量/词形题（如 `succeed/success/successful/successfully`）。

在同一合法 route 的 131 条 false 中，模型建议的主要去向是：`how` 类特殊疑问句 33、固定搭配 24、同词性词汇辨析 21、连词辨析 12。这些仅是 tree / 人工复核的假设，不是自动替换标签。

### 实验 M1：先诊断，不做 tree 全量搜索

M1a 不应再随机抽 12 条 true。经过 route 过滤后只有 52 条 true，且定义边界是本标签的核心风险，应对**全部 52 条**进行盲审并记录：选项词性、实际解题依赖、是否为普通疑问句/连词/词形语法、以及 keep/remove/uncertain。这样可先冻结“普通 how”与“wh-ever”不应混用的可执行边界。

M1b 从 131 条同 route false 中按模型建议去向分层抽检，每个高频簇至多 12 条：

- `how` 类特殊疑问句；
- 固定搭配/句型；
- 同词性词汇辨析；
- 连词辨析。

人工抽样至少覆盖：

- 非复合单选、选项真的混合词性；
- 非复合单选、选项词性实际相同；
- 完形/复合小题；
- 词形变化、非谓语、比较级等语法主导题。

只有先确认“选项是否混合词性”这个前置事实，才决定是否使用 direct validator 或 tree。预计需要的规则不是“看到多个词性就保留”，而是“词汇/短语的语义辨析是否为必要解题依赖”。

验收：在这四类样本上，先把历史错标、题型污染和真实混合词性三类分开。只有 M1a 的某个**定义一致的细簇**达到 12/12 retain，才为该 `标签 × route × 选项模式` 建立 preliminary policy；全标签在此之前全部 hold。M1b 的 false 不因抽检正确就直接生成 patch，后续仍须走树候选和分簇复核。

#### M1 离线盲审包

M1 packet builder 已完成。它严格只保留 `parent × 单选题 × 选择题`：全量放入该 route 的 52 条 direct true，再从 direct false 的四个高频建议方向各稳定抽 12 条，共 100 条。reviewer-facing 包没有 `llm_match`、`llm_reason`、`llm_should_be` 和 `output_all`；这四个字段只留在 audit index，用于审核结束后对齐。

```bash
export MIXED_VERDICTS=/path/to/知识点_词汇_词汇辨析_词汇辨析（混合词性）.jsonl
export M1_DIR="$RUNTIME/low-quality-label-experiments/mixed-pos-m1-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$M1_DIR"

python3 scripts/build_mixed_pos_m1_review_packet.py \
  --input "$MIXED_VERDICTS" \
  --teacher-csv data/rulebooks/初中英语知识点题型方法释义.csv \
  --verify-label '知识点@词汇@词汇辨析@词汇辨析（混合词性）' \
  --blind-output "$M1_DIR/blind-review-100.jsonl" \
  --audit-index "$M1_DIR/audit-index.jsonl" \
  --report "$M1_DIR/packet.report.json" \
  --seed 'mixed-pos-m1-20260827'
```

交给人工或 Gemini 的只能是 `blind-review-100.jsonl`。每条应返回：

```json
{"review_id":"...","decision":"keep|remove|uncertain","reason":"一句话说明是否满足非复合单选、选项词性和实际解题依赖"}
```

不要把 `audit-index.jsonl` 同时发送给 reviewer；它会泄露原 DS 的 true/false 和 `should_be`，使 M1 失去盲审意义。收到 review 结果后，再将 `review_id` 与 audit index 对齐，按选项模式分簇决定是否做树搜索或建立 policy。

## 6. P1：介词（短语）辨析

老师定义明确限定为非复合单选、多个介词/介词短语选项的辨析。当前完整复核发现 DS 同时存在两类问题：

- 复合题小题因只看介词语义而被误判 true；
- `by 5 o'clock`、`provide ... with`、`help ... with` 等单选固定搭配因“还有其他考点”而被误判 false。

### 实验 P1：route 前置 + 共标提示对照

1. 先按最终 source 的 `parent × 单选题 × 选择题` 构造实验子集；其他 route 只进入 quarantine，不删标。
2. 使用明确允许“固定搭配义可与动词短语/情态等共标”的提示，运行 50--100 条对照小批。
3. 对新 prompt 的 true、false 各抽 12 条人审；false 不通过时只能保持 hold。
4. true 12/12 后，才允许该 route 构建全量 DS packet；全量 true 再独立抽 60 条。

## 7. P1：词汇（音/形/义）填空族

| 标签 | 初筛 signal | 已知判别器问题 | 实验重点 |
|---|---:|---|---|
| 介词（短语）的音/形/义 | 157/500 true | `at last`、`in the end`、`without` 等固定搭配被误删 | 明示“填空实际写出介词即应共标” |
| 副词（短语）的音/形/义 | 205/500 true | 固定副词短语被误删，单选副词辨析被误放行 | 填空与单选 route 对照 |
| 动词（短语）的音/形/义 | 194/500 true | 时态、动名词、搭配、翻译共标被误删；部分 true 题面不足 | 先输入完整性分流，再验证“写出动词”规则 |
| 名词（短语）的音/形/义 | 297/500 true | 完形、复数、固定搭配中的名词被误删 | 明示不以“是否唯一主考点”排除 |
| 形容词（短语）的音/形/义 | 211/500 true | 派生/固定搭配导致 false | 填空 route 下的共标提示 |

这一族优先做一个共享 prompt 对照实验，但每个末级标签仍单独计算 500 产量、true/false 人审和 policy；不能因为它们都叫“音/形/义”合并放行。

## 8. 已有可用数据与仍需警惕的问题

名词、副词、动词、形容词（短语）辨析已完成正例 12/12 校准，并已生成各自 `parent × 单选题 × 选择题` 的 DS 待验证 packet。它们不是“干净数据完成版”：四个标签合计还有 24,798 条历史记录因 route 与老师定义冲突而进入 quarantine，后续要等题型链路确认后处理。

它们当前的合法用途仅是：服务恢复后按标签独立跑 DS、从 true 产出 preliminary silver、再做每标签独立 60 条复核。它们的 false 和 route quarantine 都不自动删除。

## 9. 每次新增问题标签必须填写的字段

复制此模板追加到第 3 节之后：

```markdown
## Px：知识点@...

### 证据
- source / SHA：
- 初筛：true / total，error：
- 完整题面人工复核：true retain/remove/uncertain；false retain/remove/uncertain：
- 高风险 route：
- 信息完整性：文本 / 图片 / 音频：

### 根因假设
- 历史错标：
- 题型或父子污染：
- 判别器理解/提示词：
- taxonomy / 释义边界：

### 下一最小实验
- 目标：
- 输入分层和固定种子：
- 模型、prompt 版本、并发、预算：
- 人工审核样本与验收标准：

### 允许结论
- 可放行：
- 必须 hold：
- 禁止动作：
```

## 10. 当前执行顺序

1. 转化法 T1：先验证 whole-tree 是否能纠正“同形/派生/屈折/翻译”边界；
2. 混合词性 M1：先确认题型和选项词性，禁止全量；
3. 介词辨析 P1：route 预过滤后重新校准；
4. 音/形/义填空族：共享 prompt 对照、逐标签验收；
5. 其余低产量标签：按本模板补齐证据，进入对应支路。

任何一项实验未达到人工验收条件，都保留 audit 和 hold 证据，不能为了补量将其混入 `hq-v*`。
