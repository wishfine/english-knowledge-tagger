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
| 3 | `知识点@语篇主题@人与社会@互联通讯` | 53/500 | 已诊断-hold | tree 在社交媒体/线上分享主题上候选不稳定：Theme-1 仅 `31 correct / 18 incorrect / 11 hold` | **Theme-Policy-0**：老师裁决 10 条“线上分享是主线还是背景”边界题 | micro-policy 冻结后再设计非 tree 主题分流对照；不得进 T2 |
| 4 | `知识点@语法句法@句子成分@谓语` | 60/500 | 已诊断-hold | 已证实：DS false 与网页 GPT 直审显著冲突；少量固定搭配/词义/其他成分混入；1 条老师边界未裁决 | **Predicate-1**：老师裁决 1 题 + 36 条三 route 盲审 + 原/压缩释义 DS 对照（第 8.3 节） | 仅在新判别器和盲审方向一致后，收集 full true 再抽 60 条 |
| 5 | `知识点@词汇@构词法@转化法` | 70/500 | 已诊断-hold | 已证实：派生、屈折、拼写和普通翻译被混入；T1 tree 末级负向约束无法修复派生误判且会改变控制题路径 | **Conv-Policy-0**：用 v1 micro-policy 验证“词形是否不变”人工/规则字段；`334...` 单题仍独立裁决 | 非 tree 分流字段在独立样本稳定后，才可另开定向重标实验 |
| 6 | `知识点@语法词法@动词时态@过去进行时@过去进行时的肯否疑` | 74/500 | 已诊断-hold | 已证实：DS false 与网页 GPT 直审显著冲突；唯一老师边界题未裁决 | **PP1**：老师裁决 1 题 + 36 条三 route 盲审 + 原/压缩释义 DS 对照（第 6.3 节） | 仅在新判别器和盲审方向一致后，收集 full true 再抽 60 条 |
| 7 | `知识点@语用@时间@顺序` | 19/127 | 已诊断-hold | 已证实：时间点、时长、`How soon` 等被误标为顺序；步骤/先后/日期推算是真正保留簇；25 条缺上下文 | **Order-1**：60 条 remove 全量 tree + 12 条 keep 回归控制（第 10.3 节） | 候选叶子/`uncovered` 分簇复核后才可生成 patch candidate |
| 8 | `知识点@语用@社会交往@争辩` | 57/365 | 已诊断-hold | 已证实：普通对话、偏好、请求建议、赞同或表面 No/but 被误标；真实反驳/投诉/否认辩解应保留；21 条缺上下文 | **Argument-1**：218 条 remove 按对话 route/言语行为分层 tree（第 11.3 节） | 候选叶子/`uncovered` 分簇复核后才可生成 patch candidate |
| 9 | `知识点@语用@社会交往@描述` | 93/500 | 已诊断-hold | 已证实：部分普通问答/词义或固定回应被误标；81 条因缺具体小题、听力原文或图片不确定 | **Description-1**：41 条 remove 按 route/信息完整性做 tree 去向，12 条 keep 回归控制（第 12.3 节） | 候选叶子/`uncovered` 分簇复核后才可生成 patch candidate |
| 10 | `知识点@语篇主题@人与社会@社会/政治/历史的变迁与发展` | 97/500 | 已诊断-hold | 已证实：个人经历、一般成长/旅行/助人故事、普通交际和虚构故事被误标；4 条材料缺失 | **Historical-Change-1**：307 条 remove 按 route/篇章完整性 tree 60 条，12 条 keep 回归控制（第 13.3 节） | 候选叶子/`uncovered` 分簇复核后才可生成 patch candidate |
| 11 | `知识点@语法词法@动词时态@时态辨析@一般现在时与现在进行时的区别` | 98/500 | 已诊断-hold | 已证实：DS false 中大量是有效的现在/进行时形式或用法题；另有被动、将来时、固定短语、写作等异常；5 条老师边界未裁决 | **Tense-Contrast-1**：老师裁决 5 题 + 按根因分层的 60 条 remove/12 条 keep 盲审（第 14.3 节） | 先冻结“单一时态形式是否仍归本标签”的业务口径，再按簇做 prompt/tree；不能直接删/留 |
| 12 | `知识点@语法句法@句子成分@主语` | 104/500 | 已诊断-hold | 已证实：普通连词成句、完成句子、翻译、词汇、被动和主谓一致任务把主语当作分析背景继承；12 条信息缺失 | **Subject-1**：353 条 remove 按 route/结构分层 tree 60 条，12 条 keep 回归控制（第 15.3 节） | 候选叶子/`uncovered` 分簇复核后才可生成 patch candidate |
| 13 | `知识点@语用@存在@存在` | 106/500 | 已诊断-hold | 已证实：have/has 所属关系、普通位置/词汇信息、其他听力内容或背景 there be 被误标；117 条缺小题/音频/图片 | **Existence-1**：244 条可读 remove 按 route/存在表达分层 tree 60 条，12 条 keep 回归控制（第 16.3 节） | 候选叶子/`uncovered` 分簇复核后才可生成 patch candidate |
| 14 | `知识点@语法词法@动词时态@一般将来时@一般将来时的肯否疑` | 117/500 | 已诊断-hold | 已证实：DS false 中大量是有效将来时形式/肯否疑题；书面表达、将来进行/完成、主将从现、固定短语/词汇混入；2 条老师边界未裁决 | **Future-1**：老师裁决 2 题 + 36 条 route 分层盲审与原/压缩释义 DS 对照（第 17.3 节） | 新判别器与盲审一致后才可收集 full true；真实 remove 簇另开 tree |
| 15 | `知识点@语法句法@简单句@主+系+表` | 127/500 | 已诊断-hold | 已证实：DS false 中大量是有效主系表/表语位置题；纯词义/级别辨析、there be、写作、其他成分和固定表达混入；17 条信息缺失 | **SVC-1**：36 条 route 分层盲审与原/压缩释义 DS 对照；真实 remove 簇后续 tree（第 18.3 节） | 新判别器与盲审一致后才可收集 full true；remove 簇另开 tree |
| 16 | `知识点@语用@情感@厌烦` | 29/113 | 已诊断-P0 remediation | 已证实：普通不喜欢、不开心、生气、身体疲劳、难度评价及无关信息题被混入；真正强烈厌烦表达可保留；16 条缺上下文 | **Prag-Boredom-1**：61 条 remove 按完整对话/听力子题/其他 route 分层，36 条 keep 做回归控制（第 24.3 节） | 新判别器与独立盲审一致后，才可生成 patch candidate；缺上下文继续 hold |
| 17 | `知识点@语用@时间@时段` | 129/500 | 已诊断-hold | 已证实：When/How long/How soon、日期星期、for/since、in+时间段和 take/spend 等均在老师定义内；误标集中于活动/地点/主题/交通方式/纯时态，另有 156 条材料不足或来源冲突 | **Prag-TimeSpan-1**：先补齐听力及复合题材料，再对可读 remove 与 keep 做分层盲审（第 25.3 节） | 材料完整且 route 方向稳定后，才可生成 patch candidate；不确定记录继续 hold |
| 18 | `知识点@语用@社会交往@介绍` | 132/500 | 已诊断-hold | 已证实：完整题面中的姓名身份、家庭关系、外貌、兴趣、学校生活、地点、数量和文化常识均符合定义；175 条因缺少具体小题、答案或音频材料不确定 | **Prag-Introduce-1**：先补齐复合题/听力材料，再对完整题面做正例回归（第 26.3 节） | 材料完整且独立抽检通过后，才可进入 silver；不确定记录继续 hold |
| 19 | `知识点@语法词法@动词时态@时态辨析@现在完成时与过去完成时的区别` | 36/134 | 已诊断-P0 remediation | 已证实：完成时辨析标签混入将来完成/完成进行、其他语法小题、写作及篇章背景；27 条删除候选、17 条材料或定义冲突不确定；1 条 mentor verdict 不可用 | **Tense-Perfect-Contrast-1**：老师裁决 3 条边界题 + 27 条 remove 分层与 12 条 keep 控制（第 27.3 节） | 边界冻结且独立盲审通过后，才可生成 patch candidate；不确定记录继续 hold |
| 20 | `知识点@语用@情感@责备` | 70/257 | 已诊断-P0 remediation | 已证实：普通生气、建议、地点人物等听力细节、语法造句和剧本背景被混入；真正责备/批评/谴责及道歉改正回应可保留；51 条材料不足 | **Prag-Blame-1**：109 条 remove 按言语行为/route 分层抽取，97 条 keep 做控制（第 28.3 节） | 独立盲审与 DS 方向一致后，才可生成 patch candidate；51 条不确定继续 hold |
| 21 | `知识点@语法词法@动词时态@一般过去时@一般过去时的肯否疑` | 137/500 | 已诊断-hold | 已证实：463 条直接考查过去时肯定、did/didn’t 否定疑问或 was/were；8 条混入情态/现在时/完成时或纯阅读；29 条材料、时间参照或来源冲突不确定 | **Tense-Past-1**：老师裁决 1 条边界题 + 8 条 remove 与 12 条 keep 小批复核（第 29.3 节） | 边界与来源规则冻结后，才可收集 full true 并独立抽 60 条；不确定记录继续 hold |
| 22 | `知识点@语法词法@名词@集合名词` | 104/377 | 已完成离线初诊-hold | 已证实：必须是集合名词作主语且整体/成员意义直接决定谓语单复数；普通复数、`sheep`、不可数 `hair/furniture`、`staff` 作宾语及姓氏复数被混入 | **Noun-Collective-1**：按合法题型与主谓一致触发分层复核（第 30.3 节） | 分层复核与全量方向一致、再独立抽 60 条后，才可生成 patch candidate |
| 23 | `知识点@语法句法@并列句@含and并列复合句` | 142/500 | 待离线分诊 | 待验证：`and` 连接词出现与并列复合句结构考查混杂 | **Syntax-And-0**：真正两分句并列 vs 词组/谓语并列分层审核 | 共标 policy 或 hold |
| 24 | `知识点@语法词法@动词@实义动词@不及物动词` | 144/500 | 阻塞：等 V1 | 与及物动词共享“词汇出现 vs 结构约束”的业务边界 | **Intransitive-0**：仅在及物动词 V1 裁决后，用同一边界做成对诊断 | 不可先独立清洗，避免两标签规则相反 |
| 25 | `知识点@语法句法@简单句@主+谓+宾` | 148/500 | 待离线分诊 | 待验证：有宾语与考查 SVO 句式混杂 | **Syntax-SVO-0**：宾语填空/语序/句式判定分层审核 | 形成“结构直接决定答案” policy |
| 26 | `知识点@语用@特征@服饰` | 150/500 | 待离线分诊 | 待验证：服饰材料背景与描述服饰意图混淆 | **Prag-Clothing-0**：完整对话/图片依赖/普通阅读背景分层审核 | 图文完整簇再作校准 |

### 3.2 已检查标签的决策卡（先看这里）

| 标签 | 这次检查确认了什么问题 | 当前处置 | 现在要做的唯一动作 | 在什么条件下才能往下走 |
|---|---|---|---|---|
| 转化法 | 历史标签混入派生、屈折、拼写、普通翻译；tree 对派生误判无方向性修复，且控制题发生退化 | `hold` | 用 conversion-vs-derivation-v1 验证“词形是否不变”字段；`334...` 继续独立裁决 | 该字段在独立样本稳定后，才可另开非 tree 的定向重标实验 |
| 及物动词 | 拼写/词形题的自然宾语造成过标；DS false 又漏掉双宾语、宾补、被动等真结构；存在 7 条老师口径边界 | `hold` | 先取得 7 条 V1 老师裁决 | 裁决写成 micro-policy 后，才可对对应结构簇做小批 tree/prompt |
| 过去进行时的肯否疑 | DS 的 false 大量与网页 GPT 的保留判断相反，不能将 low match 解释为历史错标；有 1 条老师冲突题 | `hold` | 先裁决 1 题，再跑 PP1 36 条 route 分层盲审和原/压缩释义对照 | 三主 route 的新 DS 判断与盲审方向一致，才可全量收集 true 并抽 60 条 |
| 现在进行时的肯否疑 | DS 的 false 大量与网页 GPT 的保留判断相反；少量相邻时态/用法标签混入；有 2 条老师冲突题 | `hold` | 先裁决 2 题，再跑 NP1 36 条 route 分层盲审和原/压缩释义对照 | 三主 route 的新 DS 判断与盲审方向一致，才可全量收集 true 并抽 60 条 |
| 谓语 | DS 的 false 大量与网页 GPT 的保留判断相反；单选中的固定搭配/词义/其他成分是主要异常；有 1 条老师冲突题 | `hold` | 先裁决 1 题，再跑 Predicate-1 三 route 盲审和原/压缩释义对照 | 三主 route 的新 DS 判断与盲审方向一致，才可全量收集 true 并抽 60 条 |
| 互联通讯 | 电话/邮箱/电视/网站等表面词汇被当作主题；tree 对社交媒体/线上分享主题竞争不稳定 | `hold` | Theme-1 已审核：31 correct、18 incorrect、11 hold；先裁决 10 条主题边界 | 主题 micro-policy 冻结后再做非 tree 分流对照；不能进 T2 |
| 时间-顺序 | 时间点、时长、`How soon` 被误作顺序；真正顺序是步骤、先后、日期推算/历史事件；25 条缺听力或小题 | `hold` + `relabel_candidate` 实验 | Order-1：60 条 remove 全量 tree，外加 12 条 keep 回归控制 | 候选叶子/`uncovered` 分簇复核通过后，才可生成 patch candidate |
| 社会交往-争辩 | 普通对话、偏好、建议/请求、赞同或表面 No/but 被误标；真正反驳/投诉/否认辩解应保留；21 条缺上下文 | `hold` + `relabel_candidate` 实验 | Argument-1：按补全对话、选择、听力及言语行为分层 tree | 候选叶子/`uncovered` 分簇复核通过后，才可生成 patch candidate |
| 社会交往-描述 | 普通问答、固定回应、词义/拼写或其他交际功能被误标；81 条缺具体小题/听力原文/图片 | `hold` + `relabel_candidate` 实验 | Description-1：41 条 remove 按 route/信息完整性做 tree，12 条 keep 回归控制 | 候选叶子/`uncovered` 分簇复核通过后，才可生成 patch candidate |
| 社会/政治/历史的变迁与发展 | 个人经历、一般成长/旅行/助人、普通交际和虚构故事被误标；真正国家/社会发展、政策变革、科技时代变化、文化传承/历史事件应保留；4 条材料缺失 | `hold` + `relabel_candidate` 实验 | Historical-Change-1：按 route/篇章完整性 tree 60 条，12 条 keep 回归控制 | 候选叶子/`uncovered` 分簇复核通过后，才可生成 patch candidate |
| 一般现在时与现在进行时的区别 | 有效的现在/进行时形式或用法题被 DS false 漏判；被动、将来时、固定短语、写作等混入，32 条信息不足/释义冲突 | `hold` | 先裁决 5 条边界，再跑 Tense-Contrast-1 根因分层盲审与 prompt 对照 | 口径冻结且新判别器与盲审一致后，才可收集全量 true 并抽 60 条 |
| 主语 | 连词成句、完成句子、翻译、词汇、被动和主谓一致任务将主语作为分析背景继承；主语构成/主语成分识别题应保留；12 条信息缺失 | `hold` + `relabel_candidate` 实验 | Subject-1：353 条 remove 按 route/主语结构 tree，12 条 keep 回归控制 | 候选叶子/`uncovered` 分簇复核通过后，才可生成 patch candidate |
| 存在 | have/has 所属关系、普通位置/词汇/其他听力内容或背景 there be 被误标；复合听力/情景父题常缺小题；117 条信息缺失 | `hold` + `relabel_candidate` 实验 | Existence-1：可读 remove 按 route/存在表达 tree，12 条 keep 回归控制 | 候选叶子/`uncovered` 分簇复核通过后，才可生成 patch candidate |
| 一般将来时的肯否疑 | 有效的 will / be going to 等将来时结构被 DS false 漏判；书面表达、将来进行/完成、主将从现、固定短语/词汇混入，30 条信息不足/冲突 | `hold` | 先裁决 2 条边界，再跑 Future-1 route 分层盲审与 prompt 对照 | 新判别器与盲审一致后才可收集 full true；真实 remove 簇另开 tree |
| 主系表 | 有效的系动词/表语位置题被 DS false 漏判；纯词义/级别辨析、there be、写作、其他成分和固定表达混入，17 条信息缺失 | `hold` | SVC-1：route 分层盲审与 prompt 对照，真实 remove 簇后续 tree | 新判别器与盲审一致后才可收集 full true；remove 簇另开 tree |

### 3.3 已执行的劣质标签实验结果看板

> 这里是每轮**已经运行**的实验与结论；与 3.1 的待办队列分开维护。任何一行只有在“下一动作”完成并通过门禁后才可改变训练数据状态。`tree_candidate` 不是 replacement，`keep/remove` 也不是源数据修改命令。

| 标签 | 实验 / 可审计产物 | 输入与运行结果 | 验收结论 | 当前状态 | 唯一下一动作 |
|---|---|---|---|---|---|
| `转化法` | T1/T1.1 tree；T1.2 固定 21 条关系判别；Conv-Policy-1：`conversion-policy-1-20260831-111037`；C：`c-root-tree-20260831-134515`；500 条网页 GPT 复核 | Conv-Policy-1：500 条关系普查后对 78 条网页 GPT 复核。`conversion` 仅 `7 correct / 24 incorrect`；其余：派生 `7/12 correct`、屈折 `9/12 correct`、词汇/其他 `6/12 correct`（另 `5 hold/1 incorrect`）、信息不足 `11/11 hold`。C 门禁：`19 atomic / 35 lexical_or_other / 8 mixed_or_multiple_relations / 16 insufficient`；19 条 tree 全部完成，`71 calls / 19 tree_candidate / 0 error`，wall `79.4s`。C 候选复核：`16 candidate_correct / 3 candidate_incorrect`（84.2%）。500 条网页 GPT 复核：`20 keep / 445 remove / 35 uncertain`。 | **历史标签正例污染严重。** 500 条复核显示 DS 原 `match=true` 的 70 条中仅 `13 keep`、`57 remove`；DS 原 `match=false` 的 430 条中仍有 `7 keep`、`388 remove`、`35 uncertain`。旧判别器正例精度仅 `13/70=18.6%`，C 只证明门禁能运行，未解决多 label 和过度细化。 | `hold`；不修改源标签，停止 tree 与旧 direct true 放大。 | **C-500：** 用 500 条完整题面直接从 `知识点` 根节点跑无历史标签 tree；网页 GPT 500 结果仅作事后对照，不进入 prompt。先比较候选是否包含转化法/是否找到合理替代，再决定后续清洗。 |
| `互联通讯` | Theme-1：`theme-1-20260831-103348/tree-run-20260831-104147` | 已严格对齐 500 条原始网页 GPT evidence，抽取 60 条：30 主阅读 remove、10 其他阅读 remove、10 非阅读 remove、10 keep 控制；tree：`59 tree_candidate / 1 budget_exhausted / 0 error`。两端各并发 5，wall `87.7s / 77.9s`。网页 GPT 候选复核：`31 correct / 18 incorrect / 11 hold`。 | **失败：候选主题正确率不足。** 网络言论、网站信息传播、互联网利弊的题可稳定判断；YouTube/社交媒体分享类材料在“互联通讯”和日常生活/艺术等主题之间失稳。 | `hold`；停止 Theme-1 tree 放大。 | 老师裁决以下 10 条“线上分享是主线还是背景”边界题；冻结 Theme-Policy-0 后再做非 tree 主题分流对照。 |

### 3.4 非 P0，但仍在处理的高风险标签

| 优先级 | 标签 / 问题簇 | 初筛信号 | 当前根因 | 当前状态 | 下一动作 |
|---|---|---|---|---|---|
| P1 | `知识点@词汇@词汇辨析@词汇辨析（混合词性）` | 217/500 true（43.4%）；完整复核 true 2/12 | 完形、复合题、词性变化和语法结构混入；“混合词性”边界不清 | 禁止 rollout；M1 盲审包已就绪 | 先做题型/选项词性诊断实验 |
| P1 | `知识点@语法词法@主谓一致@意义一致` | 原始初筛 325/500 true（65.0%）；完整复核 true 2/12、false 1/10 应留 | 普通形式一致、`there be`、`each` 等被混入意义一致；正例污染严重 | 禁止 rollout | 做“意义一致特例”边界诊断 |
| P1 | 结构共标簇：`语法一致`、`含but并列复合句` 等 | false 错判率高 | DS 将“不是唯一主考点”错误当作排除结构共标的理由 | 禁止用 false 清洗 | 做共标 prompt/规则对照；不抢占低匹配 P0 |
| P1 | `词汇（音/形/义）` 的介词、动词、名词、副词子类 | 介词 157/500、动词 194/500、副词 205/500 等 | DS 把“填空实际写出该词”压缩成唯一主考点；固定搭配、时态和语篇共标被漏掉 | 禁止 false 清洗 | 按“填空写词”业务规则做 prompt 对照实验 |
| P2 | `知识点@词汇@词汇辨析@介词（短语）辨析` | 404/500 true；完整复核 true 10/12、false 3/12 应留 | route 硬限制未前置，固定介词搭配有一定 false 漏删 | 未校准 | 题型链路确认后做 route 预过滤与重新校准 |
| P2 | `…@限制性定语从句@whom引导…`、`…@where引导…` | 正例复核仍有边界问题 | 非限制性、综合关系词和抽象地点先行词被误判 | 未校准 | 加反例的小批校准 |

### 3.5 样本不足的低匹配观察队列

以下知识点的初筛匹配率也不高，但总数小于 100；暂不列为 P0，等补足样本或与相邻标签合并诊断后再定：

- `知识点@语法句法@主从复合句@宾语从句@宾语从句的引导词@连接副词wh-ever/however引导宾语从句`：`9/48 = 18.8%`；
- `知识点@语用@存在@不存在`：`19/71 = 26.8%`。

### 3.6 `False 错判率`的计算口径

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

#### CSV 原文核对：派生法与转化法的边界

老师 CSV 共 576 行；两标签均位于 `知识点->词汇->构词法` 下，原文定义的核心区别是明确的：

| 对比项 | 派生法（词根词缀） | 转化法 |
|---|---|---|
| 词形 | 发生显性词形变化：添加/去除前缀、后缀或字母变化 | 词形完全不变 |
| 词性/词义 | 可伴随词性或词义变化，但决定性证据是词形变化 | 必须是同形词承担另一词性或词义功能 |
| CSV 例示 | `un-/dis-/in-/im-/re-/mis-`、`-er/-or/-ist/-tion/-ment/-ness/-ful/-less/-y/-ly` 等 | 名转动、动转名、形转动；`(v. ___) → (n. ___)` |
| 不属于本类 | — | 时态、复数、三单、比较级、固定搭配、普通翻译/默写 |

因此判定顺序必须是：

```text
题目是否实际要求完成一个具体词形任务？
  否 → 普通词义/默写/搭配，不是转化法
  是 → 源词与目标词的拼写是否完全相同？
          否 → 派生法或屈折变化，不是转化法
          是 → 是否因词性/词义功能变化而直接参与答案？
                  是 → 转化法
                  否 → 普通词汇任务
```

CSV 的“转化法”释义中有一处需要特别标记为**歧义文本**：它把“选项可能出现形态相近的词，如 `like` 和 `likes`，词性相同但词义不同”列为题干关键词。`like/likes` 存在词形屈折差异，不能作为转化法的正面例子；“形态相近”也不等于“词形完全不变”。本轮不直接改老师 CSV，而是在 `configs/label_micro_policies/conversion-vs-derivation-v1.json` 中用版本化规则覆盖该歧义，并在实验中记录其影响。

500 条网页 GPT 复核与 C-500 tree 对照进一步验证了这个边界：gold `remove` 中有 24 条派生题被 tree 误返回转化法；gold `keep` 中 13 条是“转化法与其他形态并存”的多标签题，单候选 tree 只返回转化法 3 条。因此后续不能用“候选名称命中”代替“词形不变 + 实际转换动作”的双重证据。

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

DS 恢复后运行 whole-tree，首轮预算固定为：`max_steps=8`、`max_backtracks=2`、两个 endpoint 各并发 5（总并发 10），保留 timing report。人工审核的对象不是“模型是否和旧标签相同”，而是：

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

#### T1 首次运行结果：通过“可运行性”，未通过“候选正确性”验收

首次完整运行使用 `DeepSeek-V4-Flash` 的 `9102`、`9103` 两个 vLLM endpoint，各 30 题、各并发 5：

```text
conversion-prep-20260828-172631/tree-run-20260828-172818/
├─ results-9102.jsonl   30 条：30 tree_candidate
├─ results-9103.jsonl   30 条：29 tree_candidate、1 budget_exhausted
└─ results-all.jsonl    60 条：59 tree_candidate、1 budget_exhausted、0 error
```

性能结果：两个 endpoint 的 wall time 分别为 `99.3s`、`101.8s`；单任务 p50 约 `12s`，慢任务可到 `45–48s`；p95 queue 约 `87–89s`。这是多层树搜索（每题多次串行 choice）在共享服务上的预期排队，不应在优质标签仍占用 endpoint 时提高并发。下一轮继续保持“每端 5、总 10”。

本结果**只证明接口、全树搜索和 timing 记录可用**，不证明 59 个候选标签正确。下一动作是把 `tree-input-60.jsonl + audit-index.jsonl + results-all.jsonl` 合并为网页 GPT 候选复核包：按 selection stratum 审核候选叶子是否解释题目，`budget_exhausted` 是否应保持 hold。未完成 60 条候选复核前，T1 不得进入 T2、不得生成 patch。

#### T1 候选复核结果：`revise_tree`，禁止进入 T2

网页 GPT 对 60 条候选复核包返回了 60 个唯一 `review_id` 和一个标签级结论，JSONL 结构完整；结果如下：

| 候选复核决定 | 数量 | 含义 |
|---|---:|---|
| `candidate_correct` | 51 | tree 候选末级标签能实际解释作答 |
| `candidate_incorrect` | 8 | tree 候选不合理，不能进入候选簇放大 |
| `hold` | 1 | `budget_exhausted` 或业务边界，保持隔离 |

网页 GPT 的实验级结论为 `revise_tree`，并把 `3348636953588649985` 列为待进一步业务裁决题。已确认的系统性问题是：同形转化（如 `run`、`wonder`、`gold`、`graduate`）可合理回到转化法；屈折变化和普通翻译多数已落到合理语法/词汇叶子；但派生边界仍会把 `build→building`、`weigh→weight`、`warmth→warm` 错留在转化法。故 51/60 不是可接受的 T2 放大门槛，且 8 个错误不能当作随机噪声。

**T1.1 的唯一下一实验**：不再重跑全部 60 条。固定使用 `8 candidate_incorrect + 1 hold + 12 candidate_correct` 控制题，比较：

1. 现有全树 prompt；
2. 在转化法终端选择前附加老师冻结的负向约束：`词缀、拼写增删、-ing/-ed、复数、三单、比较级等词形变化不是转化法；只有词形不变而词性改变才可选转化法`。

两个条件必须使用同一 21 条、同一 endpoint 配额、同一 `max_steps=8/max_backtracks=2`；人工只看 8 个已知派生错误是否全部不再返回转化法，以及 12 个同形/合理控制题是否仍保持正确。若任一派生错误仍返回转化法，或控制题出现方向性退化，继续 `hold` 并修订约束，不进入 T2。

T1/T1.1 的网页 GPT 候选复核包统一由 `scripts/build_tree_candidate_review_packet.py` 生成；它只传题面、route、候选标签和候选释义，不传 DS raw response 或 tree trace。T1.1 的 tree 命令在现有参数上额外加入 `--conversion-negative-constraint`；该开关只在转化法位于当前末级候选集合时生效。

#### T1.1 约束对照结果：失败，停止转化法 whole-tree 路线

T1.1 复用 T1 基线，从 60 条中固定筛取 `8 candidate_incorrect + 1 hold + 12 candidate_correct`，仅重跑约束版，两个 endpoint 各并发 5。对照结果：

| 切片 | 基线转化法候选 | 约束版转化法候选 | 候选/状态变化 | 验收 |
|---|---:|---:|---:|---|
| 8 个已知错误 | 3 | 3 | 0 | **失败：3 个派生错误全部未修正** |
| 1 个 hold | 0 | 0 | 0 | 保持 `budget_exhausted`，正确 |
| 12 个正确控制 | 3 | 2 | 3 | **退化：一个派生法控制题变为转化法，另有控制候选改变** |

仍错误返回转化法的题号为 `2966281352808570888`、`2825476033785401356`、`2992442148149280780`。因此不能再提高该 prompt 的措辞强度、不能重复跑同一 T1.1，也不能进入 T2：模型在温度 0 下仍改变控制题路径，说明该 terminal 提示不具备可复现的方向性纠错能力。

**转化法后续处置改为 `hold`**：保留已审核的 51 条候选审核证据，但停止 whole-tree 在该标签上的批量 replacement。`configs/label_micro_policies/conversion-vs-derivation-v1.json` 已冻结“词形不变→转化、显性词缀/词形变化→派生”的通用规则；其中 `direct→director` 是派生法（`-or` 后缀）的明确示例。该示例未提供 question_id，不能替代 `3348636953588649985` 的单题裁决；只有在独立样本上证明该字段可靠，才另开非 tree 的定向重标实验。

#### Conv-Policy-0：独立词形关系判别实验

为避免 tree 的多层选择干扰，后续不再让 DS 输出知识点树路径，而是运行 `scripts/validate_conversion_relation.py`。它只输出五类关系：`conversion`、`derivation`、`inflection`、`lexical_or_other`、`insufficient`，且不向模型提供历史知识点标签。首轮固定使用 T1.1 的 21 条：8 个已知错误、1 个 hold、12 个正确控制；两个 endpoint 总并发仍为 10。通过门禁：已知 `direct→director`、`weigh→weight`、`warmth→warm` 等派生/词形变化例必须稳定为 `derivation`，同形转化控制题必须稳定为 `conversion`。该实验只验证分流字段，不生成 source patch。

#### T1.2 关系判别结果：通过固定边界集，但尚未获得全量清洗资格

运行产物：`t1.1-20260828-175721/conversion-relation-20260831-105933`。21 条均成功返回结构化结果、无请求错误，总并发为 10；分布为 `2 conversion / 9 derivation / 3 inflection / 7 lexical_or_other`，所有结果均为 `high` confidence。

关键门禁全部通过：`direct→director`（`3348636953588649985`）、`weigh→weight`（`2825476033785401356`）、`warmth→warm`（`2992442148149280780`）以及 `build→building` 均不再落为 `conversion`，返回 `derivation`；词形不变的 `wonder v.→wonder n.`（`3479221260516872215`）和 `gold adj.→gold n.`（`3479221260516872195`）均返回 `conversion`。同时，三单/最高级等形态变化被分到 `inflection`，普通翻译、默写、固定搭配被分到 `lexical_or_other`，说明新 prompt 已把“词形关系”与“历史转化法标签”隔离开。

这只证明该 **21 条固定边界集** 的方向正确，不证明 500 条、更不证明全量历史“转化法”数据已经可自动清洗。下一实验是 **Conv-Policy-1**：对该标签 500 条 mentor direct 完整样本运行同一关系判别器，按四个有效关系（`conversion/derivation/inflection/lexical_or_other`）和题型 route 做分层网页 GPT 复核；只有每个拟放大的关系簇达到预定人工门禁，才能作为独立 `patch_candidate`，仍不允许整体替换。

#### Conv-Policy-1：500 条方向普查已完成，进入网页 GPT 分层复核

运行产物：`conversion-prep-20260828-172631/conversion-policy-1-20260831-111037`。500 条均处理成功，分布为：`31 conversion (6.2%)`、`126 derivation (25.2%)`、`63 inflection (12.6%)`、`269 lexical_or_other (53.8%)`、`11 insufficient (2.2%)`。这与 T1.2 的边界集方向一致：历史“转化法”并非一个可直接保留的同质簇，普通词汇/翻译与显性派生是主要污染来源。

网页 GPT 已完成实际生成的 78 条复核，JSONL 完整：78 个唯一 `review_id` + 1 个实验级结论，结构无误。结果显示 v1 不能用于关系簇放大：

| DS v1 预测关系 | 网页 GPT 结果 | 关键失败模式 |
|---|---:|---|
| `conversion` | `7 correct / 24 incorrect` | 模型把“列出同一拼写的名词义/动词义”当成题目实际要求的词性转换；这类默写/释义应为 `lexical_or_other`。 |
| `derivation` | `7 correct / 5 incorrect` | 单一派生较稳定；多空题同时含派生、屈折和固定搭配时不能压成单一派生。 |
| `inflection` | `9 correct / 3 incorrect` | 单一时态/复数/级别变化较稳定；派生后再屈折、或多空混合题会误分。 |
| `lexical_or_other` | `6 correct / 1 incorrect / 5 hold` | 普通词义/搭配稳定；缺题干、答案或解析时应改为 `insufficient`。 |
| `insufficient` | `11 hold` | 全部符合信息不足定义。 |

网页 GPT 结论为 `revise_prompt`。因此 **Conv-Policy-1 失败**：31 条预测转化中只有 7 条真实转化，不能将任何 v1 `conversion` 结果直接保留或生成 patch。

**Conv-Policy-2 的唯一下一动作**：把“题目是否实际要求完成一个词形/词性转换”设为第一道门。仅仅展示同一个词既可作名词又可作动词、双词性释义、单词默写，不得判为 `conversion`，应判 `lexical_or_other`。同时新增 `mixed_or_multiple_relations`，专门隔离多空题内同时出现派生、屈折、搭配等多种关系的样本，而不是强行压入 `derivation` 或 `inflection`。v2 先在同一 78 条上重跑和复核；未通过前，历史转化法全量继续 `hold`。

#### C：任务形态门禁 + 根节点知识树（替代“先验证旧标签”）

本实验不把历史 `转化法`、mentor 的 match 结果或 replacement 建议送入 DS；它们只用于事后按 `question_id` 审计。输入仍为完整题目信息（题干、选项、答案、解析，且去除“题型结构/名称”元数据），不能缩减为只给题干：转化法的失败例正是需要答案和解析才能分辨“实际转换”与“双词性释义”。

流程为：

```text
完整题目（无历史标签）
  → 任务形态门禁：atomic_knowledge / lexical_or_other / mixed_or_multiple_relations / insufficient
  → 仅 atomic_knowledge：从 知识点 根节点的 8 个一级类及其简短释义开始全树搜索
  → tree_candidate / uncovered / budget_exhausted
  → 网页 GPT 独立复核，不直接写回源标签
```

根节点的一级候选为 `词汇、词法、句法、语用、语篇主题、语篇体裁、语音、其他`；其后仍沿用老师 CSV 中的 active 末级标签压缩释义。C 的验收不是 tree 是否能运行，而是：双词性默写必须在门禁阶段被隔离、混合题不得进 tree、进入 tree 的原子题候选须由独立网页 GPT 审核。首轮固定复用 Conv-Policy-1 的 78 条，便于与 v1 直接比较。

#### C 首轮运行结果：门禁有效，候选仍待人工验收

固定 78 条的门禁结果为 `19 atomic_knowledge / 35 lexical_or_other / 8 mixed_or_multiple_relations / 16 insufficient`；只有 19 条进入根节点树，另外 59 条被隔离。19 条树任务均返回 `tree_candidate`，共 71 次 DS 选择调用，根节点调用 19 次，无 `__NO_MATCH__`，wall time `79.4s`。这说明 C 的过滤与运行链路符合设计，但 `tree_candidate` 仅是候选，不代表末级标签正确。

网页 GPT 已完成这 19 条的盲审：`16 candidate_correct / 3 candidate_incorrect`，候选正确率 `84.2%`，实验级结论为 `revise_tree`，因此没有通过放大门禁。

三个失败样本揭示了两类问题：

- `volunteer/volunteers`：树选了转化法，但题目同时需要名词词性和复数形式，属于混合关系；C 的门禁仍漏掉了这类“主关系 + 并行形态”的题。
- `wood→wooden`：树过度细化到“形容词作定语”，题面只证明需要形容词，并没有具体定语位置证据。
- `drop/drops`：树选了屈折标签，但题目同时比较动词三单与名词单数，单一屈折叶不能完整解释选项。

其余 16 条中，明确的同形转化、派生、时态/非谓语/比较级题大体能落到合理末级；不过 `candidate_correct` 只表示候选能解释主要作答依赖，不表示题目全部并行知识点已被输出。下一步只对这 3 个失败边界及等量通过控制题做 Conv-Policy-2，不进入全量。

#### 500 条网页 GPT 复核：确认可作为校准集，不等于已完成清洗

新收到的 500 条逐题复核 JSONL 通过基础校验：500 条 review、500 个唯一 `question_id`、无解析错误；另有 1 条标签结论。逐题结果为 `20 keep / 445 remove / 35 uncertain`，其中 `keep` 包含 7 条纯转化和 13 条“转化法与其他形态并存但转化独立参与答案”的多标签题。

与 mentor 原始 DS 结果按 `question_id` 对齐后：原 DS `match=true` 的 70 条只有 `13 keep / 57 remove`，正例精度为 `18.6%`；原 DS `match=false` 的 430 条中有 `7 keep / 388 remove / 35 uncertain`。这证明旧 DS 的 `match=true` 不能直接作为 silver，且 false 侧仍漏掉少量真实转化。500 条复核适合作为新的 target-specific prompt 校准集，但不能直接生成 source patch。

该复核的标签结论列出了 35 个 `teacher_question_ids`，超出当前 JSONL 契约规定的最多 10 个；这不影响 500 条逐题结果的统计，但导入现有 `analyze_web_gpt_raw_reviews.py` 前需将结论中的老师待裁决列表修正为不超过 10 个或置空。逐题 `decision/reason_code` 仍需保留原样，不得因修正结论元数据而改动。

本轮不再先跑 target-specific 二分类器：用户明确要求直接验证“500 条无历史标签输入 → 根节点 tree”的整体效果。为避免 tree 重新改动已判定的 keep/remove，结果只做候选质量与覆盖率实验，不能直接生成 patch。

#### C-500：500 条无历史标签根树实验（已完成，待金标对照）

`scripts/build_conversion_relation_packet.py` 先从 mentor 的 500 条完整记录生成脱敏题面；`scripts/build_unanchored_root_tree_packet.py` 再把每条题面送入 `知识点` 根节点，完全不携带 `output_all`、`llm_match`、`llm_should_be` 或历史转化法标签。树输出的单个 `tree_candidate`、`uncovered` 或 `budget_exhausted` 只用于实验。

本轮已在两个 DS endpoint 各并发 5 完成 500 条：`478 tree_candidate (95.6%) / 9 budget_exhausted (1.8%) / 4 uncovered (0.8%) / 9 unparsed (1.8%)`，无 HTTP error；两端 wall time 分别为 `852.3s` 与 `835.6s`。`unparsed` 是协议解析失败，必须保持隔离，不能按 `uncovered` 或错误标签处理。

候选叶子分布显示：`词汇（音/形/义）`四个子类合计 214 条（名词 126、动词 50、形容词 28、副词 10），`固定搭配/句型` 56 条，`派生法` 54 条，`转化法` 36 条；其余候选均为长尾叶子。与网页 GPT 500 条复核的 20 条 keep（其中纯 conversion 7 条、mixed 13 条）相比，tree 的 `转化法` 候选存在过预测风险，必须按 `question_id` 做金标对照，不能仅按候选名称计数放行。

9 条 `unparsed` 的具体原因包括：候选覆盖不足时仍返回具体路径、重复 JSON key 导致 `Extra data`、以及模型返回当前层之外的深层路径。它们均保持 hold；这批结果不应通过放宽解析器“修成”候选，因为那会掩盖 tree 候选池/提示词的真实缺口。

下一步按 `question_id` 与 500 条网页 GPT 复核对照：对网页 GPT `keep`，检查 tree 是否返回转化法或至少覆盖主要考点；对 `remove`，检查 tree 是否给出派生/屈折/词汇替代或 `uncovered`；对 `uncertain`，单独统计其是否被 tree 强行细化。由于当前 tree 每题只输出一个候选，包含多个并行知识点的题只能评估“主要候选”，不能据此声称完整多标签重标完成。

#### C-500 对照结果：失败，不能作为无标签全量重标器

500 条 tree 结果与网页 GPT 500 条复核按 `question_id`、`parent_id` 完全对齐。对照矩阵如下：

| 网页 GPT 结论 | tree 转化法 | tree 非转化候选 | `budget_exhausted` | `uncovered` | `unparsed` |
|---|---:|---:|---:|---:|---:|
| `keep`（20） | 9 | 11 | 0 | 0 | 0 |
| `remove`（445） | 27 | 403 | 7 | 0 | 8 |
| `uncertain`（35） | 0 | 28 | 2 | 4 | 1 |

若把网页 GPT 结论暂作本轮对照参考，tree 输出“转化法”的 precision 仅 `9/(9+27)=25.0%`，对 20 条 keep 的 target recall 为 `9/20=45.0%`；对 35 条信息不足题，仍有 28 条被强行细化为其它知识点候选。按实际关系看，`remove × derivation` 中有 24 条被 tree 误送回转化法，说明 root tree 仍系统性混淆派生与转化；`keep × mixed_or_multiple_relations` 中仅 3/13 返回转化法，反映单候选输出无法表达共存标签。

因此 C-500 只证明“去掉历史标签后，tree 能产生一个候选分布”，没有证明它能完成转化法的保留/删除/替代，更不能把 500 条候选直接写入训练数据。当前必须停止 C-500 放大，不做 patch。

下一步不是重复跑同一 tree，而是明确两项改造后再做小批对照：

1. **信息门禁**：题面缺少具体小题、答案或解析时，必须在进 tree 前隔离，或给 root 增加显式 `insufficient_context` 控制项；不能让模型在信息不足时强行选择普通知识点。
2. **多标签表示**：当前每题 `max_output_labels=1`，只能评估主要候选，无法表达 `转化法 + 名词的数` 等共存情况。若目标是完整重标，需改成受限的多次 tree（选中一个叶子后排除再查、设上限并保留轨迹）或按目标标签逐个判定；在此改造前，C 不能承担“第一次就打全所有标签”的任务。

本轮先只验证第一项的 prompt 变化，不宣称已经解决多标签表示问题：从 500 条固定复核集中抽取 60 条（20 keep、24 remove 分层、16 uncertain），比较当前 prompt 与 `--conversion-structured-guard` 版本。两条件使用完全相同的题目、CSV、树、参数和 endpoint 配额；网页 GPT 500 结果只用于事后评估，不进入 DS prompt。

##### Conv-Policy-1 的 DS v1 具体失效点

这不是历史标签误差的复述，而是对“DS 仅看题面后输出词形关系”的判别误差分析。78 条网页 GPT 复核显示有四类不同根因：

1. **把词汇呈现误当作实际转换（最主要，24 条）**。`promise / block / brush / plan / cover / text` 等题只是分别默写或解释一个拼写相同单词的名词义、动词义；DS 看见“同形 + 双词性”便输出 `conversion`，忽略了学生并未把源词变为目标词。该错误占 v1 预测 `conversion` 的 `24/31`，所以 v1 的最大缺口在任务意图，而不是同形词判断。
2. **一题多关系却被强行压成一个关系（至少 10 条）**。多空表格或综合题同时含派生、屈折、同形词性选择和固定搭配。例如 `kind→kindness` 与 `little→less`、`high→height / cross→cross / goal→goalkeeper`、`learn→learning` 与 `careful→carefully`。当前五分类没有“混合”出口，DS 只能任意选 `derivation`、`inflection` 或 `lexical_or_other`，结果不可作为某一关系的训练/清洗证据。
3. **复合形态只盯最后一步**。`work→worker→workers` 被错归 `inflection`，因为最终看到复数 `-s`，但完整源词到目标词包含 `-er` 派生；相反 `run→running` 在句法位置要求动名词时应视为 `inflection`，却被错归 `derivation`。v2 必须先抽取完整的“源词→目标词”与题干要求，再按优先级判断，而不能按最后一个后缀做表面分类。
4. **信息不足门禁触发太晚**。`lexical_or_other` 12 条中有 5 条实际上只有标题、词库或总题干，没有具体小题、答案和解析；这些应直接 `insufficient`。`insufficient` 自身 11/11 hold 是稳定的，说明不是类别定义错误，而是 v1 没有先检查最小可判定信息。

因此 v2 不能仅在旧 prompt 里多加一两句负向约束，必须变为两阶段输出：

```text
阶段 A：has_specific_required_transformation / has_multiple_relations / has_minimum_evidence
阶段 B：仅当“有具体单一转换且信息充分”时，判断 conversion / derivation / inflection；
        否则输出 lexical_or_other / mixed_or_multiple_relations / insufficient。
```

这样 `conversion` 的必要条件变为：**题面要求某个具体源词以完全相同拼写承担另一词性功能**，而不是“题面中恰好提到一个双词性单词”。

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

离线建包使用 `scripts/build_theme_tree_packet.py`：输入必须是已 materialize 的 500 条完整 mentor verifier JSONL 与已校验的网页 GPT `evidence.jsonl`；DS-facing packet 不含网页 GPT decision，decision 仅存在 audit index。若某个固定 strata 不足，脚本拒绝运行而不静默改变配额。

tree 根使用 active taxonomy 全树；每题只能得到一个 terminal leaf、`uncovered` 或 `budget_exhausted`。首轮固定 `max_steps=8`、`max_backtracks=2`、`concurrency=16`，并写 timing report。验收时网页 GPT/人工只审核三件事：

1. `keep` 控制题是否仍回到互联通讯；
2. 被移出的题的候选叶子是否真实解释材料主题；
3. `uncovered` 是否合理，而不是被强行塞到错误主题。

只有某个 `原互联通讯 × tree_candidate/uncovered × route × 上下文完整性` 簇达到独立 12 条复核的预定标准，才能生成 `patch_candidate`；任何不稳定簇继续 `hold`。

#### Theme-1 候选复核结果：失败，停止主题 whole-tree 放大

网页 GPT 已返回 60 个唯一 `review_id` 与一个实验级结论，JSONL 可解析、无缺行：`31 candidate_correct / 18 candidate_incorrect / 11 hold`。尽管 tree 服务运行无错误，候选主题正确率不足，结论为 `revise_tree`，因此不能进入 T2 或生成 `patch_candidate`。

稳定部分：材料核心明确是网络言论、网站信息传播、互联网利弊或数字通讯工具时，“互联通讯”判断可成立；电话、邮箱、网站仅作为广告联系方式时也未被表面词系统性误判。失败部分：以 YouTube 分享生活、社交媒体展示美食/摄影等为主线的完整材料，tree 会落到“日常生活与学校生活”“中外艺术文学及名家评析”等不匹配主题；说明“线上分享是否已构成材料主线”的业务边界未冻结。

以下 10 条进入老师裁决，不能由 tree 或网页 GPT 自动决定：`2780370638292385792`、`2727230263710494720`、`2741597323012907008`、`2747763462201974784`、`2786168626072064000`、`2767836439874424833`、`2793802129158471680`、`2800779164663488512`、`2795192294447353856`、`2951609216901070848`。

**Theme-Policy-0 的唯一下一动作**：老师冻结“线上分享/社交媒体/视频网站”在何种情况下属于互联通讯主主题的规则。冻结前，保持 `hold`，停止 whole-tree 主题 replacement；冻结后只在这组边界题与等量非边界题上做一个直接主题分流对照，不重跑当前 Theme-1。

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

## 12. P0：社会交往-描述

### 12.1 事实画像与可审计证据

目标标签为 `知识点@语用@社会交往@描述`。老师释义的有效范围是围绕人物、活动、地点、时间、方式、原因、频率、外貌或评价等具体信息进行询问、回答或描述；固定交际回应、纯词义/拼写或其他交际功能不能仅因出现疑问词而保留。网页 GPT 已完成 mentor 500 条 direct-verifier 明细的原始直审，并通过 `500/500` 的 `question_id + parent_id` 对齐：

```text
english-knowledge-tagger-runtime/知识点_语用_社会交往_描述.jsonl
english-knowledge-tagger-runtime/web-gpt-reviews/social-description-20260828/
├─ evidence.jsonl
└─ summary.json
```

| 证据切片 | keep | remove | uncertain | 解读 |
|---|---:|---:|---:|---|
| 网页 GPT 全部 500 条 | 378 | 41 | 81 | 标签级结论为 `hold` |
| mentor direct `match` 93 条 | 88 | 3 | 2 | DS true 基本有效，但仍有少量关键词误判 |
| mentor direct `mismatch` 407 条 | 290 | 38 | 79 | DS false 与网页 GPT 多数同向，但不能直接删标 |
| `parent × 单选题 × 听力单选` | 205 | 10 | 7 | 当前最大且较稳定的描述信息 route |
| `parent × 单选题 × 选择题` | 22 | 23 | 0 | 主要明确误标簇，需检查是否实际考其他语用功能 |
| `parent × 复合题 × 听力单选` | 0 | 0 | 56 | 缺少具体小题/听力上下文，必须 hold |
| `parent × 补全题 × 补全对话` | 56 | 0 | 0 | 不与选择题共享“描述”规则 |

### 12.2 根因、处理结论与禁止动作

强信号表明标签整体有效，但存在两类问题：一是单选选择题中普通交际、固定回应、词义/拼写或其他语用功能被误标；二是复合听力父题缺小题或原文，网页 GPT 无法可靠判断。81 条 `uncertain` 不可强制清理。当前处置为 `hold + relabel_candidate`。

禁止：把 41 条网页 GPT remove 或 38 条 DS false 直接删除；把 378 条 keep 直接发布 silver；把缺听力/小题的 81 条送入 tree；用“听力单选”或“补全对话”单独作为自动保留规则。

### 12.3 Description-1：语用去向 tree 验证

先离线从 41 条明确 remove 按 route 固定抽取（不足时全部使用），再从 378 条 keep 中固定抽 12 条作为回归控制，共最多 53 条。remove 至少覆盖 `parent × 单选题 × 选择题`、`parent × 单选题 × 听力单选`、补全对话及其他可读 route；81 条 uncertain 全部排除。

DS 恢复后使用 active taxonomy 全树，固定 `max_steps=8`、`max_backtracks=2`、`concurrency=16`，记录节点与请求耗时。验收关注：keep 控制题是否仍返回“描述”；remove 是否转到更准确的语用叶子或合理 `uncovered`；不同 route、音频文本状态是否造成系统性偏差。每个 `tree_candidate/uncovered × route` 簇独立复核 12 条通过后才允许生成 `patch_candidate`。

## 13. P0：社会/政治/历史的变迁与发展

### 13.1 事实画像与可审计证据

目标标签为 `知识点@语篇主题@人与社会@社会/政治/历史的变迁与发展`。老师释义的有效范围是社会/国家发展、政策变革、生活方式演变、科技时代变化、传统文化传承及历史人物/事件为语篇主线；个人经历、一般成长/旅行/助人故事、普通交际和虚构故事不能仅因出现“过去/未来/历史人物”而保留。网页 GPT 已完成 mentor 500 条 direct-verifier 明细的原始直审，并通过 `500/500` 的 `question_id + parent_id` 对齐：

```text
english-knowledge-tagger-runtime/知识点_语篇主题_人与社会_社会_政治_历史的变迁与发展.jsonl
english-knowledge-tagger-runtime/web-gpt-reviews/social-political-historical-change-20260828/
├─ evidence.jsonl
└─ summary.json
```

| 证据切片 | keep | remove | uncertain | 解读 |
|---|---:|---:|---:|---|
| 网页 GPT 全部 500 条 | 189 | 307 | 4 | 标签级结论为 `p0_remediation` |
| mentor direct `match` 97 条 | 94 | 3 | 0 | DS true 基本有效 |
| mentor direct `mismatch` 403 条 | 95 | 304 | 4 | false 中仍有真实历史/发展主题，不能直接按 false 删除 |
| `parent × 复合题 × 阅读理解` | 64 | 99 | 1 | 真实主题与个人/虚构故事混杂，需按篇章主线判断 |
| `parent × 完形填空 × 完形填空` | 16 | 49 | 0 | 多数是普通故事，不能因出现过去时间词保留 |
| `parent × 主观题 × 书面表达` | 37 | 70 | 0 | 个人经历作文是主要误标簇 |
| `parent × 复合题 × 听力单选` | 0 | 24 | 0 | 当前均为误标，且不与阅读父题共用规则 |

### 13.2 根因、处理结论与禁止动作

已证实的主要问题是**主题主线判断过宽**：题面出现奥运会、环保、旧房、人物或时间词，并不等于语篇围绕社会/政治/历史变迁；有效样本则明确讨论改革发展、科技/生活方式演变、国家创新和历史事件。4 条材料缺失的记录继续 `hold`。

当前处置为 `hold + p0_remediation`。禁止：直接删除 307 条网页 GPT remove 或 304 条 DS false；直接发布 189 条 keep；把书面表达、完形、听力和阅读父题混成一个 route policy；强迫每条 remove 获得 replacement，允许 tree 返回 `uncovered`。

### 13.3 Historical-Change-1：主题去向 tree 验证

先离线从 307 条明确 remove 按 route/篇章完整性固定抽 60 条，再从 189 条 keep 抽 12 条回归控制，共 72 条；4 条 uncertain 不进入任务。60 条至少覆盖 25 条阅读父题、15 条书面表达/完形、10 条听力/其他 route、10 条不同篇章主线。

DS 恢复后使用 active taxonomy 全树，固定 `max_steps=8`、`max_backtracks=2`、`concurrency=16`，记录节点与请求耗时。验收：keep 控制题仍返回该主题或合理相邻主题；remove 应返回能解释主线的主题叶子或 `uncovered`；个人故事/虚构故事不得因历史词汇被强行归入本标签。每个 `tree_candidate/uncovered × route × 篇章主线` 簇独立复核 12 条通过后才可形成 `patch_candidate`。

## 14. P0：一般现在时与现在进行时的区别

### 14.1 事实画像与可审计证据

目标标签为 `知识点@语法词法@动词时态@时态辨析@一般现在时与现在进行时的区别`，当前启用路径为 `知识点->词法->动词时态->时态辨析->一般现在时与现在进行时的区别`。老师释义同时覆盖一般现在时的习惯/事实/状态、现在进行时的此刻/现阶段动作、两者用法辨析及对应谓语形式；因此不能把“只出现一个时态”一概当作错标，是否属于该业务标签必须由题目实际作答依赖决定。

网页 GPT 已完成 mentor 500 条 direct-verifier 明细的原始直审，并通过 `500/500` 的 `question_id + parent_id` 对齐：

```text
english-knowledge-tagger-runtime/知识点_语法词法_动词时态_时态辨析_一般现在时与现在进行时的区别.jsonl
english-knowledge-tagger-runtime/web-gpt-reviews/present-vs-progressive-contrast-20260829/
├─ evidence.jsonl
└─ summary.json
```

| 证据切片 | keep | remove | uncertain | 解读 |
|---|---:|---:|---:|---|
| 网页 GPT 全部 500 条 | 330 | 138 | 32 | 标签级结论为 `p0_remediation`，不能直接清洗 |
| mentor direct `match` 98 条 | 91 | 5 | 2 | DS true 大多成立，但有少量相邻标签/信息冲突 |
| mentor direct `mismatch` 402 条 | 239 | 133 | 30 | DS false 中仍有大量有效时态题，不能当删除名单 |
| `child × 复合题 × 语法选择` | 65 | 2 | 0 | 当前样本以语法形式考查为主 |
| `child × 完形填空 × 语法选择` | 76 | 4 | 0 | 当前样本以语法形式考查为主 |
| `parent × 单选题 × 选择题` | 81 | 66 | 3 | 最大混合簇，需区分时态辨析与相邻语法/词汇题 |
| `parent × 主观题 × 书面表达` | 0 | 23 | 0 | 明确不属于该选择/语法辨析标签的主要 route |
| 复合题父题及缺小题 route | 0 | 0 | 21 | 缺具体题面，继续 hold |

### 14.2 根因、处理结论与禁止动作

已确认的主要问题是两类并存：

1. **判别器漏判信号**：在 DS `mismatch` 的 402 条中，网页 GPT 仍保留 239 条；这些题多由一般现在时/现在进行时形式、标志词或语境直接约束答案，说明现有 DS 对该标签的判定边界偏窄。
2. **历史标签混入相邻任务**：138 条 remove 主要包括被动语态（43）、固定短语（10）、纯词义/拼写（6）以及其他不属于本标签的题（79）；书面表达 23 条全部为 remove。另有 27 条信息不足和 5 条释义/来源冲突，不能强制判定。

网页 GPT 指定 5 条老师边界题：`2139881335183671297`、`2139861442896171008`、`2139847991060729863`、`2141204321814786048`、`2867356230077120512`。当前处置为 `hold`。禁止用 133 条 DS false 批量删标，也禁止因 330 条 keep 直接发布全量或把“单一时态题”自动归入/排除该标签。

### 14.3 Tense-Contrast-1：业务口径与判别器校准

1. 老师先裁决上述 5 条边界题，明确“单一时态形式考查”何时仍归本标签、何时应归具体时态标签，以及被动/将来时/固定短语的排除边界。
2. 去除 32 条 uncertain 后，从 138 条 remove 按 `reason_code × route` 固定抽 60 条，再从 330 条 keep 按主要 route 固定抽 12 条，形成 72 条不含历史标签和 DS 字段的盲审包。
3. 盲审完成后，在同一 72 条、同一温度和候选集合下做原释义/压缩释义对照；压缩释义必须明确：时态形式、标志词或语境是否**直接决定答案**，而不是要求题目必须同时出现两个时态。记录 route、根因切片、keep/remove/uncertain 和请求耗时。
4. 只有老师口径冻结、盲审与新 DS 方向一致，才可对同质 route 收集全量 `match=true`；全量 true 仍需独立抽 60 条复核才可 `released_silver`。remove 若形成稳定替代标签簇，再另开 tree 去向实验；本实验不直接生成 replacement 或 patch。

## 15. P0：主语

### 15.1 事实画像与可审计证据

目标标签为 `知识点@语法句法@句子成分@主语`，当前启用路径应迁移为 `知识点->句法->句子成分->主语`。只有主格代词、名词/动名词/不定式作主语、主语从句、形式主语 `it` 或直接识别主语成分等结构实际约束作答时，才应保留；主语仅作为句子已有材料或解析背景时不应继承标签。

网页 GPT 已完成 mentor 500 条 direct-verifier 明细的原始直审，并通过 `500/500` 的 `question_id + parent_id` 对齐：

```text
english-knowledge-tagger-runtime/知识点_语法句法_句子成分_主语.jsonl
english-knowledge-tagger-runtime/web-gpt-reviews/subject-20260831/
├─ evidence.jsonl
└─ summary.json
```

| 证据切片 | keep | remove | uncertain | 解读 |
|---|---:|---:|---:|---|
| 网页 GPT 全部 500 条 | 135 | 353 | 12 | 标签级结论为 `p0_remediation` |
| mentor direct `match` 104 条 | 94 | 10 | 0 | DS true 基本有效，但仍有背景继承误标 |
| mentor direct `mismatch` 396 条 | 41 | 343 | 12 | false 大多同向 remove，是真实历史过标的强信号 |
| `parent × 填空题 × 完成句子` | 7 | 229 | 0 | 最大污染簇：连词成句/句子重组里主语常为已给材料 |
| `parent × 单选题 × 选择题` | 23 | 30 | 0 | 主语构成、主谓一致及其他语法任务混杂 |
| `child × 复合题 × 语法选择` | 37 | 0 | 0 | 当前样本多为主格/非谓语/主语结构直接决定答案 |
| `child × 完形填空 × 语法选择` | 41 | 1 | 0 | 当前样本多为主语结构直接决定答案 |
| 复合题父题及缺小题 route | 0 | 0 | 12 | 信息不足，继续 hold |

### 15.2 根因、处理结论与禁止动作

已确认的根因是**句子分析背景被错误继承为考点**：连词成句、翻译、完成句子、词汇、被动和主谓一致题几乎都能在解析中看到“主语”，但这不代表学生必须选择、构造或识别主语。真实保留簇则是主格选择、动名词/不定式/名词作主语、主语从句、形式主语和划线成分识别。

当前处置为 `hold + p0_remediation`。禁止：直接删除 353 条网页 GPT remove 或 343 条 DS false；直接发布 135 条 keep；把“完成句子”或“语法选择”设成自动删除/自动保留规则；将 12 条缺小题/图片/答案的记录送入 tree。

### 15.3 Subject-1：主语结构 tree 去向验证

先离线从 353 条明确 remove 按 `route × 主语是否为已给材料 × 原任务类型` 固定抽 60 条，再从 135 条 keep 抽 12 条回归控制，共 72 条；12 条 uncertain 不进入任务。60 条至少覆盖 30 条 `parent × 填空题 × 完成句子`、10 条单选、10 条翻译/拼写/情景运用及 10 条其他可读 route。

DS 恢复后使用 active taxonomy 全树，固定 `max_steps=8`、`max_backtracks=2`、`concurrency=16`，记录节点与请求耗时。验收：keep 控制题仍回到主语或合理的相邻结构；remove 能返回更准确的末级标签或 `uncovered`；主谓一致、被动和句子重组不得被树错误归回主语。每个 `tree_candidate/uncovered × route × 结构模式` 簇独立复核 12 条通过后才可形成 `patch_candidate`。

## 16. P0：存在

### 16.1 事实画像与可审计证据

目标标签为 `知识点@语用@存在@存在`。可保留的题必须直接考查 `there be` 的构成、主谓一致、时态或存在问答，或在听力/情景中必须据此确定“某处有什么”；`have/has` 所属关系、普通位置/词汇信息、其他听力内容，或只是背景中出现 `there be` 的题不应继承该标签。

网页 GPT 已完成 mentor 500 条 direct-verifier 明细的原始直审，并通过 `500/500` 的 `question_id + parent_id` 对齐：

```text
english-knowledge-tagger-runtime/知识点_语用_存在_存在.jsonl
english-knowledge-tagger-runtime/web-gpt-reviews/existence-20260831/
├─ evidence.jsonl
└─ summary.json
```

| 证据切片 | keep | remove | uncertain | 解读 |
|---|---:|---:|---:|---|
| 网页 GPT 全部 500 条 | 139 | 244 | 117 | 标签级结论为 `p0_remediation` |
| mentor direct `match` 106 条 | 87 | 3 | 16 | true 多数有效，但已有信息缺失与少量误触发 |
| mentor direct `mismatch` 394 条 | 52 | 241 | 101 | false 多数同向 remove，但有存在表达漏判且缺失率很高 |
| `child × 复合题 × 情景运用` | 24 | 97 | 0 | 最大可处理污染簇，需按实际言语内容分流 |
| `child × 复合题 × 听力单选` | 8 | 59 | 0 | 小题可读时大多不是存在表达 |
| `parent × 单选题 × 听力单选` | 40 | 39 | 19 | 有效存在问答与其他听力信息混杂 |
| 复合题父题（听力/情景） | 0 | 0 | 87 | 缺小题或原文，必须 hold |

### 16.2 根因、处理结论与禁止动作

已确认的根因是**存在表达被宽泛继承**：解析或材料里出现 `there be`、地点信息，甚至只有物品词汇，并不代表本题考查存在；同时 `have/has` 所属关系与存在表达常被混淆。117 条 uncertain 主要来自复合听力/情景父题缺具体小题、音频原文或图片，不能靠推测清洗。

当前处置为 `hold + p0_remediation`。禁止：直接删除 244 条网页 GPT remove 或 241 条 DS false；直接发布 139 条 keep；把“听力单选”或“情景运用”作为自动保留/删除规则；将 117 条信息不足题送入 tree。

### 16.3 Existence-1：存在表达 tree 去向验证

先离线从 244 条明确 remove 中按 `route × 是否出现 there be × have/has/位置/其他信息` 固定抽 60 条，再从 139 条 keep 抽 12 条回归控制，共 72 条；117 条 uncertain 全部排除。60 条至少覆盖 25 条情景运用小题、15 条听力小题、10 条普通单选/填空及 10 条其他可读 route。

DS 恢复后使用 active taxonomy 全树，固定 `max_steps=8`、`max_backtracks=2`、`concurrency=16`，记录节点与请求耗时。验收：keep 控制题应仍返回存在或合理相邻标签；remove 应返回更准确的语用/语法叶子或 `uncovered`；`have/has`、地点信息和背景 there be 不得被树错误归回存在。每个 `tree_candidate/uncovered × route × 表达模式` 簇独立复核 12 条通过后才可形成 `patch_candidate`。

## 17. P0：一般将来时的肯否疑

### 17.1 事实画像与可审计证据

目标标签为 `知识点@语法词法@动词时态@一般将来时@一般将来时的肯否疑`。可保留的题必须由 `will`、`be going to`、现在进行时表将来、`be to do` 或 `there be` 将来结构的肯定/否定/一般疑问/特殊疑问形式直接约束作答；仅有未来时间背景、将来进行/完成、主将从现、固定短语或词汇任务不应继承该标签。

网页 GPT 已完成 mentor 500 条 direct-verifier 明细的原始直审，并通过 `500/500` 的 `question_id + parent_id` 对齐：

```text
english-knowledge-tagger-runtime/知识点_语法词法_动词时态_一般将来时_一般将来时的肯否疑.jsonl
english-knowledge-tagger-runtime/web-gpt-reviews/future-affirmative-negative-question-20260831/
├─ evidence.jsonl
└─ summary.json
```

| 证据切片 | keep | remove | uncertain | 解读 |
|---|---:|---:|---:|---|
| 网页 GPT 全部 500 条 | 393 | 77 | 30 | 标签级结论为 `hold`，主体有效但不能直接发布 |
| mentor direct `match` 117 条 | 116 | 1 | 0 | DS true 几乎全部有效 |
| mentor direct `mismatch` 383 条 | 277 | 76 | 30 | DS false 中仍有大量有效将来时形式题，不能当删除名单 |
| `parent × 单选题 × 选择题` | 194 | 17 | 0 | 最大且总体稳定的校准 route |
| `parent × 填空题 × 单词拼写` | 47 | 6 | 0 | 多数由将来时形式直接决定答案 |
| `parent × 填空题 × 完成句子` | 40 | 3 | 0 | 多数由肯否疑或结构变换直接决定答案 |
| `parent × 主观题 × 书面表达` | 0 | 48 | 0 | 明确误标簇，不与客观题共用判别规则 |
| 复合题父题及缺小题 route | 0 | 0 | 28 | 信息不足，继续 hold |

### 17.2 根因、处理结论与禁止动作

主要问题是**DS 对将来时形式标签的漏判与历史相邻时态任务混入并存**：在 DS `mismatch` 的 383 条中，网页 GPT仍保留 277 条，说明单靠 DS false 不能清洗；77 条 remove 则集中于开放写作、将来进行/完成、主将从现、固定短语和词汇。网页 GPT 指定 `3092065473160806400`、`2730124725052616708` 为老师边界题；另有 28 条信息不足、2 条释义/来源冲突。

当前处置为 `hold`。禁止：直接删除 76 条 DS false 或 77 条网页 GPT remove；直接发布 393 条 keep；把书面表达或任一题型作为自动规则；将 30 条 uncertain 送入 tree。

### 17.3 Future-1：将来时形式判别器校准

1. 老师先裁决两个边界题，冻结一般将来时与将来进行/完成、主将从现及其他未来表达的边界。
2. 从 `parent × 单选题 × 选择题`、`parent × 填空题 × 单词拼写/完成句子`、`parent × 主观题 × 书面表达` 各按固定种子抽取，构成 36 条不含历史标签/DS 字段的盲审包；28 条缺小题/文本样本排除。
3. DS 恢复后，在同一 36 条、同一温度和候选集合下比较原释义与压缩释义：只有将来时的具体肯否疑结构实际决定答案时才保留；记录每 route 的 keep/remove/uncertain 及请求耗时。
4. 老师口径冻结且新 DS 与盲审方向一致后，才可对同质 route 收集全量 true；full true 仍需独立抽 60 条复核。真实 remove 若形成稳定替代标签簇，再另开 tree 去向实验。

## 18. P0：主系表

### 18.1 事实画像与可审计证据

目标标签为 `知识点@语法句法@简单句@主+系+表`。可保留的题必须直接判断主系表句式、选择或使用系动词，或依据表语位置确定形容词、名词、介词短语等形式；仅有词义/级别辨析、`there be`、固定表达或其他句子成分的题不应继承该标签。

网页 GPT 已完成 mentor 500 条 direct-verifier 明细的原始直审，并通过 `500/500` 的 `question_id + parent_id` 对齐：

```text
english-knowledge-tagger-runtime/知识点_语法句法_简单句_主+系+表.jsonl
english-knowledge-tagger-runtime/web-gpt-reviews/subject-linking-verb-predicative-20260831/
├─ evidence.jsonl
└─ summary.json
```

| 证据切片 | keep | remove | uncertain | 解读 |
|---|---:|---:|---:|---|
| 网页 GPT 全部 500 条 | 416 | 67 | 17 | 标签级结论为 `hold`，主体有效但不可直接发布 |
| mentor direct `match` 127 条 | 120 | 3 | 4 | DS true 基本有效 |
| mentor direct `mismatch` 373 条 | 296 | 64 | 13 | DS false 中大量仍是有效主系表题，不能作为删除名单 |
| `child × 复合题 × 语法选择` | 128 | 29 | 0 | 有效题占多数，但存在相邻语法/词义污染 |
| `child × 完形填空 × 语法选择` | 139 | 19 | 0 | 有效题占多数，但存在相邻语法/词义污染 |
| `parent × 填空题 × 完成句子` | 64 | 1 | 0 | 最大稳定 route，可用于结构判别器校准 |
| `parent × 单选题 × 选择题` | 36 | 7 | 0 | 需与词义/级别辨析分开 |
| 复合题父题及缺小题 route | 0 | 0 | 17 | 信息不足，继续 hold |

### 18.2 根因、处理结论与禁止动作

当前证据表明**DS 对主系表结构/表语位置的漏判与历史相邻任务混入并存**：296 条 DS false 仍被网页 GPT保留；67 条 remove 则主要是纯词义或级别辨析、`there be`、开放写作、其他句子成分和固定表达。当前没有老师边界题，但 17 条缺具体小题、图片或答案，不能强制判定。

当前处置为 `hold`。禁止：直接删除 64 条 DS false 或 67 条网页 GPT remove；直接发布 416 条 keep；把复合题语法选择或完成句子设成自动保留规则；将 17 条 uncertain 送入 tree。

### 18.3 SVC-1：主系表结构判别器校准

从 `child × 复合题 × 语法选择`、`child × 完形填空 × 语法选择`、`parent × 填空题 × 完成句子` 各按固定种子抽 12 条，构成 36 条不含历史标签和 DS 字段的盲审包；17 条 uncertain 排除。盲审重点是：系动词/表语结构是否真的决定答案，还是仅出现相同词汇或形态。

DS 恢复后，在相同 36 条、温度和候选集合下比较原释义与压缩释义：`必须由主语+系动词+表语的结构，或表语位置的形式选择直接决定答案；仅有 be、形容词或固定表达不够`。记录每 route 的 keep/remove/uncertain 和请求耗时。只有新 DS 与盲审方向一致后，才可收集同质 route 的 full true 并独立抽 60 条复核；67 条 remove 若形成稳定替代标签簇，再另开 tree 去向实验。

## 19. P1：词汇辨析（混合词性）

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

## 20. P2：介词（短语）辨析

老师定义明确限定为非复合单选、多个介词/介词短语选项的辨析。当前完整复核发现 DS 同时存在两类问题：

- 复合题小题因只看介词语义而被误判 true；
- `by 5 o'clock`、`provide ... with`、`help ... with` 等单选固定搭配因“还有其他考点”而被误判 false。

### 实验 P2：route 前置 + 共标提示对照

1. 先按最终 source 的 `parent × 单选题 × 选择题` 构造实验子集；其他 route 只进入 quarantine，不删标。
2. 使用明确允许“固定搭配义可与动词短语/情态等共标”的提示，运行 50--100 条对照小批。
3. 对新 prompt 的 true、false 各抽 12 条人审；false 不通过时只能保持 hold。
4. true 12/12 后，才允许该 route 构建全量 DS packet；全量 true 再独立抽 60 条。

## 21. P1：词汇（音/形/义）填空族

| 标签 | 初筛 signal | 已知判别器问题 | 实验重点 |
|---|---:|---|---|
| 介词（短语）的音/形/义 | 157/500 true | `at last`、`in the end`、`without` 等固定搭配被误删 | 明示“填空实际写出介词即应共标” |
| 副词（短语）的音/形/义 | 205/500 true | 固定副词短语被误删，单选副词辨析被误放行 | 填空与单选 route 对照 |
| 动词（短语）的音/形/义 | 194/500 true | 时态、动名词、搭配、翻译共标被误删；部分 true 题面不足 | 先输入完整性分流，再验证“写出动词”规则 |
| 名词（短语）的音/形/义 | 297/500 true | 完形、复数、固定搭配中的名词被误删 | 明示不以“是否唯一主考点”排除 |
| 形容词（短语）的音/形/义 | 211/500 true | 派生/固定搭配导致 false | 填空 route 下的共标提示 |

这一族优先做一个共享 prompt 对照实验，但每个末级标签仍单独计算 500 产量、true/false 人审和 policy；不能因为它们都叫“音/形/义”合并放行。

## 22. 已有可用数据与仍需警惕的问题

名词、副词、动词、形容词（短语）辨析已完成正例 12/12 校准，并已生成各自 `parent × 单选题 × 选择题` 的 DS 待验证 packet。它们不是“干净数据完成版”：四个标签合计还有 24,798 条历史记录因 route 与老师定义冲突而进入 quarantine，后续要等题型链路确认后处理。

它们当前的合法用途仅是：服务恢复后按标签独立跑 DS、从 true 产出 preliminary silver、再做每标签独立 60 条复核。它们的 false 和 route quarantine 都不自动删除。

## 23. 每次新增问题标签必须填写的字段

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

## 24. P0：厌烦

### 24.1 事实画像与可审计证据

目标标签为 `知识点@语用@情感@厌烦`。网页 GPT 已完成该标签 mentor 明细的原始直审，且 `113/113` 条通过 `question_id + parent_id` 对齐：

```text
english-knowledge-tagger-runtime/知识点_语用_情感_厌烦.jsonl
english-knowledge-tagger-runtime/web-gpt-reviews/boredom-20260831/
├─ evidence.jsonl
└─ summary.json
```

| 证据切片 | keep | remove | uncertain | 解读 |
|---|---:|---:|---:|---|
| 网页 GPT 全部 113 条 | 36 | 61 | 16 | 标签主体存在，但历史误标比例高，不能直接发布 |
| mentor direct `match` 29 条 | 26 | 3 | 0 | DS true 基本可靠，但样本过小，不能单独放行 |
| mentor direct `mismatch` 84 条 | 10 | 58 | 16 | DS false 主要对应真实误标，也仍含 10 条有效强厌烦题 |
| `child × 复合题 × 听力单选` | 3 | 27 | 0 | 最大误标簇；必须看到具体听力子题，不得按父题题型一刀切 |
| `parent × 单选题 × 听力单选` | 13 | 10 | 1 | 同一题型下保留和误标并存，必须按情感语义判断 |
| `parent × 单选题 × 选择题` | 12 | 6 | 0 | 可作为完整文本的校准 route |
| 复合题父题且缺小题/音频/图片 | 0 | 0 | 16 | 材料不足，继续 hold |

### 24.2 根因、处理结论与禁止动作

当前证据表明，核心问题是**把任意负面评价或情感词当成“厌烦”**。可保留的题必须直接要求识别或表达强烈厌烦/无法忍受，例如 `can't stand`、`tired of`、`boring/bored`、`hate`、`annoyed`，或噪声等造成无法忍受的明确语境。普通不喜欢、不开心、生气、身体疲劳、学习难度评价以及不以情感为考点的信息题，均不应保留本标签。

当前处置为 `p0_remediation`。禁止：直接删除 61 条网页 GPT remove；直接发布 36 条 keep；将“听力单选”或任何单一路由设为自动删/留规则；将 16 条缺上下文记录交给 tree 或强行补标。

### 24.3 Prag-Boredom-1：强厌烦意图判别器校准

1. 从 61 条可读 remove 中按 `child × 复合题 × 听力单选`、`child × 复合题 × 情景运用/补全对话`、`parent × 单选题 × 听力单选/选择题` 分层抽取，形成至多 60 条固定种子的盲审包；另从 36 条 keep 抽 12 条回归控制。16 条 uncertain 排除。
2. 盲审和 DS prompt 均只问“说话人是否明确表达强烈厌烦或无法忍受，且该意图是否决定答案”，禁止把普通负面情绪、难度、愤怒或疲劳视作等价物；记录完整对话/音频文本可用性。
3. DS 恢复后，在同一盲审包、同一温度下对照原释义和压缩释义，输出 keep/remove/uncertain、route、材料状态与请求耗时；不得让模型输出替换标签。
4. 只有 DS 与独立盲审在各 route 的方向一致，且明确 remove 簇可复现，才生成人工待确认的 patch candidate。随后仍需对全量 true 独立随机抽 60 条复核，满足门禁才可能进入 released silver。

## 25. P0：时段

### 25.1 事实画像与可审计证据

目标标签为 `知识点@语用@时间@时段`。网页 GPT 已完成 mentor 500 条明细的原始直审，并通过 `500/500` 条 `question_id + parent_id` 对齐：

```text
english-knowledge-tagger-runtime/知识点_语用_时间_时段.jsonl
english-knowledge-tagger-runtime/web-gpt-reviews/time-span-20260831/
├─ evidence.jsonl
└─ summary.json
```

| 证据切片 | keep | remove | uncertain | 解读 |
|---|---:|---:|---:|---|
| 网页 GPT 全部 500 条 | 329 | 15 | 156 | 标签主体有效，但材料缺失比例高，标签级结论为 `hold` |
| mentor direct `match` 129 条 | 121 | 0 | 8 | DS true 基本有效；8 条仍因材料/来源问题不能确认 |
| mentor direct `mismatch` 371 条 | 208 | 15 | 148 | DS false 中仍有大量明确时间题，不能将 false 当删除名单 |
| `parent × 单选题 × 听力单选` | 234 | 10 | 47 | 数量最大；音频问题缺失时无法可靠判断是否考查时间 |
| `parent × 复合题 × 听力单选` | 15 | 0 | 96 | 复合题父题几乎都缺具体小题，必须补材料后复核 |
| `parent × 单选题 × 选择题` | 40 | 1 | 0 | 可作为完整文本的校准 route |

### 25.2 根因、处理结论与禁止动作

当前证据表明，老师对“时段”的定义本身较宽，不应只限制为 `How long`：`When`、日期/星期/月、`for/since`、`How soon` 的 `in + 时间段`、`take/spend` 时长均可属于本标签。明确误标主要是活动、地点、主题、交通方式或纯时态题；另有 154 条 `insufficient_context` 与 2 条 `definition_conflict`，不能靠猜测处理。

当前处置为 `hold`。禁止：直接删除 15 条网页 GPT remove；直接发布 329 条 keep；把听力单选或复合题父题设为自动规则；把 156 条 uncertain 送入 tree 或以选项中出现时间词强行补标。

### 25.3 Prag-TimeSpan-1：时间表达与语用时段判别校准

1. 先从 mentor/原始数据补齐 `parent × 单选题 × 听力单选` 和 `parent × 复合题 × 听力单选` 的音频文本、具体小题、答案及图片；补不齐的 156 条维持 hold。
2. 对 15 条 remove 按“活动/地点/主题/交通/纯时态”分层全部保留进盲审，同时从 329 条 keep 按 `When`、`How long`、`How soon`、日期/星期、`for/since`、`take/spend` 等表达各抽控制样本，目标至多 `60 remove + 12 keep`。
3. DS 恢复后，在固定样本、同一温度和原/压缩释义两种 prompt 下比较；判定依据必须是“时间/时段信息是否直接决定答案”，不因时间词在背景文本中出现而保留。
4. 只有完整材料下 DS 与独立盲审在各 route 方向一致，才可生成 patch candidate；全量 true 仍需独立抽 60 条复核后才可能进入 released silver。

## 26. P1：介绍

### 26.1 事实画像与可审计证据

目标标签为 `知识点@语用@社会交往@介绍`。网页 GPT 已完成 mentor 500 条明细的原始直审，并通过 `500/500` 条 `question_id + parent_id` 对齐：

```text
english-knowledge-tagger-runtime/知识点_语用_社会交往_介绍.jsonl
english-knowledge-tagger-runtime/web-gpt-reviews/prag-introduce-20260831/
├─ evidence.jsonl
└─ summary.json
```

| 证据切片 | keep | remove | uncertain | 解读 |
|---|---:|---:|---:|---|
| 网页 GPT 全部 500 条 | 325 | 0 | 175 | 完整题面与标签一致，但材料缺失比例高，标签级结论为 `hold` |
| mentor direct `match` 132 条 | 128 | 0 | 4 | DS true 基本有效 |
| mentor direct `mismatch` 368 条 | 197 | 0 | 171 | 大部分无法判断来自缺小题/答案/音频，不应视为正例或反例 |
| `parent × 单选题 × 补全对话` | 84 | 0 | 0 | 完整对话下可稳定覆盖介绍类基本信息 |
| `parent × 补全题 × 补全对话` | 91 | 0 | 0 | 完整题面下可作为正例回归 route |
| `parent × 复合题 × 听力单选` | 1 | 0 | 160 | 主要缺少具体小题或音频文字，不能自动放行 |

### 26.2 根因、处理结论与禁止动作

老师释义对“介绍”的覆盖较宽：姓名、身份、家庭关系、外貌、兴趣、学校生活、日常活动、地点、数量以及文化常识等基本信息问答都可以纳入。当前没有证据表明这些完整题面是错标；问题集中在复合题父题和听力记录缺少决定性材料，导致 175 条无法判断。

当前处置为 `hold`，而不是 P0 全量纠错。禁止：把 175 条 uncertain 当作错误或正例；仅凭 `听力单选`/`复合题` 路由自动删除或保留；直接发布 325 条 keep 为 released silver。

### 26.3 Prag-Introduce-1：补齐材料后的正例稳定性校准

1. 优先从 mentor/原始数据补齐 `parent × 复合题 × 听力单选` 的具体小题、选项、答案和音频文字；补不齐的 175 条继续 hold。
2. 对已完整的 `parent × 单选题 × 补全对话`、`parent × 补全题 × 补全对话` 及少量普通单选，按姓名/身份、关系、外貌兴趣、活动地点、数量、文化常识分层抽取至多 36 条正例回归；若需要反例，使用相邻“描述/问候/普通信息”标签而不是伪造 remove。
3. DS 恢复后做原释义与压缩释义对照，判定标准为“介绍类基本信息是否直接决定答案”，同时记录材料完整性和 route；不输出替换标签。
4. 只有补齐材料后的独立盲审稳定且 DS 不再系统漏判，才可对该标签全量 true 做独立 60 条复核；在此之前不生成删除 patch。

## 27. P0：现在完成时与过去完成时的区别

### 27.1 事实画像与可审计证据

目标标签为 `知识点@语法词法@动词时态@时态辨析@现在完成时与过去完成时的区别`。网页 GPT 已完成 mentor 明细的原始直审，并通过 `134/134` 条 `question_id + parent_id` 对齐。源包中有 1 条历史 `llm_match: null`（mentor 自身解析不可用），分析器将其记为 `unavailable`，没有把它伪装成 DS mismatch：

```text
english-knowledge-tagger-runtime/知识点_语法词法_动词时态_时态辨析_现在完成时与过去完成时的区别.jsonl
english-knowledge-tagger-runtime/web-gpt-reviews/tense-perfect-contrast-20260831/
├─ evidence.jsonl
└─ summary.json
```

| 证据切片 | keep | remove | uncertain | 解读 |
|---|---:|---:|---:|---|
| 网页 GPT 全部 134 条 | 90 | 27 | 17 | 标签主体存在，但有相邻时态和复合题污染；标签结论为 `p0_remediation` |
| mentor direct `match` 36 条 | 36 | 0 | 0 | DS true 全部被网页 GPT 保留，正例精度较高但样本小 |
| mentor direct `mismatch` 97 条 | 54 | 26 | 17 | DS false 中仍有大量有效辨析题，不能直接删除 |
| mentor direct `unavailable` 1 条 | 0 | 1 | 0 | mentor 自身解析失败，单独记录，不纳入 match/mismatch 比例 |
| `parent × 单选题 × 选择题` | 60 | 10 | 1 | 最大且最稳定的校准 route |
| `child × 复合题 × 语法选择` | 2 | 10 | 0 | 复合题小题常被大题其他时态标签污染 |
| 复合题父题/缺具体小题 | 0 | 0 | 13 | 信息不足，继续 hold |

### 27.2 根因、处理结论与禁止动作

可保留的题必须让**现在完成时与过去完成时的参照点差异直接决定答案**：例如 `for/since` 延续到现在，或 `before/when` 与另一个过去事件构成“过去的过去”，并且选项/解析确实在两种完成时之间作出选择。明确误标集中在将来完成时、完成进行时、其他语法小题、开放写作、固定表达以及仅把完成时当篇章背景的复合题。另有 3 条定义/来源冲突和 14 条材料不足记录。

当前处置为 `p0_remediation`。禁止：直接删除 27 条网页 GPT remove；直接发布 90 条 keep；把任何单一完成时形式题自动视为“时态辨析”；把 17 条 uncertain 或 1 条 unavailable 送入 tree。

### 27.3 Tense-Perfect-Contrast-1：完成时对比边界校准

1. 将网页 GPT 标出的 3 条老师边界题（`2141148818170523648`、`2787888950607196161`、`2139847999682088960`）提交老师，冻结“单一完成时 vs 两种完成时竞争”的业务口径。
2. 从 27 条 remove 按将来完成/完成进行、其他语法小题、写作/篇章背景、固定表达分层抽取，构成最多 27 条 remove 审核集；从 90 条 keep 按“for/since 延续现在”“过去的过去”“直接选项对比”抽 12 条 keep 控制。
3. DS 恢复后，在固定样本、同一温度和原/压缩释义 prompt 下对照；只判定当前标签是否合理，不要求模型输出替换标签，并记录 `unavailable`/材料不足状态和耗时。
4. 只有老师边界冻结、DS 与独立盲审方向一致，才可对同质 route 收集全量 true，并对全量 true 独立抽 60 条复核；其余错误簇另开 tree 去向实验。

## 28. P0：责备

### 28.1 事实画像与可审计证据

目标标签为 `知识点@语用@情感@责备`。网页 GPT 已完成 mentor 257 条明细的原始直审，并通过 `257/257` 条 `question_id + parent_id` 对齐：

```text
english-knowledge-tagger-runtime/知识点_语用_情感_责备.jsonl
english-knowledge-tagger-runtime/web-gpt-reviews/blame-20260831/
├─ evidence.jsonl
└─ summary.json
```

| 证据切片 | keep | remove | uncertain | 解读 |
|---|---:|---:|---:|---|
| 网页 GPT 全部 257 条 | 97 | 109 | 51 | 标签存在明显历史过标，标签级结论为 `p0_remediation` |
| mentor direct `match` 70 条 | 63 | 6 | 1 | DS true 大多有效，但不是无错正例 |
| mentor direct `mismatch` 187 条 | 34 | 103 | 50 | DS false 以误标为主，但仍有 34 条有效责备题，不能整批删除 |
| `child × 复合题 × 听力单选` | 17 | 30 | 6 | 责备意图与普通听力细节混淆，需具体对话/音频 |
| `child × 复合题 × 其它` | 3 | 36 | 0 | 明确误标集中在非目标言语行为或背景信息 |
| `parent × 单选题 × 选择题` | 36 | 5 | 1 | 可作为完整文本的校准 route |
| 复合题父题/缺音频或小题 | 0 | 0 | 19 | 材料不足，继续 hold |

### 28.2 根因、处理结论与禁止动作

可保留的题必须直接表达或识别责备、批评、谴责、反问质问或对责备的道歉/改正回应，例如 `It serves you right`、`That's no excuse`、`How could you ...?`、`What a mess/waste/shame` 等。普通生气、建议、提醒、偏好、地点人物等听力信息、语法造句或仅作为剧本背景的负面语句，不应继承本标签。

当前处置为 `p0_remediation`。禁止：直接删除 109 条网页 GPT remove；直接发布 97 条 keep；把“听力单选”或出现 `angry/sorry` 设为自动规则；将 51 条 uncertain 送入 tree 或强行补标。

### 28.3 Prag-Blame-1：责备言语行为判别校准

1. 从 109 条 remove 按普通生气/建议提醒/听力事实信息/语法造句/背景文本及 route 分层抽取，构成最多 60 条 remove 盲审；从 97 条 keep 按直接责备、反问谴责、责备回应各抽控制样本，目标 12 条 keep。
2. 盲审只判断“责备言语行为是否直接决定当前题目答案”，不把情绪强度、`sorry` 或 `angry` 单独视为责备；听力题必须具备完整对话或可用音频文字。
3. DS 恢复后，在固定样本、同一温度和原/压缩释义 prompt 下对照，记录 route、材料状态、keep/remove/uncertain 与请求耗时；不输出替换标签。
4. 只有 DS 与独立盲审在各言语行为簇方向一致，才生成待人工确认的 patch candidate；全量 true 仍需独立抽 60 条复核后才可能进入 released silver。

## 29. P1：一般过去时的肯否疑

### 29.1 事实画像与可审计证据

目标标签为 `知识点@语法词法@动词时态@一般过去时@一般过去时的肯否疑`。网页 GPT 已完成 mentor 500 条明细的原始直审，并通过 `500/500` 条 `question_id + parent_id` 对齐：

```text
english-knowledge-tagger-runtime/知识点_语法词法_动词时态_一般过去时_一般过去时的肯否疑.jsonl
english-knowledge-tagger-runtime/web-gpt-reviews/past-tense-affirmative-negative-question-20260831/
├─ evidence.jsonl
└─ summary.json
```

| 证据切片 | keep | remove | uncertain | 解读 |
|---|---:|---:|---:|---|
| 网页 GPT 全部 500 条 | 463 | 8 | 29 | 标签主体稳定，但标签级结论为 `hold` |
| mentor direct `match` 137 条 | 134 | 0 | 3 | DS true 基本有效 |
| mentor direct `mismatch` 363 条 | 329 | 8 | 26 | DS false 中仍有大量有效过去时题，不能当删除名单 |
| `parent × 单选题 × 选择题` | 200 | 2 | 1 | 最大且较稳定的校准 route |
| `parent × 填空题 × 单词拼写` | 89 | 1 | 5 | 多数由过去式/过去分词形式或时间参照直接决定 |
| `parent × 填空题 × 完成句子` | 73 | 0 | 1 | 多数由 did/didn’t 或 was/were 结构直接决定 |
| 复合题父题及缺时间参照 | 0 | 0 | 22 | 信息不足，继续 hold |

### 29.2 根因、处理结论与禁止动作

可保留的题必须让一般过去时的肯定、否定或疑问形式直接决定答案，例如过去时间标志、`did/didn’t + 动词原形`、`was/were` 或相应过去式。明确误标主要是 `couldn’t` 等情态动词、一般现在时、现在完成时/过去分词以及纯阅读内容题；另有 1 条来源答案与 `did + 动词原形` 规则冲突的边界记录和 28 条材料不足记录。

当前处置为 `hold`，不是直接放行。禁止：直接删除 8 条网页 GPT remove；直接发布 463 条 keep 为 released silver；把所有含 `yesterday` 的题自动保留；将 29 条 uncertain 送入 tree 或强行补标。

### 29.3 Tense-Past-1：过去时肯否疑边界校准

1. 先提交老师裁决边界题 `2725366621974073347`，确认题面答案、解析与 `did + 动词原形` 的优先级。
2. 对 8 条 remove 按情态动词、一般现在时、完成时/过去分词、纯阅读内容分层全部复核；从 463 条 keep 按肯定式、`did/didn’t` 疑问否定、`was/were` 各抽控制样本，目标 `8 remove + 12 keep`。
3. DS 恢复后，在固定样本、同一温度和原/压缩释义 prompt 下对照；判定“过去时形式是否直接决定答案”，不把过去时间背景单独当作充分证据。
4. 只有老师边界冻结且 DS 与独立盲审一致，才可对完整 route 收集全量 true，并独立抽 60 条复核；29 条材料不足样本保持 hold。

## 30. P1：集合名词

### 30.1 事实画像与可审计证据

目标标签为 `知识点@语法词法@名词@集合名词`。当前源包共 377 条，mentor DS 初筛 `match=true` 为 104 条（27.6%）。本次网页 GPT 只复核了其中 128 条，不能把该子样本外推为 377 条全量结论；另有 24 条历史完整题面校准样本，也只作边界参考：

```text
english-knowledge-tagger-runtime/知识点_语法词法_名词_集合名词.jsonl
english-knowledge-tagger-runtime/web-gpt-reviews/collective-noun-20260831/
├─ source_subset.jsonl（从 377 条源包按本次复核 ID 派生）
├─ evidence.jsonl
└─ summary.json
docs/knowledge-label-calibration-reviews-full-sample.md（仅作 24 条历史校准参考）
```

| 证据切片 | keep | remove | uncertain | 解读 |
|---|---:|---:|---:|---|
| mentor 源包 377 条 | 104 match | 273 mismatch | — | 仅为 DS 初筛，不是真实标签准确率 |
| 网页 GPT 子样本 128 条 | 41 | 83 | 4 | 外部证据，不是 377 条全量金标；本次没有标签级结论行 |
| 子样本中 mentor direct `match` 39 条 | 36 | 3 | 0 | DS true 在该子样本中大多有效，但样本选择可能有偏 |
| 子样本中 mentor direct `mismatch` 89 条 | 5 | 80 | 4 | DS false 以误标为主，但仍有 5 条有效，不能直接批量删除 |
| 24 条历史校准中的 DS `match=true` | 9 | 3 | 0 | 仅作为边界参考；`sheep`、`staff`、`hair` 等概念过宽 |
| 24 条历史校准中的 DS `match=false` | 0 | 12 | 0 | 仅作为边界参考，不能外推到 273 条全量 mismatch |
| `parent × 单选题 × 选择题` | 49 match | 80 mismatch | — | 数量最大，混有普通名词数/词义题 |
| `parent × 填空题 × 单词拼写` | 16 match | 87 mismatch | — | 只有集合主语一致真正命中；多数是普通拼写/复数 |
| `parent × 填空题 × 翻译题` | 15 match | 8 mismatch | — | `staff/family/police` 主语一致可保留，需看答案与解析 |
| `child × 复合题/完形填空 × 语法选择` | 7 match | 37 mismatch | — | 复合题中只有具体小题考集合主语一致才保留 |

### 30.2 根因、处理结论与禁止动作

老师释义的必要条件是：集合名词作主语，并且题目必须根据“整体”还是“成员”选择谓语单复数；`family/class/team/group/government/crowd` 以及本身表复数的 `police/people/cattle` 是典型例子。`sheep` 单复同形、`furniture/hair` 不可数、`The Greens` 姓氏复数、普通复数和集合名词作宾语，不能仅因词汇相关而标注。

本次 128 条子样本的主要误标原因已具体化为：普通数词/复数（30）、纯词形或拼写（27）、物主/限定词（8）、不可数/物质名词（5）、固定短语（5）以及其他背景（7）；有效样本主要是集合名词整体/成员意义或本身表复数时对谓语形式的直接约束。当前处置仍为 `hold`。禁止：把 104 条 DS true 全部当作正例；把 273 条 DS false 全部删除；把出现 `family/staff/people` 或复数谓语作为自动触发；将复合题父题标签继承给没有具体集合主语一致考点的小题。

### 30.3 Noun-Collective-1：集合名词主谓一致分层复核

1. 先按 CSV 允许题型筛选 `parent × 单选题 × 选择题`、`parent × 填空题 × 单词拼写/语法填空`、`child × 复合题 × 语法选择` 等合法 route；翻译、完形及其他 route 只作边界样本，不自动排除。
2. 从本次 83 条 remove 候选中按“普通数词/复数、词形拼写、物主限定词、不可数/物质名词、固定短语、其他背景”分层抽取至多 60 条；从 41 条 keep 中按“整体/成员意义”“本身表复数”“集合形式选择”抽 12 条控制。
3. DS 恢复后，对固定样本做原释义/压缩释义对照；判定必须同时满足“集合名词作主语”和“谓语单复数由其意义决定”，只考拼写、普通词义或一般复数不保留。
4. 小批方向稳定后，对该标签全量候选再独立抽 60 条复核；在此之前不生成删除或替换 patch，也不把 24 条校准样本当成 released silver。

## 31. 当前执行顺序

1. **互联通讯 / Theme-1**：现在离线构造 60 条 tree 任务包；DS 恢复后运行并按候选叶子/`uncovered` 分簇复核。这是当前最靠前、无需等待老师才能准备的 P0。
2. **时间-顺序 / Order-1**：现在离线构造 `60 remove + 12 keep` 的 tree 任务包；DS 恢复后按候选叶子/`uncovered` 与音频文本状态分簇复核。
3. **社会交往-争辩 / Argument-1**：现在离线构造 `60 remove + 12 keep` 的 tree 任务包；DS 恢复后按候选言语行为/`uncovered` 与父子题 route 分簇复核。
4. **社会交往-描述 / Description-1**：现在离线构造 `41 remove + 12 keep` 的 tree 任务包；81 条信息不足题保持 hold。
5. **社会/政治/历史的变迁与发展 / Historical-Change-1**：现在离线构造 `60 remove + 12 keep` 的 tree 任务包；4 条材料不足题保持 hold。
6. **主语 / Subject-1**：现在离线构造 `60 remove + 12 keep` 的 tree 任务包；12 条信息不足题保持 hold。
7. **存在 / Existence-1**：现在离线构造 `60 remove + 12 keep` 的 tree 任务包；117 条信息不足题保持 hold。
8. **一般将来时的肯否疑 / Future-1**：向老师提交 2 条边界题；裁决后构造 36 条 route 分层盲审包，DS 恢复后做原/压缩释义对照。
9. **主系表 / SVC-1**：现在构造 36 条 route 分层盲审包，DS 恢复后做原/压缩释义对照；17 条信息不足题保持 hold。
10. **厌烦 / Prag-Boredom-1**：现在构造 `60 remove + 12 keep` 的语用意图盲审包；DS 恢复后做原/压缩释义对照，16 条材料不足样本保持 hold。
11. **时段 / Prag-TimeSpan-1**：先补齐听力/复合题材料，再构造 `60 remove + 12 keep` 分层盲审包；156 条材料不足或来源冲突样本保持 hold。
12. **介绍 / Prag-Introduce-1**：先补齐复合题/听力材料，再对完整题面构造最多 36 条正例回归；175 条材料不足样本保持 hold。
13. **现在完成时与过去完成时的区别 / Tense-Perfect-Contrast-1**：向老师提交 3 条边界题；裁决后构造最多 `27 remove + 12 keep` 分层盲审包，DS 恢复后做原/压缩释义对照。
14. **责备 / Prag-Blame-1**：现在构造最多 `60 remove + 12 keep` 言语行为分层盲审包；51 条材料不足样本保持 hold。
15. **一般过去时的肯否疑 / Tense-Past-1**：提交 `2725366621974073347` 给老师，构造 `8 remove + 12 keep` 小批复核；29 条材料不足样本保持 hold。
16. **集合名词 / Noun-Collective-1**：按合法题型与主谓一致触发抽取分层样本；完成小批后再决定是否扩大全量。
17. **一般现在时与现在进行时的区别 / Tense-Contrast-1**：向老师提交 5 条边界题；裁决后构造 `60 remove + 12 keep` 根因分层盲审包，DS 恢复后做原/压缩释义对照。
18. **现在进行时的肯否疑 / NP1**：向老师提交 `3125582210285723648`、`2139891546877726720`；裁决后构造 36 条盲审包，DS 恢复后做原/压缩释义对照。
19. **谓语 / Predicate-1**：向老师提交 `2785362399957475328`；裁决后构造 36 条盲审包，DS 恢复后做原/压缩释义对照。
20. **及物动词 / V1**：向老师提交第 5.5 节的 7 条边界题；收到裁决前不生成任何清洗 patch。
21. **过去进行时的肯否疑 / PP1**：向老师提交 `3105096983930556416`；裁决后先构造 36 条盲审包，DS 恢复后再做原/压缩释义对照。
22. **转化法 / Conv-Policy-0**：T1/T1.1 已失败，停止此标签 whole-tree；使用 conversion-vs-derivation-v1 验证“词形是否不变”的人工/规则分流字段，`3348636953588649985` 继续独立裁决。
23. **其余 P0**：严格按第 3.1 节顺序，每次只启动一个 `*-0` 离线分诊；完成一个标签的“根因 + 唯一下一实验 + 门禁”后才开下一个。
24. **混合词性 M1**：已有盲审包，可与上述离线分诊并行；仍禁止全量。
25. **介词辨析 P2 与音/形/义填空族 P1**：只在对应 P0 不阻塞时运行 route / prompt 对照；每个末级标签单独验收。

任何一项实验未达到人工验收条件，都保留 audit 和 hold 证据，不能为了补量将其混入 `hq-v*`。
