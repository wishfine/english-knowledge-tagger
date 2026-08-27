# 初中英语题型与知识点数据清洗手册

> 版本：v1.0（2026-08-26）
>
> 适用范围：中学英语题目“题型方法 + 知识点”回标、质量筛选与生成式 SFT 数据构建
> 当前主线：**逐个末级知识点标签验证历史标签是否正确，先积累可审计 silver 数据；再用错误与漏标难例定向补数。**

本手册是项目后续协作的唯一执行基线。它不要求先把三百多万条历史题目全部重洗，也不允许用任何模型输出直接覆盖源标签。每次只推进一个或一组业务同质的末级知识点，保留完整证据、抽检结果和版本信息。

---

## 目录

1. [目标、范围与不做什么](#1-目标范围与不做什么)
2. [当前数据与术语](#2-当前数据与术语)
3. [不可违反的业务规则](#3-不可违反的业务规则)
4. [数据层、状态与产物](#4-数据层状态与产物)
5. [全流程总览](#5-全流程总览)
6. [阶段 0：冻结输入、taxonomy 与血缘](#6-阶段-0冻结输入taxonomy-与血缘)
7. [阶段 1：大题/小题题型路由](#7-阶段-1大题小题题型路由)
8. [阶段 2：逐末级知识点直接判别](#8-阶段-2逐末级知识点直接判别)
9. [阶段 3：标签校准与保守 silver 分流](#9-阶段-3标签校准与保守-silver-分流)
10. [阶段 4：题级 silver 组装](#10-阶段-4题级-silver-组装)
11. [阶段 5：处理 false、错标与漏标](#11-阶段-5处理-false错标与漏标)
12. [阶段 6：从 silver 到 HQ 与 SFT](#12-阶段-6从-silver-到-hq-与-sft)
13. [逐标签运行手册](#13-逐标签运行手册)
14. [指标、抽检与发布门禁](#14-指标抽检与发布门禁)
15. [性能、成本与并发观测](#15-性能成本与并发观测)
16. [问题簇、版本与协作交接](#16-问题簇版本与协作交接)
17. [当前优先级与待决事项](#17-当前优先级与待决事项)

---

## 1. 目标、范围与不做什么

### 1.1 最终目标

训练一个生成式多模态英语打标模型。输入是题目文本、题图、必要父题上下文、选项、答案和解析；输出为结构化的“题型方法 + 知识点”标签集合。正式模型路线为 `Qwen3-VL-8B-Instruct` 的 BF16 全参 SFT；训练在高质量数据和冻结评测集完成前不启动。

训练质量的最大风险不是少打一个标签，而是错打标签：

- **漏标**：相似题或错题推荐可能漏掉一部分题，但通常仍能推荐到其他相近题；
- **错标**：会把与真实薄弱点无关的题推荐给学生，业务伤害更大。

因此，本流程的优先级始终是：

```text
先降低错标 → 再处理漏标 → 再扩充长尾覆盖 → 再放大训练规模
```

### 1.2 本期范围

本期包含：

1. 大题与小题题型标签的审计和路由；
2. 小题历史知识点的逐末级标签正确性判别；
3. 大题知识点的独立处理（不从小题反推）；
4. 规则、模型候选、人工抽检、patch 和数据版本的可追溯记录；
5. 从候选标签证据构造 `silver`，再构造冻结的 `hq-v*` 数据集；
6. 使用模型错误切片持续补数。

### 1.3 明确不做的事

以下行为禁止：

- 不对三百多万历史题进行“无抽检的一次性全量重标”；
- 不用 DS-V4、Doubao、Gemini 或任何模型结果直接覆盖源 JSONL；
- 不把 `match=true` 当作真值或模型准确率；
- 不把小题自动继承父题的语篇、词汇、语法知识点；
- 不把 `知识点@空` 当作一个真实类别；
- 不因阅读类题型名称相似就全局判定“小题一定不打知识点”；
- 不让同一题或相近题跨训练与评测集合（HQ/SFT 阶段执行）；
- 不在未冻结老师规则本、人工抽检和版本 manifest 前启动正式全参训练。

---

## 2. 当前数据与术语

### 2.1 当前正式上游源

当前上游源是 mentor 提供的增强版 JSONL：

```text
/local_data/zhangyonglin/english-knowledge-tagger-data/sources/
  cleaned_final_enhanced_v2.jsonl
```

已核验信息：

| 项目 | 值 |
|---|---|
| 行数 | 3,203,122 |
| 大小 | 约 4.3 GB |
| SHA-256 | `995191fb78f9ef0b9e9958563704b8d3bd2752809ef838815c443a80fe2b77ec` |
| 上游增强 | 音频提示与时长、图片选项占位符、补充长尾数据 |

其中：

- 音频题在文本中标记“本题题干中包含音频内容”，已知时带音频片段时长；
- 所有选项为图片时，选项文本会用“图片A/B/C/D”占位；
- 图片、音频文本化并不等价于题目内容已完整可判。依赖具体图片或缺失听力文本的题仍需隔离或走视觉模型链路。

源文件是 `legacy`，只读且可能有错标、漏标、旧 taxonomy、题型录入错误和缺少多模态证据。后续所有结论只能写入新产物。

### 2.2 标签规则本与历史 taxonomy

版本化老师规则本：

```text
data/rulebooks/初中英语知识点题型方法释义.csv
```

它是新标签体系的唯一解释来源，当前包含：

- 386 个末级知识点条目；
- 190 个末级题型方法条目；
- 每个知识点的业务打标解读与压缩释义；
- 一部分“新题不再打”的停用/兼容标签说明。

历史源中见过的知识点路径约有 576 个，不能与规则本直接等同。原因包括旧根节点、旧命名、历史兼容标签和停用标签。代码中统一使用：

```text
历史渲染格式：知识点@词法@冠词@a/an的区别
canonical 格式：知识点->词法->冠词->a/an的区别
```

历史路径必须先经过版本化 migration，再根据老师 CSV 判为：

| taxonomy 状态 | 含义 | 后续处理 |
|---|---|---|
| `active` | 当前可用于新题的末级标签 | 可以进入验证与候选流程 |
| `deprecated` | 历史兼容/停用标签 | 不进入新训练标签；单独迁移或隔离 |
| `unmapped` | migration 后仍不在规则本 | taxonomy 问题，不能按内容正确/错误处理 |

### 2.3 基本术语

| 术语 | 定义 |
|---|---|
| 父题 / 大题 | `is_sub_question=false` 的题目；例如一篇阅读材料、完形材料、作文任务 |
| 小题 | `is_sub_question=true` 的题目；例如阅读材料下的一道选择题、完形的一空 |
| route | `scope × 题型结构 × 题型名称`，例如 `child × 复合题 × 语法选择` |
| 末级标签 | 老师 CSV 中可直接输出的终端知识点路径 |
| 直接判别 | 给定题目和一个历史末级标签，判断该标签是否确为解题必要知识点 |
| `silver_label_candidate` | 经人审校准 policy 放行的单标签正向证据，不是题级真值 |
| `silver_question_candidate` | 一题全部历史 active 知识点都获得正向证据的候选题，仍可能漏标 |
| `relabel_candidate` | 已被明确标记为需要进一步处理的错标候选，不能直接替换标签 |
| `hold` | 证据不足、未校准、输入不完整或存在冲突；不得进训练 |
| patch | 人工确认的 `keep/drop/replace/add` 变更记录 |
| HQ | 冻结、可复现、满足训练准入门槛的数据版本 |

---

## 3. 不可违反的业务规则

### 3.1 父题和小题是两个打标对象

父题与小题分别决定题型和知识点，不能把任何一方的全部标签复制给另一方。

典型规则：

| 题目类型 | 父题常见知识点 | 小题常见知识点 |
|---|---|---|
| 阅读理解 / 阅读还原 / 阅读匹配 | 语篇体裁、语篇主题、应有题型方法 | 由老师矩阵和实际小问决定；不能默认继承父题语篇标签 |
| 完形填空 | 语篇体裁、主题等父题信息 | 每一空可能是词法/句法，也可能按规则不单独打 |
| 语法选择（复合题小问） | 父题可有整体题型信息 | 对应具体语法点，通常至多 3 个 |
| 词汇单选 / 词汇填空 | 单题本身 | 词义、搭配、近反义、词形等解题必需点 |
| 听力 | 语用可选，题型按细分听力任务 | 听力细分题型必须打；知识点是否打取决于规则和有效文本 |
| 作文 | 一般不从小题语法标签反推 | 写作话题/体裁题型按老师规则 |

注意：“小题不继承父题”并不表示“小题没有知识点”。是否需要知识点必须由老师规则、已审批 route 和实际题面共同决定。

### 3.2 只标解题必要点，不标题面出现的所有点

判别时关注的是：学生正确解答该题必须使用什么知识点。不能因为题干或选项里出现一个结构，就把它当成考点。

例如：

- 题目考 `a/an`，题干含有名词复数，不应额外打“可数名词复数”，除非解析和答案显示它确为得分点；
- 比较级用法与比较级变化规则可能同时必要；若规则释义明确要求两者一起打，不能强迫模型二选一；
- 一道阅读题的小题答案依赖文章细节时，不能仅因文章中有定语从句、一般过去时而给小题打语法点；
- 题目使用 `on the Internet`，应按释义区分“地点介词”还是“其他介词/固定搭配”，不能只按表面单词匹配。

### 3.3 空、其他与停用标签

- `知识点@空` / `题型@空` 是缺失或无标签占位，不是模型分类类别；
- 真实 `知识点->其他` 是老师 taxonomy 中的业务标签，与树搜索控制项 `__NO_MATCH__` 不同；
- `__NO_MATCH__` 只用于候选树回退，永远不写入最终标签；
- 被标注“新题不再打”的标签不进入新训练集，也不能被自动当作“无知识点”。

---

## 4. 数据层、状态与产物

### 4.1 数据层定义

```text
legacy → audit → silver_label_candidate → silver_question_candidate
       ↘ hold / relabel_candidate → 人工复核 / patch
patch + legacy + 抽检 → hq-v* → 冻结 dev/test → SFT
```

| 层 | 可否训练 | 内容 | 关键限制 |
|---|---:|---|---|
| `legacy` | 否 | 上游源、历史 output | 可错标、漏标；只读 |
| `audit` | 否 | route、模型判别、树搜索、统计、抽检记录 | 用于定位问题，不等于真值 |
| `silver_label_candidate` | 仅辅助实验 | 一条历史标签经校准后正向通过 | 不能证明同题其他标签或漏标情况 |
| `silver_question_candidate` | 仅辅助实验 | 一题全部历史 active 标签正向通过 | 不能证明标签集合完整 |
| `relabel_candidate` | 否 | 已知/疑似错误的标签实例 | 仍需候选、人工或 patch |
| `patch` | 间接 | 人工批准的集合级变更 | 必须可追溯 |
| `hq-v*` | 是 | 冻结的训练数据版本 | 需要独立评测和质量门禁 |

### 4.2 每条产物必须保留的血缘

最少字段：

```text
question_id, parent_id, is_sub_question, source_line
source_path, source_sha256, source_version
原始 output, canonical 历史标签集合
老师规则本版本 / migration 版本 / policy 版本
模型名、endpoint 标识、prompt_version、run_id
人工审核批次、审核结论、审查人或审查来源
最终 disposition / patch action / 风险码
```

物理源行号与 source SHA 必须一起使用。仅有 `question_id` 不足以防止换源后把旧判别结果套到新题面。

### 4.3 推荐目录结构

运行产物不进 Git；代码、固定规则和说明文档进 Git。

```text
$RUNTIME/
  manifests/
  type-routing/<run-id>/
  direct-label/<label-or-batch>/<run-id>/
    raw/                         # 原始模型导出，只读
    normalized-evidence.jsonl
    silver-label-evidence.jsonl
    relabel-candidates.jsonl
    hold.jsonl
    gate.report.json
  flat-validation/<cluster>/<run-id>/
  knowledge-tree/<cluster>/<run-id>/
  silver/<batch-id>/
  hq/<version>/
```

建议一个运行 ID 同时包含任务、源版本和日期，例如：

```text
direct-label-知识点_词法_冠词_a-an-区别-v1-20260826-153000
```

---

## 5. 全流程总览

### 5.1 两条必须分开的链路

```text
链路 A：历史标签正确性（当前主线）
  题目 × 既有末级标签
      → 直接判别 true / false
      → 标签级人工校准
      → silver / hold / relabel

链路 B：标签集合补全与替换（只处理难例）
  false、未校准、候选不足、已知缺标、人工发现边界簇
      → flat 候选池或知识点树
      → 人工确认 keep/drop/replace/add
      → patch
```

链路 A 回答“旧标签是否可保留”；链路 B 回答“如果不能保留，应改为什么、还缺什么”。两者不能混用。

### 5.2 端到端顺序

1. 冻结源、规则本与 manifest；
2. 执行题型 inventory 与 route 审计；
3. 以**一个末级知识点标签**为单位，收集带该历史标签的题；
4. 运行直接判别器，得到 `match=true/false`；
5. 从 true 和 false 各抽样人工审核，填写该标签校准台账；
6. 仅对已经完成审核的标签写入稀疏 policy；
7. policy gate 将证据分为 silver / relabel / hold；
8. 将单标签证据按题组装，只有全标签覆盖的题成为 `silver_question_candidate`；
9. 将 false、hold、缺标和冲突按问题簇送入替换/补标链路；
10. 用人工 patch、独立评测和漏标控制构造 `hq-v*`；
11. SFT 后按评测错误切片定向补 2k–10k，始终混入旧 HQ 核心集。

---

## 6. 阶段 0：冻结输入、taxonomy 与血缘

### 6.1 每批运行前的检查

每个 batch 开始前必须记录：

```bash
export FINAL_SOURCE=/local_data/zhangyonglin/english-knowledge-tagger-data/sources/cleaned_final_enhanced_v2.jsonl
export TEACHER_CSV=data/rulebooks/初中英语知识点题型方法释义.csv
export KP_MIGRATION=configs/knowledge_taxonomy_migrations/legacy-rendered-to-teacher-v1.json

wc -l "$FINAL_SOURCE"
sha256sum "$FINAL_SOURCE"
sha256sum "$TEACHER_CSV" "$KP_MIGRATION"
git rev-parse HEAD
```

manifest 至少包含：

```json
{
  "source_path": "...",
  "source_sha256": "...",
  "teacher_csv_sha256": "...",
  "migration_sha256": "...",
  "git_commit": "...",
  "run_id": "...",
  "purpose": "direct terminal-label validation",
  "label_scope": "知识点->词法->冠词->a/an的区别"
}
```

### 6.2 taxonomy 预处理

对每个历史 `知识点@...`：

1. 转换为 `知识点->...` 形式；
2. 应用最长前缀 migration；
3. 查老师规则本是否存在；
4. 判断是否是当前 active 末级标签；
5. 保留原始路径、canonical 路径和 migration rule ID。

只有 canonical 且 active 的末级标签可以进入直接判别。其余情况的含义如下：

| 情况 | 处理 |
|---|---|
| 迁移成功，目标 active | 正常进入逐标签验证 |
| 迁移成功，目标 deprecated | 隔离为旧 taxonomy 迁移问题 |
| 无迁移、规则本不存在 | `unmapped_legacy_label`，不让模型猜新标签 |
| 历史 output 无可解析知识点 | 不等于正确空标签；按 route 和题面另行判断 |

### 6.3 释义质量分析

标签释义既是模型判断依据，也是业务边界的书面定义。每个标签在放大前至少检查：

1. 释义是否说明“什么情况下需要打”；
2. 是否清楚说明“不该打”的近似场景；
3. 是否给出有区分力的关键词、结构或例子；
4. 是否错误地把背景知识、题面词汇或常见形式写成必打条件；
5. 是否与兄弟标签、上位标签存在冲突或遗漏的共标关系。

建议维护以下关系表，而不是只依赖自然语言：

| 关系 | 示例用途 |
|---|---|
| 近似 / 易混淆 | `时间介词` 与 `地点介词`、`其他介词` |
| 可共标 | `比较级用法` 与 `比较级变化规则` |
| 互斥 | 同一特定结构下不可同时成立的细分标签 |
| 上下位 | 父节点一般不应与更具体末级重复输出，除非业务规则明确要求 |
| 停用替代 | 旧标签应迁移至哪个 active 标签，或仅作为历史兼容保留 |

---

## 7. 阶段 1：大题/小题题型路由

### 7.1 为什么题型路由仍然必要

虽然直接标签判别不再先受 route 候选前缀硬限制，题型仍决定：

- 大题与小题是否应分别打标签；
- 某类小题有没有知识点、是否 optional 或 forbidden；
- 该标签的错误主要集中在哪种业务场景；
- 哪些 false 应进入替换树，哪些仅是输入不完整；
- 如何做分层抽检和 SFT 评测切片。

### 7.2 route 的唯一键

```text
scope(parent | child) × declared_type_structure × declared_type_name
```

例如：

```text
child × 复合题 × 语法选择
parent × 补全题 × 阅读还原
child × 完形填空 × 语法选择
```

不要用模糊通配符，也不要因 route 未命中就沿用历史题型标签。历史题型只能作为证据。

### 7.3 route 处理步骤

1. 用 inventory 枚举所有父题/小题精确组合；
2. 对每个组合抽取隐藏历史 output 的盲审包；
3. 根据老师 CSV、业务矩阵和盲审，写入 versioned route policy；
4. 输出 `approved / needs_review / unmapped / legacy_type_*` 状态；
5. 对 approved route 明确知识点存在性：`required / optional / forbidden / unresolved`；
6. 用 route 切片统计直接判别的 true、false、hold 和人工准确率。

### 7.4 route 与知识点关系的当前原则

- `scope` 是直接判别证据的必填字段；
- route 是审计和后续处理维度；
- route 不得因为当前候选 policy 不包含某个标签，就否定该标签的直接判别；
- 发现一个标签在特定 route 系统性 false，不立即全局 drop；先判断是题型录入 bug、释义不适用、输入缺失还是标签确实错误。

题型映射细节见：[题型打标策略映射](type-policy-mapping.md)。

---

## 8. 阶段 2：逐末级知识点直接判别

### 8.1 单位与目标

当前高质量数据提取单位是：

```text
一道题 × 一个已有历史末级知识点
```

目标不是让模型在 386 或 576 个标签中选一个，而是验证已有标签：

> 结合题干、选项、答案、解析、必要上下文和目标标签释义，这个标签是否是正确解题所需的知识点？

这避免了大候选池选择对短期质量筛选造成的噪声，也使每一个标签都能独立测量模型可靠性和业务边界。

### 8.2 送入判别器的内容

对于文本充分的小题，发送：

1. 当前小题题干；
2. 选项；
3. 正确答案；
4. 解析；
5. 必要的父题材料或上下文；
6. 待验证的 canonical 末级标签；
7. 该标签的原始业务释义（必要时加压缩释义）；
8. 结构化输出约束。

默认从模型题面中移除上游渲染的：

```text
题型结构为：...
题型名称为：...
```

这些字段可以在本地作为审计维度，但不应让模型借脏题型元数据复述历史答案。

### 8.3 不送入直接判别器的内容

直接判别阶段不发送：

- 全部 386/576 个知识点；
- flat top-k 候选标签；
- 同级叶子列表；
- “请选择更好的替代标签”的要求；
- 父题的全部历史知识点。

这些内容属于 false/难例后的替换链路。直接判别只判断当前标签是否成立。

### 8.4 推荐输出契约

模型可以输出 `reason`、`confidence` 和证据片段辅助人工复核，但 gate 的唯一业务输入是结构化的 boolean `llm_match`。模型自身 confidence 不是放行条件。

推荐模型原始输出的语义：

```json
{
  "match": true,
  "confidence": "high",
  "reason": "解析表明空格考查 for + 时间段表示持续时间。",
  "evidence": ["six months", "for + 时间段"]
}
```

其中：

| 字段 | 用途 | 是否可自动放行 |
|---|---|---:|
| `match` | 当前标签是否合理 | 否，必须经校准 policy |
| `confidence` | 人工排序、模型异常分析 | 否 |
| `reason` | 抽检、释义调优、问题聚类 | 否 |
| `evidence` | 快速定位题面依据 | 否 |

不建议开启会显著增加延迟且难以结构化约束的长 thinking 输出。若模型服务支持 reasoning，优先关闭或限制为短结构化依据；业务判断仍应由最终 JSON 字段承载。

### 8.5 样本选择与批量大小

每个末级标签单独建立样本池：

```text
所有含该 canonical 历史标签的题
  → 去除 taxonomy 未映射、源信息严重缺失、重复或身份不一致题
  → 按 parent/child、route、文本/图文/音频、标签共现数分层
  → 单标签批量判别
```

当前 mentor 已按“每个最末级标签最多约 500 题”抽取并进行大规模判别。它是高效初筛，但不是最终清洗结论。

对于每个 label，人工审核至少分开抽样：

```text
llm_match=true  样本
llm_match=false 样本
```

两类都要看，因为 false 不必然表示历史标签错：模型可能漏判共标、过度追求“唯一主考点”、缺少图片/听力信息，或不理解释义边界。

### 8.6 全量 rollout 的优先级门槛

500 条初筛的 `match=true` 比例只用于判断一个标签是否值得优先投入全量模型成本；它不是标签正确率。前提是“每标签最多 500 条”的抽样是随机或稳定分层抽样，而不是文件前 500 条。

对某标签的初筛 `X ~ Binomial(n, p)`，使用**单侧 95% Wilson 下界**估计其 true 产量；只有满足下列条件才进入全量 rollout 队列：

```text
one-sided Wilson lower bound ≥ 70%
无服务/解析错误
match=true 样本数 ≥ 12
```

满 500 条时，至少 `367/500 = 73.4%` 才满足该下界；日常可用更容易理解的 `≥75%` 作为优先阈值。样本少于 500 时必须按实际 `n` 计算，不能机械套用 75%。通过产量门槛后，仍必须有 `true` 的 12 条人工复核全对，才能写入 `screened_12` preliminary policy。

第一批已完成 `true` 12/12 人审复核、可离线准备的标签为：

```text
名词（短语）辨析：448/500 = 89.6%，单侧 95% 下界 87.1%
副词（短语）辨析：439/500 = 87.8%，单侧 95% 下界 85.2%
动词（短语）辨析：429/500 = 85.8%，单侧 95% 下界 83.0%
形容词（短语）辨析：423/500 = 84.6%，单侧 95% 下界 81.8%
```

四个标签的人工 `true` 样本均为 `12/12 retain`，故其初始 policy 都只放行 positive `match=true` 为 `silver_label_candidate`；任何 false 都保持 `hold`。它们的 false 样本并非全部为错标，因此不能因为 `match=false` 自动删除。每个标签的全量运行完成后，必须分别从**新产生的 true** 中独立随机抽取 60 条做人工复核；60/60 retain 才能把该标签升级为 `released_post_sweep`。

#### mentor-direct-v1：名词（短语）辨析的首轮全量运行（示例）

这轮要复用 mentor 初筛时的 definition JSON 和 prompt 行为，不能换成另一套 prompt 后继续沿用原来的 12/12 校准结论。准备下列输入：

为保证可比性，`mentor-direct-v1` 会保留 `output_all` 作为模型输入中的历史标签上下文；这不是长期默认推荐的无锚定 prompt，而是本轮对已有 v1 校准结论的**冻结复现**。未来若改为不发 `output_all` 的 v2，必须重新做每标签 500 条初筛和 12/12 校准，不能沿用本轮 policy。

```bash
export FINAL_SOURCE=/local_data/zhangyonglin/english-knowledge-tagger-data/sources/cleaned_final_enhanced_v2.jsonl
export TEACHER_CSV=data/rulebooks/初中英语知识点题型方法释义.csv
export KP_MIGRATION=configs/knowledge_taxonomy_migrations/legacy-rendered-to-teacher-v1.json

# 这两个文件必须来自 mentor 运行 24 万初筛时的同一版本。
export MENTOR_LABEL_DEFINITIONS=/path/to/label_definitions_for_verification.json
export MENTOR_CALIBRATION_SAMPLE=/path/to/knowledge-label-calibration-sample.jsonl

export LABEL='知识点@词汇@词汇辨析@名词（短语）辨析'
export POLICY=configs/terminal_label_calibration_policies/mentor-direct-v1-preliminary-20260827.json
export RUN="$RUNTIME/direct-label/noun-discrimination-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RUN"
```

第一步用 mentor 的机器可读 `overall_summary.json` 排序。该步骤只是重现优先级，不修改数据：

```bash
python3 scripts/rank_mentor_verification_report.py \
  --summary /path/to/verification_results/overall_summary.json \
  --output-json "$RUN/mentor-priority.json" \
  --output-csv "$RUN/mentor-priority.csv"
```

然后构造该标签在最终 source 上的完整 packet。脚本会全量流式扫描一次，保存所有匹配记录的题号、父题号、source line、scope、route、原始 `input` 和 `output_all`：

```bash
python3 scripts/build_mentor_label_rollout_packet.py \
  --source "$FINAL_SOURCE" \
  --verify-label "$LABEL" \
  --label-definitions "$MENTOR_LABEL_DEFINITIONS" \
  --output "$RUN/full.packet.jsonl" \
  --report "$RUN/full.packet.report.json"

wc -l "$RUN/full.packet.jsonl"
cat "$RUN/full.packet.report.json"
```

完整 packet 不是全部都可进入本标签 rollout。该标签老师定义限制为“非复合单选”，因此按人工冻结的 exact route policy 划分：

```text
eligible：parent × 单选题 × 选择题
quarantine：翻译、完形、阅读、填空、复合小题及其他 route
```

当前冻结 packet 的实际计数为 `32,747` 条 eligible 和 `7,009` 条 quarantine。quarantine 不是删除；它是后续由题型负责人确认、或作为该标签错标问题簇处理的只读证据。先执行分流：

```bash
export ROUTE_POLICY=configs/terminal_label_rollout_policies/mentor-direct-v1-noun-discrimination-20260827.json

python3 scripts/partition_mentor_label_rollout_packet.py \
  --input "$RUN/full.packet.jsonl" \
  --policy "$ROUTE_POLICY" \
  --eligible-output "$RUN/eligible.packet.jsonl" \
  --quarantine-output "$RUN/route-quarantine.packet.jsonl" \
  --report "$RUN/route-partition.report.json"

wc -l "$RUN/eligible.packet.jsonl" "$RUN/route-quarantine.packet.jsonl"
cat "$RUN/route-partition.report.json"
```

只对 eligible packet 做 20 条 smoke，检查 JSON 解析、prompt version、模型输出和 source identity；确认无误后才显式带 `--allow-full` 启动该 32,747 条范围。全量输出每条记录都是后续 gate 可读的标准 evidence：

```bash
python3 scripts/validate_mentor_label_rollout.py \
  --input "$RUN/eligible.packet.jsonl" \
  --label-definitions "$MENTOR_LABEL_DEFINITIONS" \
  --teacher-csv "$TEACHER_CSV" \
  --taxonomy-migration "$KP_MIGRATION" \
  --output "$RUN/smoke.evidence.jsonl" \
  --report "$RUN/smoke.verdict.report.json" \
  --limit 20 \
  --concurrency 16

python3 scripts/validate_mentor_label_rollout.py \
  --input "$RUN/eligible.packet.jsonl" \
  --label-definitions "$MENTOR_LABEL_DEFINITIONS" \
  --teacher-csv "$TEACHER_CSV" \
  --taxonomy-migration "$KP_MIGRATION" \
  --output "$RUN/full.evidence.jsonl" \
  --report "$RUN/full.verdict.report.json" \
  --allow-full \
  --concurrency 64
```

全量完成后通过人工冻结的 preliminary policy 分流。该 policy 只允许这个标签的 positive 进入 `silver`，false 仍全部进入 hold：

```bash
python3 scripts/gate_terminal_label_discriminator.py \
  --input "$RUN/full.evidence.jsonl" \
  --teacher-csv "$TEACHER_CSV" \
  --policy "$POLICY" \
  --silver-output "$RUN/silver-label-evidence.jsonl" \
  --relabel-output "$RUN/relabel-candidates.jsonl" \
  --hold-output "$RUN/hold.jsonl" \
  --report "$RUN/gate.report.json"
```

最后从**本次全量运行新得到的** positive silver 中抽 60 条，并排除最初 12/12 校准题。抽样包不附加人工结论；业务方审核完成后再决定是否升级 policy：

```bash
python3 scripts/sample_silver_post_sweep.py \
  --input "$RUN/silver-label-evidence.jsonl" \
  --verify-label "$LABEL" \
  --exclude-jsonl "$MENTOR_CALIBRATION_SAMPLE" \
  --output "$RUN/post-sweep-60.review.jsonl" \
  --report "$RUN/post-sweep-60.report.json" \
  --sample-size 60 \
  --seed "noun-discrimination-mentor-direct-v1-20260827"
```

若独立 60 条全为 retain，人工创建新 policy 版本，将 `calibration_stage` 改为 `released_post_sweep`；若任何一条为 remove 或 uncertain，停止该标签放大，保留已产出 evidence，并新建该标签的误判问题簇。无论哪种结果，都不修改 source `output`。

#### DS 服务暂停期间：准备四个标签的离线 packet

在 DS 服务没有部署时，可以先构造 packet、按 route 分流、记录每个标签的真实 source 数量；这些步骤不发网络请求，也不改写 source 或历史标签。四个标签结论必须保持独立，不能把它们的后续 60 条复核合并计算。

下面命令会顺序扫描 source 四次，避免并发读取同一个 4 GB 源文件造成不必要的 IO 竞争。每个标签都会生成独立目录；重复运行同一 `BATCH` 会因输出已存在而失败，不会覆盖已有结果。

```bash
export FINAL_SOURCE=/local_data/zhangyonglin/english-knowledge-tagger-data/sources/cleaned_final_enhanced_v2.jsonl
export MENTOR_LABEL_DEFINITIONS=/local_data/zhangyonglin/english-knowledge-tagger-data/mentor-direct-v1/label_definitions_for_verification.json
export RUNTIME=/local_data/zhangyonglin/english-knowledge-tagger-runtime
export BATCH="$RUNTIME/direct-label/lexical-pos-v0.1-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BATCH"

prepare_label () {
  local slug="$1"
  local label="$2"
  local route_policy="$3"
  local label_run="$BATCH/$slug"

  mkdir -p "$label_run"
  python3 scripts/build_mentor_label_rollout_packet.py \
    --source "$FINAL_SOURCE" \
    --verify-label "$label" \
    --label-definitions "$MENTOR_LABEL_DEFINITIONS" \
    --output "$label_run/full.packet.jsonl" \
    --report "$label_run/full.packet.report.json"

  python3 scripts/partition_mentor_label_rollout_packet.py \
    --input "$label_run/full.packet.jsonl" \
    --policy "$route_policy" \
    --eligible-output "$label_run/eligible.packet.jsonl" \
    --quarantine-output "$label_run/route-quarantine.packet.jsonl" \
    --report "$label_run/route-partition.report.json"

  wc -l "$label_run/eligible.packet.jsonl" "$label_run/route-quarantine.packet.jsonl"
}

prepare_label noun-discrimination \
  '知识点@词汇@词汇辨析@名词（短语）辨析' \
  configs/terminal_label_rollout_policies/mentor-direct-v1-noun-discrimination-20260827.json
prepare_label adverb-discrimination \
  '知识点@词汇@词汇辨析@副词（短语）辨析' \
  configs/terminal_label_rollout_policies/mentor-direct-v1-adverb-discrimination-20260827.json
prepare_label verb-discrimination \
  '知识点@词汇@词汇辨析@动词（短语）辨析' \
  configs/terminal_label_rollout_policies/mentor-direct-v1-verb-discrimination-20260827.json
prepare_label adjective-discrimination \
  '知识点@词汇@词汇辨析@形容词（短语）辨析' \
  configs/terminal_label_rollout_policies/mentor-direct-v1-adjective-discrimination-20260827.json
```

服务恢复后，仍须对每个 `<label_run>/eligible.packet.jsonl` 先做 20 条 smoke，再启动对应的全量 DS 验证；不能把四个 eligible packet 串成一个文件后共用一个标签 policy。

---

## 9. 阶段 3：标签校准与保守 silver 分流

### 9.1 为什么要先校准标签，而不是相信全局准确率

判别稳定性和准确率会随标签差异很大：

- `介词`、`时态`、`语法一致`等高频且边界丰富的标签容易出现误判；
- 长尾标签题少，模型未必理解释义；
- 依赖图片、音频或父题材料的标签更容易因输入不全而假 false；
- 有关联标签的题容易被模型错误压缩为单标签。

因此不能用“全量 true 比例很高”放行所有标签。必须对每个末级标签独立校准。

### 9.2 校准台账

每个标签的台账建议至少记录：

| 字段 | 说明 |
|---|---|
| `canonical_label` | 当前老师 taxonomy 的末级路径 |
| `prompt_version` | 人审结论所对应的精确 prompt；不同 prompt 版本不得互相复用放行结论 |
| label 释义版本 | 原始/压缩释义和 CSV SHA |
| 判别器配置 | model、prompt_version、是否视觉、是否 reasoning |
| 样本池定义 | source SHA、筛选条件、route 与 scope 分布 |
| true 人审 | `retain / remove / uncertain` 计数 |
| false 人审 | `retain / remove / uncertain` 计数 |
| 主要误差模式 | 漏共标、图文缺失、题型误录、释义冲突等 |
| 结论 | hold / preliminary silver / released post sweep |
| 审查记录 | review ID、日期、审核人/来源 |

当前正在填写的校准台账是人工工作文件，不能被代码假定为完成，也不应自动提交到仓库。

### 9.3 稀疏 calibration policy

policy 只列出审核已完成且业务认可的标签。未列出的标签没有“默认通过”逻辑，而是：

```text
positive_disposition = hold
negative_disposition = hold
calibration_stage = unreviewed
```

一个已批准的 policy 条目形如：

```json
{
  "canonical_label": "知识点->词法->冠词->a/an的区别",
  "prompt_version": "example-direct-label-v1",
  "positive_disposition": "silver_label_candidate",
  "negative_disposition": "hold",
  "calibration_stage": "screened_12",
  "audit": {
    "positive": {"retain": 12, "remove": 0, "uncertain": 0},
    "negative": {"retain": 2, "remove": 8, "uncertain": 2}
  }
}
```

放行约束：

| 分支 | 放行条件 | 产物 |
|---|---|---|
| 正向 `match=true` | 标签明确列入 policy；已审 true 数大于 0；`true.remove=0` | `silver_label_candidate` |
| 负向 `match=false` | 标签明确列入 policy；false 人审全部支持“应移除”，无 retain/uncertain | `relabel_candidate` |
| 任意未列标签 | 无论 true 或 false | `hold` |
| 服务失败/无法解析 | 无论标签状态 | `hold` |

`screened_12` 是早期的 silver 准入，不是“100% 正确”的证明。对于准备大规模发布的标签，应另外进行 post-sweep 独立抽检；若 60 条独立正样本均未发现误标，其单侧 95% precision 下界约为 95%。这个统计门槛也不替代业务复核。

### 9.4 标准化直接判别证据

不同人、不同服务的原始 JSON 字段可能不同。必须先通过显式 field map 标准化；禁止以字段名猜测。

标准化证据最小契约：

```json
{
  "schema_version": "terminal-label-discriminator-evidence-v1",
  "review_id": "direct-label:123:知识点->...",
  "question_id": "...",
  "parent_id": "...",
  "source_line": 12345,
  "is_sub_question": true,
  "legacy_label": "知识点@...",
  "canonical_label": "知识点->...",
  "llm_match": true,
  "status": "candidate",
  "model": "ds-v4-flash",
  "prompt_version": "direct-label-v1",
  "route_key": {
    "declared_type_structure": "复合题",
    "declared_type_name": "语法选择"
  }
}
```

`source_line + question_id + parent_id + is_sub_question` 是最小身份组。gate 会拒绝同一 `question_id × canonical_label` 出现相互矛盾的 true/false。

### 9.5 已实现的本地 gate

```bash
# 1. 生成所有 active 标签的人工审核骨架；不自动放行
python3 scripts/build_terminal_label_calibration_template.py \
  --teacher-csv "$TEACHER_CSV" \
  --output "$RUN_DIR/terminal-label-review-template.jsonl"

# 2. 使用针对当前 runner 的显式字段映射，生成标准证据
python3 scripts/normalize_terminal_label_discriminator.py \
  --input "$RAW_DISCRIMINATOR_JSONL" \
  --field-map "$RUNNER_FIELD_MAP_JSON" \
  --output "$RUN_DIR/direct-evidence.normalized.jsonl"

# 3. 根据人工已批准的 sparse policy 分流
python3 scripts/gate_terminal_label_discriminator.py \
  --input "$RUN_DIR/direct-evidence.normalized.jsonl" \
  --teacher-csv "$TEACHER_CSV" \
  --policy "$CALIBRATION_POLICY_JSON" \
  --silver-output "$RUN_DIR/silver-label-evidence.jsonl" \
  --relabel-output "$RUN_DIR/relabel-candidates.jsonl" \
  --hold-output "$RUN_DIR/direct-hold.jsonl" \
  --report "$RUN_DIR/direct-gate.report.json"
```

以上脚本只写新 JSONL，且拒绝覆盖已有输出。

---

## 10. 阶段 4：题级 silver 组装

### 10.1 为什么不能直接拿标签级 true 训练

一道题可能有多个知识点。例如历史集合为 `A + B`：

- `A` 通过不代表 `B` 正确；
- `A + B` 都通过仍不代表缺失的 `C` 不存在；
- `A` 的判别证据若来自旧 source line，不能套到新版题面。

因此标签级 positive 只是必要条件，不是题级训练真值。

### 10.2 组装规则

一题可以进入 `silver_question_candidate` 的必要条件：

1. 源 output 可解析；
2. 所有历史知识点均能迁移为 active canonical 末级标签；
3. 每一个历史 canonical 标签都有 `silver_label_candidate`；
4. 每条正向证据的 `source_line`、`question_id`、`parent_id`、`is_sub_question` 与当前源严格一致；
5. 不存在同一题同一标签的矛盾证据。

否则写入 compact hold，常见原因：

```text
no_historical_knowledge_labels
historical_label_not_active_taxonomy
missing_positive_evidence_for_historical_label
positive_evidence_source_identity_mismatch
source_output_not_rendered_labels
```

组装命令：

```bash
python3 scripts/assemble_silver_questions.py \
  --source "$FINAL_SOURCE" \
  --silver-evidence "$RUN_DIR/silver-label-evidence.jsonl" \
  --teacher-csv "$TEACHER_CSV" \
  --taxonomy-migration "$KP_MIGRATION" \
  --output "$RUN_DIR/silver-question-candidates.jsonl" \
  --hold-output "$RUN_DIR/silver-question-hold.jsonl" \
  --report "$RUN_DIR/silver-question-assembly.report.json"
```

输出中的 `source_record` 保留原始题目字段，`approved_evidence_review_ids` 保留每个标签的证据 ID。它仍不能命名为 HQ 或训练集。

---

## 11. 阶段 5：处理 false、错标与漏标

### 11.1 false 的默认去向

`match=false` 不自动等于“历史标签错误”。默认进入 `hold`，按原因分簇：

| false/hold 模式 | 优先检查 |
|---|---|
| 模型认为只有一个主考点 | 是否存在业务要求的共标关系 |
| 同一个标签在特定 route 集中 false | 题型录入、route、释义适用范围 |
| 图文/听力题 false 多 | 图片、音频文本、时长或上下文是否缺失 |
| `其他` 与具体标签混淆 | 释义、近似标签关系、固定搭配边界 |
| 历史根节点无法迁移 | taxonomy migration，不是内容判断 |
| 同一答案但选项/解析为空 | 题目信息不完整，不能强行重标 |

只有 false 样本的人审结果全部明确支持“应移除”，才可在 policy 中把该标签 false 分支放入 `relabel_candidate`。

### 11.2 替换候选：flat 验证

flat 验证是替换候选的快速工具，而非直接判别的前置条件。它发送：

```text
题目有效内容
+ 当前历史标签及释义
+ 同级直接末级兄弟
+ 从允许范围检索的少量跨分支候选
```

当前默认策略中的 `12` 指的是**跨分支 lexical retrieval shortlist**，不是整棵树的深度，也不是同一父节点所有叶子数。直接同级兄弟另有独立预算；两者合起来才是 flat alternatives。

使用 flat 的场景：

- 已知历史标签 false，且希望得到受限替代候选；
- 业务确认该题必有知识点，但历史标签为空；
- `candidate_coverage=insufficient` 需要确认当前候选池是否遗漏正确分支；
- 某个近似标签簇需要对比候选预算与释义版本。

flat 只产生 `keep / replace / drop / uncertain` 候选，不能直接写 patch。

### 11.3 候选树：复杂错标/缺标的回退链路

知识点树的节点由老师 CSV 的 active taxonomy 构成：

```text
上层：显示当前父节点的所有直接子分类
末层：显示该父节点下所有直接末级叶子
控制项：__NO_MATCH__
```

树搜索原则：

1. 一次只在当前层选择；
2. `__NO_MATCH__` 表示当前分支不合适，回退并排除失败分支；
3. `__NO_MATCH__` 不是“其他”业务标签，不能输出；
4. 终端路径最多给出一个补充候选；
5. 多标签关系必须由人工/patch 显式补充，不能让树强制二选一。

树适合处理：

- flat 产生 `replace` 或 `uncertain + insufficient`；
- route 规定必须有知识点但历史为空；
- 标签与同级近似标签的边界难以用 top-k 一次看清；
- 需要分析“发释义/不发释义”、树宽、回退次数和节点耗时。

### 11.4 漏标处理

直接判别只能验证已有标签，因此漏标必须依赖额外信号发现：

- 老师人工金标；
- 模型评测错误；
- 一题解析清楚指出多个必要点，但历史集合缺少其中一个；
- 同质问题簇中异常少标签或题型-内容冲突；
- flat/tree 候选的稳定高置信分歧；
- 相同/近重复题的标签集合不合理差异。

漏标候选须作为 `add` patch 走人工确认。任何一个直接判别 true 都不能证明“该题没有漏标”。

---

## 12. 阶段 6：从 silver 到 HQ 与 SFT

### 12.1 HQ 需要比 silver 多什么

`silver_question_candidate` 至多说明现有历史标签未被校准判别器否定；HQ 还必须处理：

1. 标签集合是否漏标；
2. 题型是否正确；
3. 多模态证据是否完整；
4. taxonomy 是否全部 active；
5. 是否存在重复、近重复、相同父题或相同图片哈希跨评测泄漏；
6. 是否经过对应 route/label 的分层人工抽检；
7. 是否有冻结的独立 gold dev/test。

### 12.2 HQ 版本节奏

| 版本 | 规模建议 | 目的 | 进入条件 |
|---|---:|---|---|
| `hq-v0.1` | 2–3 万 | 验证数据格式、评测、SFT 全链路 | 高频 route/标签经过抽检，冻结独立评测 |
| `hq-v1.0` | 10 万+，逐步向 20–30 万扩展 | 首个正式训练集 | 覆盖长尾、混淆簇、图文题；patch 审核完成 |
| `hq-v1.1+` | 每轮补 2k–10k | 针对稳定模型错误定向补数 | 始终混入旧 HQ 核心集，避免遗忘 |

“每个标签至少 400 题”是覆盖目标，不是跳过质量门禁的理由。标签数量不足时，先确认该标签是否 active、业务需要、题目信息充分，再定向补，不用噪声样本硬凑数。

### 12.3 训练与评测隔离

在构建 HQ 时按以下 group 约束切分：

```text
parent_id
近重复文本簇
图片哈希簇
必要时题源/试卷簇
```

同一大题、近重复题或同图片题不得跨 train/validation/test。评测至少分层报告：

- 题型 F1；
- 知识点 micro/macro F1；
- 标签集合 exact match；
- 层级路径 F1；
- 父题/小题、纯文本/图文、听力、阅读、完形、语法选择等切片；
- 高频/长尾、已校准/新补充、易混淆标签切片。

---

## 13. 逐标签运行手册

后续的日常工作原则是：**一次只推进一个末级标签，或一个定义与错误模式高度一致的小簇。**

### 13.1 开始前检查清单

- [ ] 标签是老师规则本中的 active 末级标签；
- [ ] 已阅读该标签原始释义、压缩释义、兄弟标签与历史兼容说明；
- [ ] 明确标签可能适用的 parent/child scope 与主要 route；
- [ ] 已确认本批 source SHA、CSV SHA、migration SHA；
- [ ] 已定义图文/音频不足时的隔离规则；
- [ ] 已确定直接判别 prompt 版本；
- [ ] 已创建独立运行目录，所有输出路径不存在；
- [ ] 已定义 true/false 人工抽样方法与审核人。

### 13.2 单标签的标准步骤

#### Step A：标签业务预分析

输出一页标签卡：

```text
标签：知识点->...
释义：...
应该打：...
不该打：...
常见 route：...
近似/互斥/共标标签：...
输入缺失风险：文本 / 图片 / 音频 / 父题上下文
已知历史错误模式：...
```

这一步可由工程人员整理，但业务边界必须由老师/mentor 确认。

#### Step B：构造标签样本池

按 canonical 历史标签从 source 收集题。保留：

```text
question_id, parent_id, is_sub_question, source_line
原始标签、canonical 标签、route、题面完整度、图像/音频状态
```

不要因题型 route 尚未完全清洗而跳过该标签；但要把 route 写进证据，后续可发现“只在阅读还原误判”之类的问题。

#### Step C：直接判别

固定：

```text
source version
label definition version
prompt version
model 和 endpoint
并发
是否包含图片 / 父题上下文
```

第一次只跑小批，检查 JSON 可解析率、reason 是否引用解析、误判是否集中。确认后再扩大到该标签全部候选题。

#### Step D：双向人工抽检

从 `true` 与 `false` 分层抽样，各自审核。当前最小工作单元可用“12 条 true + 12 条 false”，但不要把 12 条零误差误解为正式发布门槛。

审核选项建议为：

```text
retain：历史标签确为必要点
remove：历史标签不该打
uncertain：题目信息不足、业务规则未定、需要二次裁决
```

审核必须记录原因，例如：

```text
多标签共标被模型漏判
题图决定选项，文本不足
历史题型名称录入错误导致上下文误导
标签释义缺少固定搭配边界
答案解析本身错误或不完整
```

#### Step E：更新校准 policy

仅在该标签台账完整、审核人确认后写 policy：

- true 无审出错标：可尝试 `silver_label_candidate`；
- false 仍有 retain 或 uncertain：`negative_disposition=hold`；
- false 全部明确应移除：才可考虑 `relabel_candidate`；
- 任何结论不稳：不写入 policy，继续 hold。

#### Step F：运行 gate 与组装器

运行第 9.5 与第 10.2 节命令，获取：

```text
silver-label-evidence.jsonl
relabel-candidates.jsonl
direct-hold.jsonl
silver-question-candidates.jsonl
silver-question-hold.jsonl
*.report.json
```

检查报告：

- 正向/负向/hold 数量是否符合台账；
- 某个 route 是否出现异常集中；
- 是否存在 source identity mismatch；
- 题级 silver 的通过率为何远低于标签级通过率；
- hold 是否主要由同一共现标签未完成校准造成。

#### Step G：处理未通过样本

| 样本状态 | 去向 |
|---|---|
| true 但标签未校准 | 保留 `hold`，等待台账完成 |
| false 但 false policy 未放行 | `hold`，优先做双向人工复核 |
| false 已明确错标 | `relabel_candidate`，进入 flat/tree/人工 patch |
| 标签集合缺少正向证据 | 题级 `hold`，等待其他共现标签完成校准 |
| source identity 不一致 | 重新确认 source version，不能复用证据 |
| 疑似漏标 | 新建 `add` 问题簇，不从 gate 自动补标签 |

### 13.3 一个标签完成的定义

某标签可以从“处理中”转为“可稳定扩展”至少需要：

1. 释义和近似边界已审；
2. 直接判别输出可解析、输入内容正确；
3. true/false 两侧都有人工样本；
4. 主要误差模式有明确去向；
5. policy 条目、运行 manifest 和报告齐全；
6. 未发现会影响其他标签的大规模系统性问题；
7. 该标签的 silver 结果未被误命名为 HQ。

---

## 14. 指标、抽检与发布门禁

### 14.1 不能只看一个数字

每个 label 和 batch 至少报告：

| 指标 | 说明 |
|---|---|
| 候选样本数 | 包含该历史 canonical 标签的题数 |
| 直接判别 true/false/error | 模型产出分布，非准确率 |
| true 人审 precision | `true.retain / true.reviewed` |
| false 人审 precision | `false.remove / false.reviewed`；用于判断 false 是否能放行 relabel |
| uncertain 比例 | 反映题目信息、释义或业务规则不足 |
| silver 标签数 | 已校准的正向证据数量 |
| silver 题数 | 全历史标签集合均有正向证据的题数 |
| hold 原因分布 | 后续工作队列，而非失败垃圾桶 |
| route × scope 切片 | 定位题型录入或业务规则问题 |
| 多模态状态切片 | 文本、图片、音频、图文听力组合 |

### 14.2 抽检原则

抽检必须分层，而非随机只看最容易题：

- parent / child；
- 高频 / 长尾；
- 有解析 / 无解析；
- 纯文本 / 图文 / 音频；
- 单标签 / 多标签；
- 目标标签独占 / 与近似标签共现；
- 高置信 / 低置信（如有）；
- 每个主要 route。

对发现的问题按“问题簇”计数。例如，如果“介词标签在阅读题小题中被模型当背景语法”反复发生，应新建一个簇，不应只逐题修改。

### 14.3 HQ 发布门禁

一个 batch 进入 `hq-v*` 前必须同时满足：

- [ ] 题型 route 的规则已确认，或该题型已有明确人工裁决；
- [ ] 标签均为 active taxonomy；
- [ ] 所有直接标签证据与 source identity 一致；
- [ ] false/relabel 与漏标风险已人工处理或明确隔离；
- [ ] 图像、音频和文本依赖满足当前训练输入能力；
- [ ] patch 已审核、版本化且可回放；
- [ ] 有独立人工金标 dev/test；
- [ ] parent/近重复/图片簇切分无泄漏；
- [ ] batch manifest、统计、抽检结论和负责人齐全。

---

## 15. 性能、成本与并发观测

### 15.1 为什么性能记录也是数据质量工作

耗时异常常提示业务问题：

- 某个标签 prompt 特别长，可能是释义过长或上下文拼接过多；
- 某一树分支宽、`NO_MATCH` 多，可能是 taxonomy 或释义边界不清；
- 图文/音频失败集中，可能不是模型能力问题而是输入信息缺失；
- 高并发后的 unparsed 增加，不能把服务拥塞造成的输出错误计入标签错误率。

### 15.2 每次模型运行要记录的指标

```text
batch wall time
每条 queue_elapsed_ms
每条 task_elapsed_ms
每次模型 model_call_elapsed_ms
prompt_chars / response_chars
HTTP / parse error 类型
并发数、重试次数、endpoint、模型版本
按标签、route、树父节点的 p50 / p95 / p99
```

flat 验证脚本可配置并发最高到 128，但不要一开始直接 128。推荐先用同一冻结小批比较 `16 / 32 / 64 / 128`：

- 若队列 p95 高而单次调用稳定：并发超过服务容量；
- 若单次调用 p95 高且 prompt 很长：优先检查释义和上下文；
- 若错误率随并发上升：降低并发，错误输出保持 hold；
- 若某标签独占慢任务：建立标签级性能/定义问题簇。

### 15.3 释义实验

对于易混淆标签，释义不是默认越长越好。实验要固定题、模型、并发和输出格式，只改变一个因素：

```text
原始释义 vs 压缩释义 vs 不发释义
完整同级叶子 vs 有预算的同级叶子
不同 retrieval k
有/无必要父题上下文
```

每个组合至少重复三次，记录：

- 输出一致性；
- 与人工金标的一致性；
- `other`、`NO_MATCH`、uncertain 比例；
- prompt 长度和 wall time；
- 错误集中在哪个标签或父节点。

模型三次一致只说明稳定，不说明正确；必须有人工或老师金标裁决。

---

## 16. 问题簇、版本与协作交接

### 16.1 什么是问题簇

问题簇是“同一原因、可批量验证、可复用规则”的一组异常，不是泛泛的“数据脏”。例如：

```text
阅读还原 vs 阅读匹配的题型录入混淆
完形填空与语法选择小题混淆
介词的时间 / 地点 / 原因目的 / 其他边界
比较级用法与比较级变化规则的共标
听力题缺少有效听力文本
图片选项题只保留图片A/B/C/D占位
历史语法词法根节点迁移
标签数量异常多的复合题
```

每个问题簇必须有：

```text
cluster_id
发现方式和影响范围
涉及 label / route / scope
最小可复现样本
假设根因
小批处理方案
人工抽检标准
放大条件与停止条件
输出路径和负责人
```

### 16.2 变更流程

```text
发现问题
  → 小批诊断（不改源）
  → 人工确认根因
  → 新规则 / prompt / migration / patch 小实验
  → 分层抽检
  → 扩大到该问题簇
  → 更新文档、版本与 manifest
```

不要把“某个小批效果不错”直接扩大为全量规则。若清洗后无法验证结果优于历史版本，应停止放大。

### 16.3 角色分工

| 角色 | 主要职责 | 不应做 |
|---|---|---|
| mentor / 老师 | 业务标签释义、边界裁决、数据补全、人工金标 | 直接覆盖历史 source |
| 题型负责人 | route inventory、盲审、题型 policy、题型 patch | 用知识点结果替代题型人工裁决 |
| 小题知识点负责人 | 逐标签校准、问题簇、flat/tree 候选与知识点 patch | 从父题继承标签或把模型候选直接入训 |
| 工程负责人 | 数据契约、脚本、版本、性能、报告、HQ 构建 | 代替业务方裁决语义边界 |
| 模型服务 | 提供候选、证据和分歧发现 | 直接修改 source/HQ |

### 16.4 每次交接必须提供

1. Git commit 与代码变更；
2. 源文件、SHA、规则本、policy、prompt 的 manifest；
3. 完整命令与输出目录；
4. 标签/route 统计和人工抽检结论；
5. 发现的错误模式与未决问题；
6. 下一步负责人、最小任务和停止条件。

---

## 17. 当前优先级与待决事项

### 17.1 当前优先级

1. 使用 mentor 已运行的“每个末级标签约 500 题”判别结果；
2. 对每个标签分别完成 true/false 人工审核台账；
3. 只将已完成标签写入 sparse calibration policy；
4. 先形成一批可靠的 `silver_label_candidate` 与 `silver_question_candidate`；
5. 将 false、hold、共标争议、图文/听力不足建立为问题簇；
6. 用老师金标、人工 patch 和独立评测把其中一部分升级为 `hq-v0.1`；
7. SFT pilot 后按错误切片补数据，而不是重新推翻全量历史数据。

### 17.2 仍待业务确认的事项

以下事项不能由工程规则自行假设：

- 各阅读类、阅读还原、阅读匹配、阅读问答、阅读填表小题是否需要知识点；
- 大题知识点的具体可打范围；
- 听力缺文本、图片占位题是否进入文本 SFT、视觉 SFT 或隔离；
- 近似标签、互斥标签、必然共标标签的完整关系；
- 停用标签应迁移、删除还是保留为兼容输出；
- 金标规模、双人复核和冲突裁决流程；
- 何时把 `screened_12` 升级为 post-sweep released；
- HQ 中图文样本的比例与真实推理输入形式。

### 17.3 当前实现位置

已实现：

```text
逐标签直接判别证据的 field-map 标准化
稀疏人工 calibration policy
silver / relabel / hold gate
题级“全部历史标签正向证据覆盖”组装器
source identity 校验
taxonomy migration、题型 inventory、flat 验证、知识点树与性能审计基础组件
```

未实现或不应自动化的部分：

```text
把未完成的人工校准台账自动转为放行 policy
直接从模型 false 自动生成最终 replace/add
全量 HQ 构造和正式 SFT
对所有阅读小题做统一的“空知识点”规则
```

---

## 附录：相关文档与脚本

- [当前数据处理 Loop](current-data-loop.md)：现有组件、实验与总体进度；
- [知识点标签验证](knowledge-label-validation.md)：flat 候选池、同级兄弟和 tree 的难例链路；
- [题型打标策略映射](type-policy-mapping.md)：route 与老师题型矩阵的逐项映射；
- [DS-V4-Flash 候选打标说明](ds-v4-flash-labeling.md)：内部服务调用与候选打标说明；
- `scripts/normalize_terminal_label_discriminator.py`：将判别器原始 JSONL 映射为稳定证据；
- `scripts/gate_terminal_label_discriminator.py`：按人工校准 policy 分流；
- `scripts/assemble_silver_questions.py`：按全历史标签正向覆盖构造题级 silver；
- `scripts/build_terminal_label_calibration_template.py`：生成 active 标签审核骨架；
- `scripts/validate_knowledge_labels.py`：flat 历史标签验证；
- `scripts/route_knowledge_tree.py`：难例的分层候选树搜索。
