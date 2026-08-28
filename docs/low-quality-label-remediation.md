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

### 3.1 P0 运行看板（26 个末级标签）

来源为 mentor 的标签准确率验证报告，数据源 `cleaned_final_enhanced_v2.jsonl`，每标签最多抽 500 条。**“根因”列只有写明“已证实”时才是结论；“待验证”只是下一实验的假设。**

状态定义：`已诊断-hold` = 已有足够证据否定直接清洗，但尚不能发布；`实验包就绪` = 可等 DS 服务恢复；`待离线分诊` = 不依赖 DS，下一步应先准备/交网页 GPT 审核；`未诊断` = 除初筛数字外尚无标签级结论。

| # | 标签 | DS 初筛 | 状态 | 已证实或待验证的根因 | 唯一下一实验 | 通过后才允许的下一步 |
|---:|---|---:|---|---|---|---|
| 1 | `知识点@语法词法@动词@实义动词@及物动词` | 33/500 | 已诊断-hold | 已证实：拼写题中自然出现宾语造成过标；DS false 也漏掉双宾语/宾补/被动等共标；7 个业务边界未冻结 | **V1 老师微规则裁决**：裁决第 5.5 节的 7 题 | 按已冻结结构簇做 tree/prompt 小批；不能全量删/留 |
| 2 | `知识点@语法词法@动词时态@现在进行时@现在进行时的肯否疑` | 47/500 | 已诊断-hold | 已证实：DS false 与网页 GPT 直审显著冲突；少量过去进行时/`be going to`/一般现在时混入；2 条老师边界未裁决 | **NP1**：老师裁决 2 题 + 36 条三 route 盲审 + 原/压缩释义 DS 对照（第 7.3 节） | 仅在新判别器和盲审方向一致后，收集 full true 再抽 60 条 |
| 3 | `知识点@语篇主题@人与社会@互联通讯` | 53/500 | 已诊断-hold | 强信号：电话/邮箱/电视/网站等关键词被误作“网络社交或信息传递”主题；大量阅读父题不是该主题 | **Theme-1**：403 条 remove 中分层构造 tree 纠错 60 条小包（第 8.3 节） | 仅输出 `relabel_candidate` / `uncovered`，再按候选叶子复核 |
| 4 | `知识点@语法句法@句子成分@谓语` | 60/500 | 已诊断-hold | 已证实：DS false 与网页 GPT 直审显著冲突；少量固定搭配/词义/其他成分混入；1 条老师边界未裁决 | **Predicate-1**：老师裁决 1 题 + 36 条三 route 盲审 + 原/压缩释义 DS 对照（第 8.3 节） | 仅在新判别器和盲审方向一致后，收集 full true 再抽 60 条 |
| 5 | `知识点@词汇@构词法@转化法` | 70/500 | 实验包就绪 | 已证实：派生、屈折、拼写和普通翻译被混入，不能只在构词法子树找答案 | **T1 whole-tree 60 条**（第 4.3 节；等待 DS） | 仅产生 `relabel_candidate`，按候选叶子×route 抽检 |
| 6 | `知识点@语法词法@动词时态@过去进行时@过去进行时的肯否疑` | 74/500 | 已诊断-hold | 已证实：DS false 与网页 GPT 直审显著冲突；唯一老师边界题未裁决 | **PP1**：老师裁决 1 题 + 36 条三 route 盲审 + 原/压缩释义 DS 对照（第 6.3 节） | 仅在新判别器和盲审方向一致后，收集 full true 再抽 60 条 |
| 7 | `知识点@语用@时间@顺序` | 19/127 | 已诊断-hold | 已证实：时间点、时长、`How soon` 等被误标为顺序；步骤/先后/日期推算是真正保留簇；25 条缺上下文 | **Order-1**：60 条 remove 全量 tree + 12 条 keep 回归控制（第 10.3 节） | 候选叶子/`uncovered` 分簇复核后才可生成 patch candidate |
| 8 | `知识点@语用@社会交往@争辩` | 57/365 | 已诊断-hold | 已证实：普通对话、偏好、请求建议、赞同或表面 No/but 被误标；真实反驳/投诉/否认辩解应保留；21 条缺上下文 | **Argument-1**：218 条 remove 按对话 route/言语行为分层 tree（第 11.3 节） | 候选叶子/`uncovered` 分簇复核后才可生成 patch candidate |
| 9 | `知识点@语用@社会交往@描述` | 93/500 | 待离线分诊 | 待验证：描述与介绍/评价/普通陈述混淆 | **Prag-Describe-0**：言语行为×对话完整性分层审核 | 决定语用释义补充或 hold |
| 10 | `知识点@语篇主题@人与社会@社会/政治/历史的变迁与发展` | 97/500 | 待离线分诊 | 待验证：父题主题与材料背景词共现被混淆 | **Theme-Change-0**：只审有完整篇章的父题；子题单列 quarantine | 父题主题簇才可做后续判别器校准 |
| 11 | `知识点@语法词法@动词时态@时态辨析@一般现在时与现在进行时的区别` | 98/500 | 待离线分诊 | 待验证：单一时态题被错带入“辨析” | **Tense-Contrast-0**：成对时态证据 vs 单一时态分层审核 | 定义“必须存在两种时态竞争”的 policy |
| 12 | `知识点@语法句法@句子成分@主语` | 104/500 | 待离线分诊 | 待验证：主语自然出现、主谓一致和句型题混入 | **Syntax-Subject-0**：按主语形式是否直接约束答案分层审核 | 决定共标规则或 route quarantine |
| 13 | `知识点@语用@存在@存在` | 106/500 | 待离线分诊 | 待验证：`there be` 语法与“存在”语用功能混淆 | **Prag-Existence-0**：`there be`、地点陈述、情景交际分层审核 | 决定语法/语用边界后再校准 |
| 14 | `知识点@语法词法@动词时态@一般将来时@一般将来时的肯否疑` | 117/500 | 待离线分诊 | 待验证：将来时间表达、计划/预测和一般将来时形式混杂 | **Tense-Future-0**：形式直接决定答案 vs 语义背景分层审核 | prompt/释义小批对照或 hold |
| 15 | `知识点@语法句法@简单句@主+系+表` | 127/500 | 待离线分诊 | 待验证：含系动词并不等于考查主系表句式 | **Syntax-SVC-0**：系动词、表语和句式判定题分层审核 | 形成“句式是否直接决定答案” policy |
| 16 | `知识点@语用@情感@厌烦` | 29/113 | 待离线分诊 | 待验证：情感词出现与说话人厌烦意图混淆 | **Prag-Boredom-0**：完整对话优先，缺上下文直接 hold | 稳定场景簇才可继续 |
| 17 | `知识点@语用@时间@时段` | 129/500 | 待离线分诊 | 待验证：时段字面信息与时间安排语用意图混淆 | **Prag-TimeSpan-0**：时间量/时段安排/普通背景分层审核 | 决定语用 trigger 或 hold |
| 18 | `知识点@语用@社会交往@介绍` | 132/500 | 待离线分诊 | 待验证：介绍、问候、描述身份等近邻意图混淆 | **Prag-Introduce-0**：对话首轮/人物介绍/普通陈述分层审核 | 稳定意图簇进入 prompt 对照 |
| 19 | `知识点@语法词法@动词时态@时态辨析@现在完成时与过去完成时的区别` | 36/134 | 待离线分诊 | 待验证：单一完成时题被错带入“辨析” | **Tense-Perfect-Contrast-0**：是否存在两个完成时竞争证据分层审核 | 定义时态辨析必要条件 |
| 20 | `知识点@语用@情感@责备` | 70/257 | 待离线分诊 | 待验证：责备、抱怨、建议和提醒近邻意图混淆 | **Prag-Blame-0**：完整对话的言语行为分层审核 | 稳定簇才做校准 |
| 21 | `知识点@语法词法@动词时态@一般过去时@一般过去时的肯否疑` | 137/500 | 待离线分诊 | 待验证：过去时间背景与过去时形式考查混杂 | **Tense-Past-0**：肯/否/疑形式直接决定答案 vs 背景分层审核 | prompt 对照或 hold |
| 22 | `知识点@语法词法@名词@集合名词` | 104/377 | 待离线分诊 | 待验证：普通复数/专有集合名词与集合名词语法一致混淆 | **Noun-Collective-0**：数、主谓一致和词义分类分层审核 | 形成集合名词必要条件 |
| 23 | `知识点@语法句法@并列句@含and并列复合句` | 142/500 | 待离线分诊 | 待验证：`and` 连接词出现与并列复合句结构考查混杂 | **Syntax-And-0**：真正两分句并列 vs 词组/谓语并列分层审核 | 共标 policy 或 hold |
| 24 | `知识点@语法词法@动词@实义动词@不及物动词` | 144/500 | 阻塞：等 V1 | 与及物动词共享“词汇出现 vs 结构约束”的业务边界 | **Intransitive-0**：仅在及物动词 V1 裁决后，用同一边界做成对诊断 | 不可先独立清洗，避免两标签规则相反 |
| 25 | `知识点@语法句法@简单句@主+谓+宾` | 148/500 | 待离线分诊 | 待验证：有宾语与考查 SVO 句式混杂 | **Syntax-SVO-0**：宾语填空/语序/句式判定分层审核 | 形成“结构直接决定答案” policy |
| 26 | `知识点@语用@特征@服饰` | 150/500 | 待离线分诊 | 待验证：服饰材料背景与描述服饰意图混淆 | **Prag-Clothing-0**：完整对话/图片依赖/普通阅读背景分层审核 | 图文完整簇再作校准 |

### 3.2 已检查标签的决策卡（先看这里）

| 标签 | 这次检查确认了什么问题 | 当前处置 | 现在要做的唯一动作 | 在什么条件下才能往下走 |
|---|---|---|---|---|
| 转化法 | 历史标签混入派生、屈折、拼写、普通翻译；错标题不一定属于构词法子树 | `hold` + `relabel_candidate` 实验 | 等 DS 恢复，跑 whole-tree T1 的 60 条 | 四种边界簇均无系统性方向错误，再按候选叶子分簇抽 12 条 |
| 及物动词 | 拼写/词形题的自然宾语造成过标；DS false 又漏掉双宾语、宾补、被动等真结构；存在 7 条老师口径边界 | `hold` | 先取得 7 条 V1 老师裁决 | 裁决写成 micro-policy 后，才可对对应结构簇做小批 tree/prompt |
| 过去进行时的肯否疑 | DS 的 false 大量与网页 GPT 的保留判断相反，不能将 low match 解释为历史错标；有 1 条老师冲突题 | `hold` | 先裁决 1 题，再跑 PP1 36 条 route 分层盲审和原/压缩释义对照 | 三主 route 的新 DS 判断与盲审方向一致，才可全量收集 true 并抽 60 条 |
| 现在进行时的肯否疑 | DS 的 false 大量与网页 GPT 的保留判断相反；少量相邻时态/用法标签混入；有 2 条老师冲突题 | `hold` | 先裁决 2 题，再跑 NP1 36 条 route 分层盲审和原/压缩释义对照 | 三主 route 的新 DS 判断与盲审方向一致，才可全量收集 true 并抽 60 条 |
| 谓语 | DS 的 false 大量与网页 GPT 的保留判断相反；单选中的固定搭配/词义/其他成分是主要异常；有 1 条老师冲突题 | `hold` | 先裁决 1 题，再跑 Predicate-1 三 route 盲审和原/压缩释义对照 | 三主 route 的新 DS 判断与盲审方向一致，才可全量收集 true 并抽 60 条 |
| 互联通讯 | 电话/邮箱/电视/网站等表面词汇被当作主题；主要污染在阅读父题 | `hold` + `relabel_candidate` 实验 | 构造 Theme-1：从网页 GPT remove 中按 route/题面完整性固定抽 60 条 tree 输入 | 候选叶子或 `uncovered` 按分簇复核通过后，才可扩大到同质簇 |
| 时间-顺序 | 时间点、时长、`How soon` 被误作顺序；真正顺序是步骤、先后、日期推算/历史事件；25 条缺听力或小题 | `hold` + `relabel_candidate` 实验 | Order-1：60 条 remove 全量 tree，外加 12 条 keep 回归控制 | 候选叶子/`uncovered` 分簇复核通过后，才可生成 patch candidate |
| 社会交往-争辩 | 普通对话、偏好、建议/请求、赞同或表面 No/but 被误标；真正反驳/投诉/否认辩解应保留；21 条缺上下文 | `hold` + `relabel_candidate` 实验 | Argument-1：按补全对话、选择、听力及言语行为分层 tree | 候选叶子/`uncovered` 分簇复核通过后，才可生成 patch candidate |

### 3.3 非 P0，但仍在处理的高风险标签

| 优先级 | 标签 / 问题簇 | 初筛信号 | 当前根因 | 当前状态 | 下一动作 |
|---|---|---|---|---|---|
| P1 | `知识点@词汇@词汇辨析@词汇辨析（混合词性）` | 217/500 true（43.4%）；完整复核 true 2/12 | 完形、复合题、词性变化和语法结构混入；“混合词性”边界不清 | 禁止 rollout；M1 盲审包已就绪 | 先做题型/选项词性诊断实验 |
| P1 | `知识点@语法词法@主谓一致@意义一致` | 原始初筛 325/500 true（65.0%）；完整复核 true 2/12、false 1/10 应留 | 普通形式一致、`there be`、`each` 等被混入意义一致；正例污染严重 | 禁止 rollout | 做“意义一致特例”边界诊断 |
| P1 | 结构共标簇：`语法一致`、`含but并列复合句` 等 | false 错判率高 | DS 将“不是唯一主考点”错误当作排除结构共标的理由 | 禁止用 false 清洗 | 做共标 prompt/规则对照；不抢占低匹配 P0 |
| P1 | `词汇（音/形/义）` 的介词、动词、名词、副词子类 | 介词 157/500、动词 194/500、副词 205/500 等 | DS 把“填空实际写出该词”压缩成唯一主考点；固定搭配、时态和语篇共标被漏掉 | 禁止 false 清洗 | 按“填空写词”业务规则做 prompt 对照实验 |
| P2 | `知识点@词汇@词汇辨析@介词（短语）辨析` | 404/500 true；完整复核 true 10/12、false 3/12 应留 | route 硬限制未前置，固定介词搭配有一定 false 漏删 | 未校准 | 题型链路确认后做 route 预过滤与重新校准 |
| P2 | `…@限制性定语从句@whom引导…`、`…@where引导…` | 正例复核仍有边界问题 | 非限制性、综合关系词和抽象地点先行词被误判 | 未校准 | 加反例的小批校准 |

### 3.4 样本不足的低匹配观察队列

以下知识点的初筛匹配率也不高，但总数小于 100；暂不列为 P0，等补足样本或与相邻标签合并诊断后再定：

- `知识点@语法句法@主从复合句@宾语从句@宾语从句的引导词@连接副词wh-ever/however引导宾语从句`：`9/48 = 18.8%`；
- `知识点@语用@存在@不存在`：`19/71 = 26.8%`。

### 3.5 `False 错判率`的计算口径

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

若本机只同步了 mentor 的两份全量文件（`sampled_for_verification.jsonl` 含题面、`verification_results.jsonl` 含判别结论），必须先用 `scripts/materialize_mentor_direct_verdicts.py` 按 `verify_label + question_id` 严格合并；它会拒绝重复或缺失配对，不能按行号猜测关联。合并输出才可作为下面的 tree correction 输入。

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

### 5.6 网页 GPT 原始文件直审：500 条问题筛查证据

为节省协作 token，网页 GPT 直接审核了 mentor 的完整 500 条原始 verifier JSONL。它可看见历史标签和 DS 字段，因此 `reviewer_mode=anchored_raw_source_review`，不是独立盲审。Codex 已以 `question_id + parent_id` 校验：500 条输入、500 条返回、无重复、无未知题号、无空理由，结果被规范化为：

```text
english-knowledge-tagger-runtime/low-quality-labels/transitive-verb-t0-20260828-v4/
├─ web-gpt-raw-review-evidence.jsonl    # 500 条可审计 reviewer evidence
└─ web-gpt-raw-review-analysis.json
```

| 来源切片 | keep | remove | uncertain | 解释 |
|---|---:|---:|---:|---|
| 网页 GPT 全部 500 条 | 81 | 391 | 28 | 问题筛查，不可直接删/留 |
| mentor direct `match` 33 条 | 17 | 15 | 1 | DS true 也有明显不纯 |
| mentor direct `mismatch` 467 条 | 64 | 376 | 27 | DS false 有大量结构漏删，但不能外推为全量错误率 |
| mentor `false + should_be=正确` 11 条 | 0 | 4 | 7 | 再次证明这批字段冲突应保持 hold |

当前网页 GPT 的强信号是：单词拼写 route 仅 `6 keep / 203 remove`，而单选 route 为 `44 keep / 66 remove`、完成句子为 `14 keep / 69 remove`。这支持“拼写题中自然出现宾语”是主要过标簇，但它仍需老师确认是否与 CSV 业务口径一致。

与既有 24 条独立校准相比，网页 GPT 在 `20/24` 条上同结论；另有 4 条“旧校准 keep、网页 GPT remove”：`avoid doing`、`trust someone`、连词成句 `take the medicine`、`feed chickens and pigs`。四条都落在“动宾/非谓语结构是否必须直接决定空格答案”的同一严格度分歧，不能把网页 GPT 的 remove 自动覆盖旧结论。

因此本标签最终状态不变：`hold`。网页 GPT 原始直审可作为下一轮 route/结构分簇和老师边界裁决的输入；它既不产出 `released_silver`，也不产出自动删除 patch。

## 6. P0：过去进行时的肯否疑

### 6.1 事实画像与产物

目标历史标签为 `知识点@语法词法@动词时态@过去进行时@过去进行时的肯否疑`；当前启用 taxonomy 路径仍需由 migration 映射为 `知识点->词法->动词时态->过去进行时->过去进行时的肯否疑`。输入为 mentor 的 500 条 direct-verifier 明细：

```text
english-knowledge-tagger-runtime/知识点_语法词法_动词时态_过去进行时_过去进行时的肯否疑.jsonl
```

mentor 初筛为 `74/500 match`（14.8%），因此它进入 P0；但这只表示当前判别器的产量，不是历史标签有 85.2% 错标。网页 GPT 以原始文件直审模式完成 500 条审核，Codex 已按 `question_id + parent_id` 对齐全部输入和输出。原始回传中一行题面双引号未转义；用户补发同一题的完整 JSON 后才通过校验，两个版本都保留在会话附件中，规范化证据不修改 source：

```text
english-knowledge-tagger-runtime/web-gpt-reviews/
└─ past-progressive-affirmative-negative-question-20260828/
   ├─ evidence.jsonl
   └─ summary.json
```

| 证据切片 | keep | remove | uncertain | 解读 |
|---|---:|---:|---:|---|
| 网页 GPT 全部 500 条 | 479 | 1 | 20 | 原始直审证据，不能直接发布 silver |
| mentor direct `match` 74 条 | 73 | 0 | 1 | DS true 基本被网页 GPT 保留 |
| mentor direct `mismatch` 426 条 | 406 | 1 | 19 | DS false 与网页 GPT 的当前业务理解严重背离 |
| `parent × 单选题 × 选择题` | 179 | 1 | 0 | 当前最大、最完整的可校准 route |
| `parent × 填空题 × 单词拼写` | 155 | 0 | 0 | 不可因“拼写题”自动排除；题目仍可能直接考查过去进行时形式 |
| `parent × 填空题 × 完成句子` | 62 | 0 | 0 | 可作为时态形式校准的第二 route |
| 复合题/情景运用等 | 0 | 0 | 19 uncertain | 题面/上下文不足，暂不用于放大 |

### 6.2 当前根因与处理结论

网页 GPT 的标签级结论为 `hold`，并把 `3105096983930556416` 列为唯一老师裁决题：它存在主谓结构与当前老师释义的正面冲突。这里的关键根因不是已证实的历史大规模错标，而是**当前 DS 判别器把过去进行时的形式考查误判为不匹配**：在其 `mismatch` 集中，网页 GPT 仍保留 `406/426`。该结果来自可见历史字段的原始直审，不能单独证明网页 GPT 正确；但足以否定“按 DS false 清洗”这条路径。

因此本标签归入通用闭环中的“低 match、false 多数应留”分支：先修订判别器对定义/题面格式的理解并小批复测，而不是启动知识点树广搜，也不以 `llm_should_be` 生成 replacement。

### 6.3 下一最小实验与门禁

1. 老师先裁决 `3105096983930556416`，将结论写为该标签的 micro-policy；未裁决前该题及同类冲突 route 均为 `hold`。
2. 以 `parent × 单选题 × 选择题`、`parent × 填空题 × 单词拼写`、`parent × 填空题 × 完成句子` 各固定抽取 12 条，构成 36 条不含历史标签/DS 字段的盲审校准包；网页 GPT 只判断标签适用性，不再重审这 500 条原始结果。
3. 依据盲审与老师裁决，做一个受控的 DS prompt/释义表达对照：同一 36 条、同一温度和候选集合，比较“原释义”与“明确 `was/were + V-ing` 的肯定/否定/疑问结构，且该结构直接决定答案”的压缩释义。记录每 route 的 keep/reject/uncertain 及请求耗时。
4. 只有三个主 route 均达到预先约定的人审一致性，且 DS 与盲审方向一致，才允许把该**判别器版本**用于该标签全量 `match=true` 收集；全量 true 仍须独立抽 60 条复核才能成为 `released_silver`。

明确禁止：用现有 426 条 DS false 批量删标；因网页 GPT 479 keep 直接发布全量历史题；将 20 条 `uncertain` 强行改为 keep/remove；在未验证判别器前运行 tree replacement。

## 7. P0：现在进行时的肯否疑

### 7.1 事实画像与可审计证据

目标标签为 `知识点@语法词法@动词时态@现在进行时@现在进行时的肯否疑`，当前启用路径应迁移为 `知识点->词法->动词时态->现在进行时->现在进行时的肯否疑`。网页 GPT 对 mentor 500 条 direct-verifier 明细完成原始直审，并已通过 `500/500` 的 `question_id + parent_id` 对齐：

```text
english-knowledge-tagger-runtime/知识点_语法词法_动词时态_现在进行时_现在进行时的肯否疑.jsonl
english-knowledge-tagger-runtime/web-gpt-reviews/
└─ present-progressive-affirmative-negative-question-20260828/
   ├─ evidence.jsonl
   └─ summary.json
```

| 证据切片 | keep | remove | uncertain | 解读 |
|---|---:|---:|---:|---|
| 网页 GPT 全部 500 条 | 478 | 7 | 15 | 标签级结论为 `hold`，不是可直接发布的 silver |
| mentor direct `match` 47 条 | 46 | 0 | 1 | DS true 基本被保留 |
| mentor direct `mismatch` 453 条 | 432 | 7 | 14 | DS false 与网页 GPT 的当前业务理解显著背离 |
| `parent × 单选题 × 选择题` | 198 | 3 | 2 | 最大完整 route，可作主要校准切片 |
| `parent × 填空题 × 单词拼写` | 177 | 0 | 0 | 不能因拼写 route 自动排除；形式可能直接决定作答 |
| `parent × 填空题 × 完成句子` | 45 | 0 | 0 | 第二个形式考查校准切片 |
| 复合题小题/情景运用等 | 0 | 0 | 13 | 上下文不足，继续 hold |

### 7.2 根因、处理结论与禁止动作

当前证据指向**判别器对时态形式标签的系统性漏判**，而不是已证实的大规模历史错标：网页 GPT 认为 `am/is/are + V-ing` 的肯定、否定、一般/特殊疑问及答语直接约束答案；7 条 remove 是相邻时态（过去进行时、`be going to`、一般现在时）或纯用法知识混入。网页 GPT 指定 `3125582210285723648`、`2139891546877726720` 为老师边界题。

处置为 `hold`。禁止：用现有 453 条 DS false 批量删标；因网页 GPT 478 keep 直接放行历史全量；把 15 条 uncertain 强制改判；未校准判别器前运行 tree replacement。

### 7.3 NP1：形式标签判别器校准

NP1 是唯一下一实验：

1. 老师先裁决两个边界题，并把结果写成该标签 micro-policy；同类题在裁决前均为 hold。
2. 从 `parent × 单选题 × 选择题`、`parent × 填空题 × 单词拼写`、`parent × 填空题 × 完成句子` 各以固定种子抽 12 条，建立 36 条**不含历史标签和 DS 字段**的盲审包。
3. DS 恢复后，在同一 36 条、同一候选集合和温度下比较原释义与压缩释义：`am/is/are + V-ing 的肯定、否定、一般疑问、特殊疑问或答语结构，且该结构直接决定答案`；输出每 route 的判断、uncertain 和请求耗时。
4. 三个 route 均达到预先约定的人审一致性、且新 DS 与盲审方向一致，才允许用该版本判别器收集全量 true；full true 仍必须独立抽 60 条复核才可 `released_silver`。

## 8. P0：谓语

### 8.1 事实画像与可审计证据

目标标签为 `知识点@语法句法@句子成分@谓语`，当前启用路径应迁移为 `知识点->句法->句子成分->谓语`。网页 GPT 对 mentor 500 条 direct-verifier 明细完成原始直审，并通过 `500/500` 的 `question_id + parent_id` 对齐：

```text
english-knowledge-tagger-runtime/知识点_语法句法_句子成分_谓语.jsonl
english-knowledge-tagger-runtime/web-gpt-reviews/predicate-20260828/
├─ evidence.jsonl
└─ summary.json
```

| 证据切片 | keep | remove | uncertain | 解读 |
|---|---:|---:|---:|---|
| 网页 GPT 全部 500 条 | 454 | 29 | 17 | 标签级结论为 `hold`，不是可直接发布的 silver |
| mentor direct `match` 60 条 | 58 | 1 | 1 | DS true 基本被保留 |
| mentor direct `mismatch` 440 条 | 396 | 28 | 16 | DS false 与网页 GPT 的当前业务理解显著背离 |
| `parent × 单选题 × 选择题` | 52 | 24 | 0 | remove 的主要集中簇；需判断是否真考谓语而非词义/搭配/其他成分 |
| `parent × 填空题 × 完成句子` | 242 | 1 | 1 | 最大稳定形式/成分判断 route |
| `child × 复合题 × 语法选择` | 23 | 0 | 0 | 当前样本均被保留，需独立于父题 route 校准 |
| `child × 完形填空 × 语法选择` | 20 | 0 | 0 | 当前样本均被保留，需独立于父题 route 校准 |

### 8.2 根因、处理结论与禁止动作

当前证据指向**判别器把谓语形式、时态、助动词、情态和被动结构错误当作“不是谓语考点”**。但 29 条 remove 表明该标签也有真实异常：固定搭配、纯词义以及其他句子成分题不能因句中存在动词就共标“谓语”。网页 GPT 指定 `2785362399957475328` 为老师边界题。

处置为 `hold`。禁止：用 440 条 DS false 批量删标；因 454 条 keep 直接发布全量；在未校准“谓语形式是否直接约束答案”的判别器前运行 tree replacement；把缺具体小题的 17 条 uncertain 强制改判。

### 8.3 Predicate-1：谓语成分/形式判别器校准

1. 老师先裁决 `2785362399957475328` 并写入 micro-policy。
2. 从 `parent × 单选题 × 选择题`、`parent × 填空题 × 完成句子`、`child × 复合题 × 语法选择` 各以固定种子抽 12 条，形成 36 条不含历史标签/DS 字段的盲审包；完形小题暂不混入，以免和语法选择 route 混淆。
3. DS 恢复后，对同一 36 条比较原释义和压缩释义：`题目要求识别谓语成分，或谓语位置/时态/助动词/情态/被动形式直接决定答案；仅出现动词或固定搭配不够`。记录每 route 的判断、uncertain 与耗时。
4. 三个 route 的新 DS 判断与盲审方向一致后，才可收集此标签全量 true；full true 仍需独立抽 60 条才可 `released_silver`。

## 9. P0：互联通讯

### 9.1 事实画像与可审计证据

目标标签为 `知识点@语篇主题@人与社会@互联通讯`，老师释义要求文章/对话**围绕**网络社交、信息传递、线上沟通、数字交流、社交媒体或通讯工具展开；单独出现电话、邮箱、电视或网站不充分。mentor 的 500 条 direct-verifier 明细和网页 GPT 原始直审产物如下：

```text
english-knowledge-tagger-runtime/知识点_语篇主题_人与社会_互联通讯.jsonl
english-knowledge-tagger-runtime/web-gpt-reviews/internet-communication-20260828/
├─ evidence.jsonl
└─ summary.json
```

网页 GPT 原始直审已通过 `500/500` 的 `question_id + parent_id` 对齐校验。它看得到历史标签和 DS 字段，故仍只是 `anchored_raw_source_review` evidence，不能直接改 source。

| 证据切片 | keep | remove | uncertain | 解释 |
|---|---:|---:|---:|---|
| 网页 GPT 全部 500 条 | 71 | 403 | 26 | 标签级结论为 `p0_remediation` |
| mentor direct `match` 53 条 | 45 | 7 | 1 | DS true 仍有关键词误判 |
| mentor direct `mismatch` 447 条 | 26 | 396 | 25 | 多数与网页 GPT 的 remove 同向，但不可直接作为删除 patch |
| `parent × 复合题 × 阅读理解` | 34 | 322 | 24 | 最大污染簇；大量父题只是材料中出现通讯相关物品 |
| `parent × 主观题 × 书面表达` | 8 | 18 | 0 | 需与阅读父题分开，不可共享规则 |
| `parent × 补全题 × 阅读还原` | 7 | 2 | 0 | 数量小且保留率高，不并入阅读父题污染簇 |

### 9.2 根因、处理结论与禁止动作

当前强证据支持“**主题词触发过宽**”：题目仅出现电话、邮箱、电视或网站，不能推出材料主题是互联通讯；而真正围绕在线交流/信息传递/通讯工具的题应保留。26 条 `uncertain` 都由题面或篇章上下文不足导致，不能被强行归入 remove。

因此处置为 `hold + p0_remediation`：先探索 403 条 remove 的合理去向或无覆盖状态，再对同质候选簇复核。禁止：

- 把 403 条网页 GPT remove 或 396 条 DS false 直接从历史标签删除；
- 因 71 条 keep 直接发布该标签的 silver；
- 把阅读父题全部 route quarantine；完整篇章且主题明确的父题仍可能保留该标签；
- 强迫每个 remove 题获得 replacement；允许 tree 返回 `uncovered`。

### 9.3 Theme-1：树纠错可用性小批

Theme-1 是本标签唯一下一实验；先离线构造任务包，等 DS 恢复后运行。输入从已校验的网页 GPT 证据中以固定种子分层抽 60 条：

- 30 条 `parent × 复合题 × 阅读理解 × remove`，其中至少 12 条篇章完整、12 条篇章不完整；
- 10 条其他阅读/任务型阅读 `remove`；
- 10 条书面表达、完形、听力等非阅读 `remove`，检验 route 是否改变去向；
- 10 条 `keep` 作为回归控制，确保 tree 不系统性离开互联通讯。

tree 根使用 active taxonomy 全树；每题只能得到一个 terminal leaf、`uncovered` 或 `budget_exhausted`。首轮固定 `max_steps=8`、`max_backtracks=2`、`concurrency=16`，并写 timing report。验收时网页 GPT/人工只审核三件事：

1. `keep` 控制题是否仍回到互联通讯；
2. 被移出的题的候选叶子是否真实解释材料主题；
3. `uncovered` 是否合理，而不是被强行塞到错误主题。

只有某个 `原互联通讯 × tree_candidate/uncovered × route × 上下文完整性` 簇达到独立 12 条复核的预定标准，才能生成 `patch_candidate`；任何不稳定簇继续 `hold`。

## 10. P0：时间-顺序

### 10.1 事实画像与可审计证据

目标标签为 `知识点@语用@时间@顺序`。该标签仅有 127 条 mentor direct-verifier 明细，但满足 P0 的总数门槛；网页 GPT 原始直审已通过 `127/127` 的 `question_id + parent_id` 对齐：

```text
english-knowledge-tagger-runtime/知识点_语用_时间_顺序.jsonl
english-knowledge-tagger-runtime/web-gpt-reviews/time-order-20260828/
├─ evidence.jsonl
└─ summary.json
```

| 证据切片 | keep | remove | uncertain | 解读 |
|---|---:|---:|---:|---|
| 网页 GPT 全部 127 条 | 42 | 60 | 25 | 标签级结论为 `p0_remediation` |
| mentor direct `match` 19 条 | 18 | 0 | 1 | true 基本是有效顺序题 |
| mentor direct `mismatch` 108 条 | 24 | 60 | 24 | DS false 中仍有真实顺序题，不能用作删除名单 |
| `parent × 单选题 × 选择题` | 5 | 31 | 0 | 最大可处理 remove 簇：时间点/时长等常被误标 |
| `parent × 单选题 × 听力单选` | 23 | 16 | 11 | 需先区分有文本解析与缺听力原文 |
| `child × 复合题 × 听力单选` | 6 | 8 | 0 | 可与听力父题分开验证，不直接继承规则 |
| 复合题父题/听力复合题 | 0 | 0 | 14 | 信息不足，保持 hold |

### 10.2 根因、处理结论与禁止动作

已确认的正例边界是 `first/then/finally`、`before/after`、步骤先后、星期/日期推算与历史事件顺序；单纯问日期、时长、时间点、`How soon` 不构成“顺序”。两个老师边界题为 `2805318653360246784`、`3318252241126518784`。25 条 `uncertain` 因听力原文、具体小题或图片缺失，不能人工猜测补标。

处置为 `hold + p0_remediation`。禁止：直接删除 60 条网页 GPT remove；直接保留 42 条 keep；将 25 条信息不足题送入 tree；把听力父题和小题合并为同一 route policy。

### 10.3 Order-1：小样本 tree 去向验证

本标签的下一实验不需要再抽 remove：127 条总量小，直接使用全部 60 条已审 remove；再按固定种子抽 12 条 keep 作为回归控制，共 72 条任务。先离线生成任务包，DS 恢复后运行 whole-tree，参数固定 `max_steps=8`、`max_backtracks=2`、`concurrency=16`，并记录每节点和总请求耗时。

输入分层必须保留：

- 31 条 `parent × 单选题 × 选择题 × remove`；
- 16 条 `parent × 单选题 × 听力单选 × remove`；
- 8 条 `child × 复合题 × 听力单选 × remove`；
- 其余可读 remove；
- 12 条 keep 回归控制。

验收：keep 控制题不应系统性离开“时间-顺序”；remove 的候选叶子必须真实解释题目，或合理返回 `uncovered`；缺上下文题不参与评判。候选按 `tree_candidate/uncovered × route × 音频文本状态` 分簇，每簇独立 12 条复核通过才形成 `patch_candidate`。

## 11. P0：社会交往-争辩

### 11.1 事实画像与可审计证据

目标标签为 `知识点@语用@社会交往@争辩`。网页 GPT 对 mentor 的 365 条 direct-verifier 明细完成原始直审，已通过 `365/365` 的 `question_id + parent_id` 对齐：

```text
english-knowledge-tagger-runtime/知识点_语用_社会交往_争辩.jsonl
english-knowledge-tagger-runtime/web-gpt-reviews/social-argument-20260828/
├─ evidence.jsonl
└─ summary.json
```

| 证据切片 | keep | remove | uncertain | 解读 |
|---|---:|---:|---:|---|
| 网页 GPT 全部 365 条 | 126 | 218 | 21 | 标签级结论为 `p0_remediation` |
| mentor direct `match` 57 条 | 53 | 4 | 0 | DS true 基本有效，但仍有少量误触发 |
| mentor direct `mismatch` 308 条 | 73 | 214 | 21 | false 中仍有真实争辩，不能直接删 |
| `parent × 填空题 × 补全对话` | 30 | 162 | 0 | 最大污染簇：普通交际被混入争辩 |
| `parent × 单选题 × 选择题` | 37 | 2 | 0 | 相对稳定的保留簇 |
| `child × 复合题 × 补全对话` | 1 | 19 | 0 | 子题不可沿用父题规则 |
| 听力复合父题 | 0 | 0 | 14 | 缺听力/小题内容，保持 hold |

### 11.2 根因、处理结论与禁止动作

有效边界是不同意、质疑、反驳、投诉或对指责的否认/辩解；个人偏好、普通问答、请求建议、赞同以及只含 `No`/`but` 的表面词不构成争辩。老师边界题为 `2821211074106068992`。当前处置为 `hold + p0_remediation`。

禁止：直接删除 218 条网页 GPT remove 或 214 条 DS false；把 126 条 keep 直接发布；以“补全对话”作为自动保留/自动删除的硬规则；让缺听力或小题的 21 条进入 tree。

### 11.3 Argument-1：言语行为 tree 去向验证

先离线从 218 条 remove 按固定种子抽 60 条，再抽 12 条 keep 作为回归控制。60 条至少覆盖：30 条 `parent × 填空题 × 补全对话`、10 条子题补全对话/其他复合题、10 条听力或选择、10 条其他可读 route。DS 恢复后以 active taxonomy 全树运行，固定 `max_steps=8`、`max_backtracks=2`、`concurrency=16`，保留 timing report。

验收重点：keep 控制题不能系统性离开争辩；remove 的候选是否是更准确言语行为或合理 `uncovered`；父/子题、听力文本状态不能混淆。每个 `tree_candidate/uncovered × route × 言语行为` 簇独立复核 12 条通过后才形成 `patch_candidate`。

## 12. P1：词汇辨析（混合词性）

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

## 13. P2：介词（短语）辨析

老师定义明确限定为非复合单选、多个介词/介词短语选项的辨析。当前完整复核发现 DS 同时存在两类问题：

- 复合题小题因只看介词语义而被误判 true；
- `by 5 o'clock`、`provide ... with`、`help ... with` 等单选固定搭配因“还有其他考点”而被误判 false。

### 实验 P2：route 前置 + 共标提示对照

1. 先按最终 source 的 `parent × 单选题 × 选择题` 构造实验子集；其他 route 只进入 quarantine，不删标。
2. 使用明确允许“固定搭配义可与动词短语/情态等共标”的提示，运行 50--100 条对照小批。
3. 对新 prompt 的 true、false 各抽 12 条人审；false 不通过时只能保持 hold。
4. true 12/12 后，才允许该 route 构建全量 DS packet；全量 true 再独立抽 60 条。

## 14. P1：词汇（音/形/义）填空族

| 标签 | 初筛 signal | 已知判别器问题 | 实验重点 |
|---|---:|---|---|
| 介词（短语）的音/形/义 | 157/500 true | `at last`、`in the end`、`without` 等固定搭配被误删 | 明示“填空实际写出介词即应共标” |
| 副词（短语）的音/形/义 | 205/500 true | 固定副词短语被误删，单选副词辨析被误放行 | 填空与单选 route 对照 |
| 动词（短语）的音/形/义 | 194/500 true | 时态、动名词、搭配、翻译共标被误删；部分 true 题面不足 | 先输入完整性分流，再验证“写出动词”规则 |
| 名词（短语）的音/形/义 | 297/500 true | 完形、复数、固定搭配中的名词被误删 | 明示不以“是否唯一主考点”排除 |
| 形容词（短语）的音/形/义 | 211/500 true | 派生/固定搭配导致 false | 填空 route 下的共标提示 |

这一族优先做一个共享 prompt 对照实验，但每个末级标签仍单独计算 500 产量、true/false 人审和 policy；不能因为它们都叫“音/形/义”合并放行。

## 15. 已有可用数据与仍需警惕的问题

名词、副词、动词、形容词（短语）辨析已完成正例 12/12 校准，并已生成各自 `parent × 单选题 × 选择题` 的 DS 待验证 packet。它们不是“干净数据完成版”：四个标签合计还有 24,798 条历史记录因 route 与老师定义冲突而进入 quarantine，后续要等题型链路确认后处理。

它们当前的合法用途仅是：服务恢复后按标签独立跑 DS、从 true 产出 preliminary silver、再做每标签独立 60 条复核。它们的 false 和 route quarantine 都不自动删除。

## 16. 每次新增问题标签必须填写的字段

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

## 17. 当前执行顺序

1. **互联通讯 / Theme-1**：现在离线构造 60 条 tree 任务包；DS 恢复后运行并按候选叶子/`uncovered` 分簇复核。这是当前最靠前、无需等待老师才能准备的 P0。
2. **时间-顺序 / Order-1**：现在离线构造 `60 remove + 12 keep` 的 tree 任务包；DS 恢复后按候选叶子/`uncovered` 与音频文本状态分簇复核。
3. **社会交往-争辩 / Argument-1**：现在离线构造 `60 remove + 12 keep` 的 tree 任务包；DS 恢复后按候选言语行为/`uncovered` 与父子题 route 分簇复核。
4. **现在进行时的肯否疑 / NP1**：向老师提交 `3125582210285723648`、`2139891546877726720`；裁决后构造 36 条盲审包，DS 恢复后做原/压缩释义对照。
5. **谓语 / Predicate-1**：向老师提交 `2785362399957475328`；裁决后构造 36 条盲审包，DS 恢复后做原/压缩释义对照。
6. **及物动词 / V1**：向老师提交第 5.5 节的 7 条边界题；收到裁决前不生成任何清洗 patch。
7. **过去进行时的肯否疑 / PP1**：向老师提交 `3105096983930556416`；裁决后先构造 36 条盲审包，DS 恢复后再做原/压缩释义对照。
8. **转化法 / T1**：实验包已就绪；DS 恢复后运行 60 条 whole-tree，检查“同形/派生/屈折/翻译”四个边界簇。
9. **其余 P0**：严格按第 3.1 节顺序，每次只启动一个 `*-0` 离线分诊；完成一个标签的“根因 + 唯一下一实验 + 门禁”后才开下一个。
10. **混合词性 M1**：已有盲审包，可与上述离线分诊并行；仍禁止全量。
11. **介词辨析 P2 与音/形/义填空族 P1**：只在对应 P0 不阻塞时运行 route / prompt 对照；每个末级标签单独验收。

任何一项实验未达到人工验收条件，都保留 audit 和 hold 证据，不能为了补量将其混入 `hq-v*`。
