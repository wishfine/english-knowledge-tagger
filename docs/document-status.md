# 文档状态与阅读顺序

> 更新日期：2026-08-26

本项目的方案在数据质量实践中已经迭代。为避免把旧的实验设计、历史服务器命令或人工工作稿误当成当前执行规范，所有文档按以下状态阅读。

## 当前有效

| 文档 | 用途 | 何时阅读 |
|---|---|---|
| [数据清洗执行手册](data-cleaning-playbook.md) | 完整 SOP：逐末级标签、校准、silver、错标/漏标、HQ 门禁 | 开始任何数据清洗工作前 |
| [数据处理协作原则](data-cleaning-principles.md) | 给题型和知识点同事共用的简版方法论 | 分配工作或进行跨角色交接时 |
| [当前数据处理 Loop](current-data-loop.md) | 当前代码组件、已完成实验、运行命令和进度快照 | 实际运行或交接前 |
| [低质量知识点标签问题工作台](low-quality-label-remediation.md) | 低产量/错标标签的根因、实验、人工门禁与清洗边界 | 处理问题标签、树广搜或定向重标前 |
| [题型打标策略映射](type-policy-mapping.md) | `scope × 结构 × 名称` 的题型审计与 policy | 处理题型、route 或知识点存在性规则时 |
| [知识点标签验证](knowledge-label-validation.md) | flat/tree 的替换与补标难例链路 | 直接判别 false、未校准、缺标后 |
| [DS-V4-Flash 候选打标说明](ds-v4-flash-labeling.md) | 内部服务与旧生成候选脚本的边界 | 需要模型候选或接入原始判别结果时 |

当前已完成正例 `12/12 retain` 校准、可进入各自全量 rollout 队列的 preliminary label policy 位于：

```text
configs/terminal_label_calibration_policies/mentor-direct-v1-preliminary-20260827.json
```

它分别放行“名词/副词/动词/形容词（短语）辨析”的正向结果；四个标签均只允许 `parent × 单选题 × 选择题` route 进入 DS。该文件不是从 Markdown 台账自动生成的，而是依据已完成的完整样本人工复核手工冻结。各标签的 60 条独立复核、发布与停止条件均独立计算。

离线 packet 准备、全量执行命令、60 条独立复核与停止条件见 [数据清洗执行手册](data-cleaning-playbook.md#mentor-direct-v1名词短语辨析的首轮全量运行示例)。

当前数据高质量提取的首入口是：

```text
题目 × 历史末级知识点
→ 直接判别
→ 人审校准 policy
→ silver / hold / relabel
```

题型 route、flat shortlist 和树搜索不替代这一步；它们分别用于审计、空标签规则和 false/漏标难例。

## 人工工作台账：不自动改写、不自动提交

以下文件是正在推进的人工审核材料。它们可以作为校准 policy 的依据，但不能被脚本当作“已全部完成”的事实：

- `docs/knowledge-label-calibration-ledger.md`
- `docs/knowledge-label-calibration-reviews.md`

只有人工确认后的、稀疏的 `terminal-label-calibration-policy-v1` JSON 可以放行标签。未列标签默认 `hold`。

## 历史 / 归档文档：保留证据，不作为当前命令来源

| 文档 | 为什么归档 |
|---|---|
| [服务器部署与训练](server-deployment.md) | 记录的是早期 Qwen3.5 + MS-Swift + LoRA 假设；当前正式训练路线已改为 Qwen3-VL-8B BF16 全参 SFT，且 HQ 还未就绪 |
| [2026-08-24 初始设计](plans/2026-08-24-english-knowledge-tagger-design.md) | 初始 LoRA/MS-Swift 方案与现行训练路线不一致 |
| [2026-08-25 树路由设计](plans/2026-08-25-hierarchical-knowledge-candidate-routing-design.md) | 树仍可用于 false/漏标难例，但不再是历史标签正确性验证主入口 |
| [增强版题型清单](type-inventory-enriched.md) | 记录的是旧源版本的 inventory 运行；最终增强源应单独重新生成 inventory |

归档文档可用于理解历史决定和复现旧实验，但不能直接执行其中训练、环境或全量清洗命令。
