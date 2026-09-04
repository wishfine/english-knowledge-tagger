# 138 个优质标签的训练数据组装

这一步只做离线组装，不调用 DS，也不修改 v3 源文件或任何历史标签。

输入是：

- `final-quality-snapshot/.../snapshot.sqlite3`：终判 evidence 索引；
- `parent-context-v3-.../cleaned_final_enhanced_v3_parent_context.jsonl`：题目内容的 v3 派生源；
- 老师维护的知识点 CSV 和 taxonomy migration。

对 v3 源中的每道题，读取其历史知识点集合。除去 6 个不进入本批训练的标签后，要求剩余的每一个历史标签都有且仅有一条 `status=candidate, llm_match=true` 且输入完整的终判 evidence；否则写入 `holds.jsonl`，不做部分标签训练样本。满足条件的题目写入 `train.jsonl`：整行内容来自 v3 源，仅把 `output` 重写为合并后的知识点标签和原题型标签。同一道题的多个知识点因此只保留一条训练记录。

六个排除标签为：

1. `知识点@语法词法@动词时态@一般过去时@动词过去式变化规则`
2. `知识点@语法词法@非谓语动词@动名词@动名词的结构@动名词的一般式`
3. `知识点@语法词法@形容词与副词@副词的用法@副词修饰副词`
4. `知识点@语法词法@非谓语动词@动词不定式@动词不定式的结构@动词不定式的被动式`
5. `知识点@词汇@近/反义词@同/近义词`
6. `知识点@语法词法@动词时态@一般将来时@一般将来时的定义/判定@be going to`

输出文件：

- `train.jsonl`：可供后续训练实验使用的保守候选；
- `provenance.jsonl`：每题的正例标签、evidence review ID、原始/合并 output；
- `holds.jsonl`：缺证据、非正例、输入不完整、证据冲突等原因；
- `report.json`：源文件 hash、计数和排除标签清单。

`report.json` 中的 `evidence_label_count` 应为 138；若不是 138，应先检查终判快照和排除清单，不要直接把结果用于训练。

这里的“训练数据”仍是经过终判的候选集；如需发布为正式 silver/HQ，应再按项目的 60 条独立复核和多模态门禁执行。

## 按标签物化包

如需把 138 个标签分别落盘，使用 `scripts/materialize_processed_label_packets.py`。每个文件命名为 `有质-编号-完整历史标签名.jsonl`，例如 `有质-001-知识点@词汇@固定搭配／句型.jsonl`；因为 `/` 不能直接出现在文件名中，所以替换为全角 `／`。`label_index.json` 保存文件名与 canonical/历史标签的精确对应关系。该目录的内容是 DS true 且输入完整的 v3 题目包，不是未经判别的原始源；联合训练仍使用本流程生成的 `train.jsonl`。
