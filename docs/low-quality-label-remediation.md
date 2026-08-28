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

### 2.3 按原始 DS 匹配率的四档分流

原始匹配率只衡量 mentor 判别器在“历史带该标签的题”中的 `match / total` 产量；它不等于 `match=true` 的人工准确率。因此先按产量划档，再用人工审核决定是否晋级。所有档位均要求题面满足当前老师释义的 route 限制、文本/图片/音频信息可用；不满足时一律 `route_quarantine` 或 `hold`。

| 档位 | 原始匹配率 | 目标 | 进入条件 | 允许动作 | 禁止动作 |
|---|---:|---|---|---|---|
| A：优质快车道 | `>= 70%` | 快速收集高质量正例 | direct true 独立人工抽 12 条，`12/12 keep` | 对该标签的全量数据包运行同一判别器；只收集 full true；从 full true 独立再抽 60 条，`60/60` 才标为 `released_silver` | 用 full false 删除、替换或覆盖历史标签 |
| B：条件晋级 | `50%–<70%` | 验证能否稳定收集 silver | 首 12 条 true `12/12 keep` 后，再按主要 `route × 信息完整性` 分层独立抽 24 条 true，`24/24 keep` | 通过后可对**该标签全量数据包**运行判别器，并沿用 full true 的 60 条独立复核门禁 | 仅凭首 12 条或原始匹配率直接全量；把 false 当脏数据删除 |
| C：分簇挽救 | `>30%–<50%` | 找到局部可用的高纯度子簇 | 先在 500 条明细中按 `route × 题面完整性 × 相邻标签/选项模式` 分簇；某个子簇的 true 独立抽 12 条 `12/12 keep` | 只对通过的**子簇**构造全量判别包，full true 仍须独立 60 条复核；其余子簇保持 hold | 对整标签全量运行；将低产量直接视为历史错标率 |
| D：P0 根因修复 | `<=30%` | 找出低产量的明确根因，并纠正剩余题的去向 | 先完成 500 条 `true/false × route × 题面完整性 × 相邻标签` 分诊，并提出可检验根因 | 小批 tree 广搜、定义/prompt 对照、route 隔离；只生成 `relabel_candidate` / `hold` | 直接全量；将 direct false 直接清空；默认相信 `should_be` |

说明：`70%`、`50%`、`30%` 是当前的**资源分配阈值**，不是统计上的“正确/错误”分界线。12 条和 24 条只用于决定是否值得放大；最终可训练的 `released_silver` 必须经过全量 true 后重新独立抽取的 60 条复核。若 60 条中出现任一错标，则停止该标签或子簇的发布，回到根因诊断。

## 3. 当前问题标签队列

P0 的含义已统一为“**最优先诊断的低匹配率知识点标签**”，不是“可直接清洗的标签”。它只由 mentor 的原始 500 条 DS 初筛决定：

```text
P0 准入 = 知识点末级标签 ∧ 初筛总数 >= 100 ∧ 原始 DS 匹配率 <= 30%
```

这里的匹配率是 `match / total`，不是完整样本台账刻意构造的 `12 true + 12 false` 的 50%。`true`/`false` 人工复核、`False 错判率`和 route 限制只决定后续采用树广搜、改判别器、route 隔离还是 hold，**不改变本表的 P0 排序**。每个 P0 都必须先做 500 条明细的根因诊断；低匹配率本身不能授权删除或替换任何历史标签。

### 3.1 P0 全量诊断队列（26 个知识点标签）

来源为 mentor 的标签准确率验证报告，数据源 `cleaned_final_enhanced_v2.jsonl`，每标签最多抽 500 条。按原始匹配率升序排列。

| 顺序 | 标签 | 原始 DS 匹配 | 匹配率 | 当前状态 / 最小下一步 |
|---:|---|---:|---:|---|
| 1 | `知识点@语法词法@动词@实义动词@及物动词` | 33/500 | 6.6% | 下一个处理：提取 500 条明细，先做 true/false × route × 题面完整性分诊 |
| 2 | `知识点@语法词法@动词时态@现在进行时@现在进行时的肯否疑` | 47/500 | 9.4% | 待准备明细与时态边界诊断包 |
| 3 | `知识点@语篇主题@人与社会@互联通讯` | 53/500 | 10.6% | 待准备主题语义边界与父/子题 route 诊断包 |
| 4 | `知识点@语法句法@句子成分@谓语` | 60/500 | 12.0% | 待准备句子成分共标/唯一主考点诊断包 |
| 5 | `知识点@词汇@构词法@转化法` | 70/500 | 14.0% | T1 whole-tree 小批 packet 已就绪，等待 DS 恢复 |
| 6 | `知识点@语法词法@动词时态@过去进行时@过去进行时的肯否疑` | 74/500 | 14.8% | 待准备明细与时态边界诊断包 |
| 7 | `知识点@语用@时间@顺序` | 19/127 | 15.0% | 待准备语用意图与题面信息完整性诊断包 |
| 8 | `知识点@语用@社会交往@争辩` | 57/365 | 15.6% | 待准备语用场景边界诊断包 |
| 9 | `知识点@语用@社会交往@描述` | 93/500 | 18.6% | 待准备语用场景边界诊断包 |
| 10 | `知识点@语篇主题@人与社会@社会/政治/历史的变迁与发展` | 97/500 | 19.4% | 待准备主题语义边界与父/子题 route 诊断包 |
| 11 | `知识点@语法词法@动词时态@时态辨析@一般现在时与现在进行时的区别` | 98/500 | 19.6% | 待准备“时态辨析 vs 单一时态”诊断包 |
| 12 | `知识点@语法句法@句子成分@主语` | 104/500 | 20.8% | 待准备句子成分共标/唯一主考点诊断包 |
| 13 | `知识点@语用@存在@存在` | 106/500 | 21.2% | 待准备语用功能与普通陈述句混入诊断包 |
| 14 | `知识点@语法词法@动词时态@一般将来时@一般将来时的肯否疑` | 117/500 | 23.4% | 待准备时态边界诊断包 |
| 15 | `知识点@语法句法@简单句@主+系+表` | 127/500 | 25.4% | 待准备句式共标/唯一主考点诊断包 |
| 16 | `知识点@语用@情感@厌烦` | 29/113 | 25.7% | 待准备语用场景边界诊断包 |
| 17 | `知识点@语用@时间@时段` | 129/500 | 25.8% | 待准备语用时间含义与普通时间表达诊断包 |
| 18 | `知识点@语用@社会交往@介绍` | 132/500 | 26.4% | 待准备语用场景边界诊断包 |
| 19 | `知识点@语法词法@动词时态@时态辨析@现在完成时与过去完成时的区别` | 36/134 | 26.9% | 待准备“时态辨析 vs 单一时态”诊断包 |
| 20 | `知识点@语用@情感@责备` | 70/257 | 27.2% | 待准备语用场景边界诊断包 |
| 21 | `知识点@语法词法@动词时态@一般过去时@一般过去时的肯否疑` | 137/500 | 27.4% | 待准备时态边界诊断包 |
| 22 | `知识点@语法词法@名词@集合名词` | 104/377 | 27.6% | 待准备集合名词/普通复数名词边界诊断包 |
| 23 | `知识点@语法句法@并列句@含and并列复合句` | 142/500 | 28.4% | 待准备并列结构共标/唯一主考点诊断包 |
| 24 | `知识点@语法词法@动词@实义动词@不及物动词` | 144/500 | 28.8% | 与及物动词成对诊断；待及物动词规则稳定后处理 |
| 25 | `知识点@语法句法@简单句@主+谓+宾` | 148/500 | 29.6% | 待准备句式共标/唯一主考点诊断包 |
| 26 | `知识点@语用@特征@服饰` | 150/500 | 30.0% | 待准备语用场景边界诊断包 |

### 3.2 非 P0，但仍在处理的高风险标签

| 优先级 | 标签 / 问题簇 | 初筛信号 | 当前根因 | 当前状态 | 下一动作 |
|---|---|---|---|---|---|
| P1 | `知识点@词汇@词汇辨析@词汇辨析（混合词性）` | 217/500 true（43.4%）；完整复核 true 2/12 | 完形、复合题、词性变化和语法结构混入；“混合词性”边界不清 | 禁止 rollout；M1 盲审包已就绪 | 先做题型/选项词性诊断实验 |
| P1 | `知识点@语法词法@主谓一致@意义一致` | 原始初筛 325/500 true（65.0%）；完整复核 true 2/12、false 1/10 应留 | 普通形式一致、`there be`、`each` 等被混入意义一致；正例污染严重 | 禁止 rollout | 做“意义一致特例”边界诊断 |
| P1 | 结构共标簇：`语法一致`、`含but并列复合句` 等 | false 错判率高 | DS 将“不是唯一主考点”错误当作排除结构共标的理由 | 禁止用 false 清洗 | 做共标 prompt/规则对照；不抢占低匹配 P0 |
| P1 | `词汇（音/形/义）` 的介词、动词、名词、副词子类 | 介词 157/500、动词 194/500、副词 205/500 等 | DS 把“填空实际写出该词”压缩成唯一主考点；固定搭配、时态和语篇共标被漏掉 | 禁止 false 清洗 | 按“填空写词”业务规则做 prompt 对照实验 |
| P2 | `知识点@词汇@词汇辨析@介词（短语）辨析` | 404/500 true；完整复核 true 10/12、false 3/12 应留 | route 硬限制未前置，固定介词搭配有一定 false 漏删 | 未校准 | 题型链路确认后做 route 预过滤与重新校准 |
| P2 | `…@限制性定语从句@whom引导…`、`…@where引导…` | 正例复核仍有边界问题 | 非限制性、综合关系词和抽象地点先行词被误判 | 未校准 | 加反例的小批校准 |

### 3.3 样本不足的低匹配观察队列

以下知识点的初筛匹配率也不高，但总数小于 100；暂不列为 P0，等补足样本或与相邻标签合并诊断后再定：

- `知识点@语法句法@主从复合句@宾语从句@宾语从句的引导词@连接副词wh-ever/however引导宾语从句`：`9/48 = 18.8%`；
- `知识点@语用@存在@不存在`：`19/71 = 26.8%`。

### 3.4 `False 错判率`的计算口径

完整样本台账中的 24 条不是自然随机的模型输出分布：每个标签刻意抽取 12 条 direct true 和 12 条 direct false。因此表中的 `DS 匹配率 12/24 = 50%` 是**抽样构成**，不能用于比较标签的真实 match 产量。

对某标签的 12 条 direct false，人工逐条给出 `retain`、`remove` 或 `uncertain`。台账中的 false 错判率定义为：

```text
False 错判率
= 人工判为 retain 的 direct-false 条数
  / (12 条 direct-false - 人工判为 uncertain 的条数)
```

它的含义是“**模型已经输出 false 的条件下，模型把本应保留标签误删的比例**”；它不是历史错标率、不是 false 在全量中的比例，也不是模型的总体准确率。

示例：

| 标签 | 人工 false 结果 | 错判率 | 解释 |
|---|---|---:|---|
| 固定搭配/句型 | retain 4、remove 4、uncertain 4 | `4 / (12-4) = 4/8 = 50%` | 4 条信息不足不能当对或错，故从分母排除 |
| `if/whether` 引导宾语从句 | retain 6、remove 0、uncertain 6 | `6 / (12-6) = 6/6 = 100%` | 6 条可判 false 全部是 DS 漏删，不代表全体数据 100% 错 |
| 介词（短语）辨析 | retain 3、remove 9、uncertain 0 | `3/12 = 25%` | 有一定漏删，但并非当前 P0 |
| 混合词性 | retain 0、remove 12、uncertain 0 | `0/12 = 0%` | DS false 在该抽样中可靠；本标签的核心问题在 DS true 与历史正例污染 |

因此优先级必须同时看：历史 500 条的真实产量、true 采样准确率、false 错判率的**可判分母**、uncertain 比例和数据量。`1/3` 与 `12/12` 都可能显示 33%/100%，但证据强度完全不同。

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

## 5. P0：及物动词

### 5.1 事实画像

输入是 mentor 对该精确末级标签的 500 条 direct-verifier 明细：

```text
知识点@语法词法@动词@实义动词@及物动词
输入：english-knowledge-tagger-runtime/知识点_语法词法_动词_实义动词_及物动词.jsonl
```

该文件的历史渲染路径 `知识点@语法词法@动词@实义动词@及物动词` 必须先经版本化 migration `legacy-grammar-wording-to-morphology` 映射为当前启用路径 `知识点->词法->动词->实义动词->及物动词`。两种路径都会保存在审计产物中；不能因路径名称不同把它计为语义错标。

| 项目 | 数量 | 解释 |
|---|---:|---|
| `llm_match=true` | 33 | 原始匹配率 `33/500 = 6.6%`；不是 33 条已经确认的 silver |
| `llm_match=false` | 467 | 不能批量删除；其中包含信息不足和共标遗漏风险 |
| 可进入后续 tree 任务 | 483 | `33` 条 direct true recheck + `450` 条 direct mismatch |
| `direct_contract_conflict` | 11 | `llm_match=false`，但 `llm_should_be=正确`；其 `llm_reason` 实际又说明“不符合”，字段自相矛盾 |
| `direct_insufficient` | 6 | 只有题型说明、词表或缺具体句子，无法判断 |
| 音频 / 整题图片 | 0 / 0 | 本批的低匹配率不是多模态信息缺失导致 |

三个主要 route 占 `404/500 = 80.8%`，但都只有约 6%--8% 的 direct true，说明问题不是一个 route 的偶发录入错误，而是历史标签在多个常见题型中被系统性扩大：

| route | true / total | 原始匹配率 |
|---|---:|---:|
| `parent × 填空题 × 单词拼写` | 14 / 209 | 6.7% |
| `parent × 单选题 × 选择题` | 9 / 112 | 8.0% |
| `parent × 填空题 × 完成句子` | 5 / 83 | 6.0% |

`output_all` 中最常与该标签共现的是固定搭配/句型（85）、一般现在时定义/判定（73）、`do/does/did` 作助动词（68）、情态动词基本用法（49）和一般疑问句（43）。这只是历史共标分布，**不能**证明这些共标本身错误；但它解释了为什么“句中出现及物动词”不能作为保留规则。

初步 tree 分流产物如下，未调用任何模型、未改源数据：

```text
english-knowledge-tagger-runtime/low-quality-labels/transitive-verb-t0-20260827/
├─ tree-tasks.jsonl          483 条
├─ hold.jsonl                 17 条
└─ tree-tasks.report.json
```

T0 盲审 packet 使用 migration 后的 active taxonomy，并和 tree 分流独立保存：

```text
english-knowledge-tagger-runtime/low-quality-labels/transitive-verb-t0-20260828-v4/
├─ true-blind-review-33.jsonl    # 所有 direct true；供独立人工/Gemini 审核
├─ false-blind-review-60.jsonl   # 固定分层 false；供独立人工/Gemini 审核
├─ review-audit-index.jsonl      # 仅供审核完成后回连 DS 结果，不能给 reviewer
└─ review-packets.report.json
```

### 5.2 当前可执行定义

沿用 CSV 和已有 24 条独立复核的共同边界，而不是把“题目里出现及物动词”当作依据：

**可保留候选**必须有可观察的结构约束，即答案或句型判断依赖于以下至少一项：

- 及物与不及物的对比，如 `raise/rise`、`hear/listen (to)`、`reach/arrive`、`run out/run out of`；
- 直接宾语或宾格的选择实际受谓语及物性约束；
- 双宾语、宾语补足语，如 `show sb sth`、`give sb sth`、`make + 宾语 + 补足语`；
- 被动结构以动词可带宾语为必要前提，如 `be influenced by`。

**应删除或 hold** 的典型情形：

- 只考时态、三单、助动词、拼写、词义，而宾语只是已给出的自然上下文；
- 固定搭配中虽有动词和宾语，但宾语结构没有参与答案选择；
- 题面只有题型标题、词表或空白，无法恢复具体句子。

已有 24 条独立复核显示：direct true 的抽样 `12/12` 可保留；direct false 中 `make + 宾语 + 宾补` 与被动 `be influenced by` 两条应保留，故 false 错判率为 `2/12 = 16.7%`。这足以禁止“false 直接删除”，但不足以保证剩余 21 条 direct true 全部都符合上述更严格边界。

### 5.3 根因判断（当前阶段）

1. **历史过标是主问题。** 6.6% 的 raw match 在单词拼写、单选、完成句子三大 route 上同时出现，符合“把所有含及物动词的题都继承标签”的模式。
2. **direct true 仍有边界污染风险。** 33 条数量很小，应全部盲审；其中既有明确的 `raise/rise`、`show sb sth`、`hear/listen`，也有仅在单词拼写题中自然出现 `hide the truth`、`trust someone` 等直接宾语的候选，不能只抽 12 条就全量放行。
3. **direct false 的主要风险是结构共标漏删。** 现有反例已覆盖宾语补足语和被动；后续还需检查双宾语、宾格选择和及/不及物对比。固定搭配、时态和拼写类 false 不能被默认视为“安全删除”，只能作为分层审核的来源。
4. **判别器输出契约有独立问题。** 11 条 `false + 正确` 的矛盾记录必须保持 `hold`，不得根据 `llm_should_be` 创建 replacement，也不得计入 false 准确率。

### 5.4 T0：先完成可人工验收的盲审，不跑全量

T0-A 对 33 条 direct true **全部**盲审，审稿人只看清洗后的题面和当前老师释义，不看 `llm_match`、历史 `output_all`、`llm_reason` 或 `llm_should_be`。每条返回：

```json
{"review_id":"...","decision":"keep|remove|uncertain","reason":"及物性是否实际约束答案；若是，指出直接宾语/双宾语/宾补/被动/及不及物对比"}
```

T0-B 从 450 条直接 false 中按 `route × 模型建议族` 抽取固定的 60 条盲审，并强制包含已有人工复核中确认的两条 DS false 漏删：`2624065286149791744`（`make + 宾语 + 宾补`）和 `2797969086460768256`（被动结构）。其余样本覆盖：

- 时态/三单/助动词主考但有直接宾语；
- 固定搭配；
- 宾格选择；
- 双宾语与宾语补足语；
- 被动结构；
- 及物/不及物动词或短语对比；
- 单词拼写、完成句子、单选三大 route。

可复跑 packet 的命令如下。盲审文件会删除 `llm_match`、`llm_reason`、`llm_should_be`、`output_all` 和 source line；这些字段只保留在 audit index，避免 reviewer 被 DS 结论锚定。

```bash
python3 scripts/build_p0_direct_diagnosis_packets.py \
  --input "$MENTOR_LABEL_JSONL" \
  --verify-label '知识点@语法词法@动词@实义动词@及物动词' \
  --teacher-csv data/rulebooks/初中英语知识点题型方法释义.csv \
  --taxonomy-migration configs/knowledge_taxonomy_migrations/legacy-rendered-to-teacher-v1.json \
  --true-output "$RUN/true-blind-review-33.jsonl" \
  --false-output "$RUN/false-blind-review-60.jsonl" \
  --audit-output "$RUN/review-audit-index.jsonl" \
  --report "$RUN/review-packets.report.json" \
  --false-sample-size 60 \
  --false-boundary-question-id 2624065286149791744 \
  --false-boundary-question-id 2797969086460768256 \
  --seed 'transitive-verb-t0-20260828'
```

T0 的决策规则：

- 33 条 true 全部通过，才可将这 33 条登记为 `silver_label_candidate`，并为其定义一致的细簇准备后续补量实验；该标签的历史总体仍维持 P0，不能因此构造全标签 silver 包。任一 true 错误则先按错误模式拆分。
- false 的审核只决定哪些结构簇可进入 tree 小批；即使 60 条全为 remove，也不直接删除其余 false。
- 11 条 contract conflict 和 6 条信息不足始终维持 `hold`，等待题面补全或 mentor 判别器解析修复。

DS 服务恢复后，tree 只对 T0-B 中人工确认“原标签不适用且题面足够”的小簇运行；其结果仅为 `relabel_candidate`。通过人工复核前，禁止替换历史及物动词标签。

### 5.5 T0 盲审结果：保持 P0，不得全量 rollout

已收齐 `93/93` 个 review result，`review_id` 与 true packet、false packet、audit index 完整一一对应，无重复、无未知 ID。结果和可复跑的机器可读报告如下：

```text
english-knowledge-tagger-runtime/low-quality-labels/transitive-verb-t0-20260828-v4/
├─ reviewer-results.jsonl
└─ review-analysis.json
```

| 审核集合 | keep | remove | uncertain | 可判样本 | 可判 keep 比率 | 结论 |
|---|---:|---:|---:|---:|---:|---|
| 33 条 direct true（全量） | 24 | 9 | 0 | 33 | 72.7% | true 自身已不纯，禁止将全标签 direct true 作为 silver |
| 60 条 direct false（刻意分层） | 14 | 38 | 8 | 52 | 26.9% | false 中确有结构共标漏删；该比例仅描述本分层 packet，不得外推到 467 条 false |

true 侧最明显的错误模式是“单词拼写题中自然出现直接宾语”：`parent × 填空题 × 单词拼写` 为 `6 keep / 8 remove`。相对地，本轮 `parent × 单选题 × 选择题` 是 `9/9 keep`，`parent × 填空题 × 完成句子` 是 `4/5 keep`；但样本数小，二者只是后续分簇假设，**不是**立即放行的 policy。

false 侧保留的强结构包括双宾语（`offer sb sth`）、宾语补足语（`make sb do`、`hear sb doing`）、被动（`be influenced by`）、及/不及物对比（`read/look`、`achieve/come true`）和宾格选择。它证明 direct verifier 把“存在更具体标签”错误理解为互斥，但并不证明任何一个历史 false 记录应被保留。

#### 已发现的 policy 冲突与二次裁决集

已有 24 条校准记录中，`2763348356975136768`（`trust someone`）和 `2506263048647131136`（`feed chickens and pigs`）先前被判为保留，本轮盲审判为删除。两题都是“词汇/拼写或时态为直接作答目标，直接宾语只是已给上下文”的边界。当前工作台采用的严格口径应倾向删除，但不能静默覆盖较早结论；应把它们与下面边界题一起交给业务老师裁决并冻结 micro-policy。

| 题号 | 当前盲审结论 | 需要裁决的原因 |
|---:|---|---|
| `2763348356975136768` | remove | `trust someone` 的直接宾语是否足以让单词拼写题共标及物动词 |
| `2506263048647131136` | remove | `feed chickens and pigs` 的三单/拼写题是否应因直接宾语共标 |
| `3120750759128346624` | keep | `take the orange to him` 同样是拼写/三单题，和前两题的严格口径冲突 |
| `2735187241526140930` | keep | `operate on` 是“介词动词短语可被动”的业务分类；需确认是否纳入本末级“及物动词” |
| `2141810373476298752` | keep | `get` 表“到达”在无宾语时的归类，与标准及物/不及物分析存在歧义 |
| `2765880206472548352` | keep | `claim + that` 宾语从句是否属于 CSV 中及物动词宾语范围 |
| `2768597858236551168` | keep | 连词成句中的 `guess + 宾语从句` 是否算“及物性实际约束答案” |

在这 7 条得到业务裁决前：

- 33 条 direct true 中的 24 条仅可登记为 `silver_label_candidate`，不可发布；
- 14 条 false keep 中，只有已由独立旧校准和本轮同时支持的 `make + 宾补`、`be influenced by` 可作为 tree / prompt 的正向边界例；
- `operate on`、裸 `get`、宾语从句宾语与“拼写题自然宾语”均不得写成自动化 keep/remove 规则；
- 所有 direct false 的 `remove` 仍然只是 `hold`，不可批量删标。

## 6. P1：词汇辨析（混合词性）

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

## 7. P2：介词（短语）辨析

老师定义明确限定为非复合单选、多个介词/介词短语选项的辨析。当前完整复核发现 DS 同时存在两类问题：

- 复合题小题因只看介词语义而被误判 true；
- `by 5 o'clock`、`provide ... with`、`help ... with` 等单选固定搭配因“还有其他考点”而被误判 false。

### 实验 P2：route 前置 + 共标提示对照

1. 先按最终 source 的 `parent × 单选题 × 选择题` 构造实验子集；其他 route 只进入 quarantine，不删标。
2. 使用明确允许“固定搭配义可与动词短语/情态等共标”的提示，运行 50--100 条对照小批。
3. 对新 prompt 的 true、false 各抽 12 条人审；false 不通过时只能保持 hold。
4. true 12/12 后，才允许该 route 构建全量 DS packet；全量 true 再独立抽 60 条。

## 8. P1：词汇（音/形/义）填空族

| 标签 | 初筛 signal | 已知判别器问题 | 实验重点 |
|---|---:|---|---|
| 介词（短语）的音/形/义 | 157/500 true | `at last`、`in the end`、`without` 等固定搭配被误删 | 明示“填空实际写出介词即应共标” |
| 副词（短语）的音/形/义 | 205/500 true | 固定副词短语被误删，单选副词辨析被误放行 | 填空与单选 route 对照 |
| 动词（短语）的音/形/义 | 194/500 true | 时态、动名词、搭配、翻译共标被误删；部分 true 题面不足 | 先输入完整性分流，再验证“写出动词”规则 |
| 名词（短语）的音/形/义 | 297/500 true | 完形、复数、固定搭配中的名词被误删 | 明示不以“是否唯一主考点”排除 |
| 形容词（短语）的音/形/义 | 211/500 true | 派生/固定搭配导致 false | 填空 route 下的共标提示 |

这一族优先做一个共享 prompt 对照实验，但每个末级标签仍单独计算 500 产量、true/false 人审和 policy；不能因为它们都叫“音/形/义”合并放行。

## 9. 已有可用数据与仍需警惕的问题

名词、副词、动词、形容词（短语）辨析已完成正例 12/12 校准，并已生成各自 `parent × 单选题 × 选择题` 的 DS 待验证 packet。它们不是“干净数据完成版”：四个标签合计还有 24,798 条历史记录因 route 与老师定义冲突而进入 quarantine，后续要等题型链路确认后处理。

它们当前的合法用途仅是：服务恢复后按标签独立跑 DS、从 true 产出 preliminary silver、再做每标签独立 60 条复核。它们的 false 和 route quarantine 都不自动删除。

## 10. 每次新增问题标签必须填写的字段

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

## 11. 当前执行顺序

1. 转化法 T1：实验包已就绪；DS 恢复后直接验证 whole-tree 是否能纠正“同形/派生/屈折/翻译”边界；
2. 及物动词：已完成 500 条 `true/false × route × 题面完整性` 分诊；先执行 T0-A 全量 true 盲审和 T0-B 分层 false 盲审，再决定 tree 小批；
3. 其余 P0：严格按第 3.1 节的原始匹配率顺序准备明细、定义和最小诊断实验；同类标签可共用实验骨架，但不得合并结论；
4. 混合词性 M1：已具备盲审包，作为 P1 并行诊断，禁止全量；
5. 介词辨析 P2 与音/形/义填空族 P1：在对应 P0 诊断不受阻时，再做 route / prompt 对照并逐标签验收。

任何一项实验未达到人工验收条件，都保留 audit 和 hold 证据，不能为了补量将其混入 `hq-v*`。
