# English Knowledge Tagger

为已有初中英语题目回标“题型方法 + 知识点”的数据工程与生成式 SFT 项目。

当前目标不是全量重洗题库，而是先构建经过业务规则和人工确认的高质量数据版本：

```text
hq-v0.1（2–3 万） -> SFT pilot -> 错误切片 -> 定向补数 -> hq-v1.0（10 万+）
```

老师提供的版本化标签规则本位于 `data/rulebooks/初中英语知识点题型方法释义.csv`。它包含 386 个知识点末级标签和 190 个题型方法末级标签；源数据中的历史标签不是该规则本的替代品。

源数据保持只读。所有标签修正通过可审计 patch 叠加，不能直接覆盖原始或“暂时认为 OK”的 JSONL。

## 当前数据事实

当前基线数据是渲染后的 SFT JSONL，而不是结构化题目：

```json
{
  "instruction": "...",
  "input": "题型名称、题干、选项、答案、解析及必要父题上下文",
  "output": "题型@...;知识点@...",
  "question_id": "...",
  "parent_id": "...",
  "is_sub_question": true
}
```

这是给已有题目回标的场景，因此 `input` 中的题型结构/名称、答案、解析和父题上下文都是允许使用的证据。`output` 才是历史标签来源。

## 数据工作流

1. 审计大题/小题的题型与知识点标签，不直接改数据。
2. 生成小批、同质的人工审查包。
3. 人工确认 `keep/drop/replace/add` patch。
4. 将原始高置信样本与已确认 patch 构造成 `hq-v*` 数据版本。
5. 使用冻结 dev/test 评估模型，针对稳定错误切片补充数据。

小题知识点的关键规则是：父题标签只能缩小候选范围，不能自动全部继承。题型族决定小题是否应有知识点、可否继承以及是否必须重标。

## 已实现组件

- `scripts/profile_source.py`：流式字段与标签 profile。
- `scripts/audit_composites.py`：使用本地 SQLite 父题索引审计大/小题标签关系；不加载全量数据进内存。
- `scripts/inventory_question_types.py`：按大题/小题分别枚举“题型结构 × 题型名称”，生成待填写的打标策略 CSV。
- `scripts/bootstrap_type_routing_policy.py`：由题型清单生成全量 `unmapped` 的精确题型路由策略骨架。
- `scripts/sample_type_review_packet.py`：按精确题型组合稳定抽样，生成默认隐藏历史标签的盲审包。
- `scripts/route_question_types.py`：将老师 CSV 和已确认路由应用到源数据，输出历史题型证据、候选题型树与风险码；不改写标签。
- `scripts/label_candidates.py`：调用内部 `ds-v4-flash` 服务生成**候选**知识点标签；只写新 JSONL，不修改源数据。
- `scripts/build_knowledge_validation_packet.py` 与 `scripts/validate_knowledge_labels.py`：按精确小题路由的 `required/optional/forbidden/unresolved` 策略验证历史知识点；`forbidden` 与 `unresolved` 不调用 DS，输出可审计跳过原因，不改写标签。
- `scripts/normalize_terminal_label_discriminator.py`、`scripts/gate_terminal_label_discriminator.py` 与 `scripts/assemble_silver_questions.py`：将 mentor/DS 的逐末级标签判别通过显式 field-map 标准化；只放行已完成人审校准的正例，并且只在一道题全部历史 active 知识点都有正向证据时产出 `silver_question_candidate`。未校准、false 与源身份不一致的证据默认 hold，不改写 source。
- `scripts/build_knowledge_tree_tasks.py` 与 `scripts/route_knowledge_tree.py`：从历史 `replace`、候选池不足和 required 缺标构建单标签树搜索任务；逐层路由得到候选及回退轨迹，不生成最终多标签集合。
- `scripts/analyze_knowledge_tree_runs.py`：对三次 `compressed` 与三次 `none` 树路由运行做可重复性和 replace 候选波动汇总，不自动选择提示版本。
- `configs/knowledge_taxonomy_migrations/legacy-rendered-to-teacher-v1.json`：历史渲染标签树到当前老师 taxonomy 的版本化路径迁移规则。

候选打标接口、输入输出 schema、多人协作约定和小批运行命令见 [DS-V4-Flash 候选打标说明](docs/ds-v4-flash-labeling.md)。
题型逐项映射到老师矩阵的流程见 [题型打标策略映射](docs/type-policy-mapping.md)。
小题知识点历史标签验证与 DS-V4 小批运行流程见 [知识点标签验证](docs/knowledge-label-validation.md)。
题型与知识点从审计到 HQ 的当前端到端闭环见 [当前数据处理 Loop](docs/current-data-loop.md)。
逐末级标签推进、校准、silver、错标/漏标处理与 HQ 门禁的完整执行手册见 [数据清洗手册](docs/data-cleaning-playbook.md)。
给题型和知识点负责人共用的简版方法论见 [数据处理协作原则](docs/data-cleaning-principles.md)。
各文档的当前有效性、历史归档状态与推荐阅读顺序见 [文档状态](docs/document-status.md)。

对历史标签的“8 个同级近邻”与“完整直接兄弟叶子”候选覆盖对照，先按 [知识点标签验证](docs/knowledge-label-validation.md#v01--v02完整直接末级兄弟的覆盖校准) 生成并人工审查 packet，不能直接调用 DS 或修改标签。

## 训练路线

正式训练目标为 `Qwen/Qwen3-VL-8B-Instruct` 的 BF16 全参生成式 SFT，使用 response-only loss 和 DeepSpeed ZeRO-3。全参训练在高质量 `hq-v*` 数据与冻结评测集准备完成前不启动。

现有历史 Qwen3.5 / MS-Swift / LoRA 文件保留作参考，不能视为当前正式训练路线。

## 本地验证

项目的新数据组件仅依赖 Python 标准库：

```bash
python3 -m unittest discover -s tests -p 'test_source_profile.py' -v
python3 -m unittest discover -s tests -p 'test_composite_audit.py' -v
python3 -m unittest discover -s tests -p 'test_candidate_labeling.py' -v
python3 -m unittest discover -s tests -p 'test_label_candidates_cli.py' -v
```
