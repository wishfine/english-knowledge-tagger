# 题型打标策略映射

高质量数据先做“每种题应该如何打标”的映射，再清洗历史标签。题型策略的唯一键为：

```text
scope(parent | child) × 题型结构 × 题型名称
```

大题和小题必须分别建行。父题知识点不能继承到小题；父子关联仅用于题目上下文、数据血缘和去重。

## 生成全量题型清单

对每个数据源单独运行，不合并后再统计：

```bash
python3 scripts/inventory_question_types.py \
  --input /path/to/cleaned_all.jsonl \
  --output-json /local_data/zhangyonglin/english-knowledge-tagger-runtime/inventory/cleaned_all.json \
  --output-csv /local_data/zhangyonglin/english-knowledge-tagger-runtime/inventory/cleaned_all.policy.csv
```

JSON 是机器可读的完整统计。CSV 是人工逐行映射表，包含历史题型标签分布、历史知识点数量分布和最多三个样本题号。

## 填写 CSV

根据老师确认的题型矩阵填写以下列，而不是从历史 `output` 反推规则：

| 列 | 含义 |
|---|---|
| `policy_status` | `unmapped`、`approved`、`not_applicable` 或 `needs_teacher_review` |
| `knowledge_policy` | 此 scope 下应打的知识点规则；可写 `forbidden`、`none`、`required:<路径>`、`optional:<路径>` |
| `required_type_policy` | 此 scope 下必须输出的题型树路径 |
| `review_notes` | 来源图片、业务解释、边界案例和待确认问题 |

阅读理解、阅读还原、阅读问答和阅读填表的小题应填写 `knowledge_policy=forbidden`：只打对应阅读细题型，不打任何知识点。语篇体裁/语篇主题只属于大题。

## 规则生效条件

1. 每一行先由业务/老师确认 `policy_status=approved`。
2. 规则先在同质小批样本上生成审查包并人工复核。
3. 审核通过的标签变更以 patch 保存，不能覆写源 JSONL。
4. 只有 approved 策略覆盖的样本才能进入 `hq-v*` 高质量版本。
