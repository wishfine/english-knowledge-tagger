# 增强版题型清单

增强版清单是独立的 `type-inventory-v2` 产物。它不会修改原有
`type_inventory.py`、`inventory_question_types.py` 或旧清单文件。

## 新增统计

每个 `scope × 题型结构 × 题型名称` 组合新增：

- `type_label_count_distribution`：每题题型标签数量分布；
- `unlabeled_record_count`：没有题型标签的记录数；
- `type_label_assignment_count`：题型标签赋值总数；
- `type_label_combination_counts`：完整题型标签组合及题数；
- `samples_by_historical_label`：按历史题型标签保留的样本题号；
- `unlabeled_sample_question_ids`：无题型标签样本题号。

程序在读取源文件时同步计算 SHA256，不额外扫描第二遍。JSON 和 CSV
任一输出已经存在时，脚本都会拒绝运行，不会覆盖已有结果。

## 运行

```bash
cd /local_data/zhangyonglin/english-knowledge-tagger

python scripts/inventory_question_types_enriched.py \
  --input /local_data/zhangyonglin/english-knowledge-tagger-data/sources/cleaned_with_type_labels_standard_only.jsonl \
  --output-json /local_data/zhangyonglin/english-knowledge-tagger-runtime/inventory/question_types.enriched.v1.json \
  --output-csv /local_data/zhangyonglin/english-knowledge-tagger-runtime/inventory/question_types.enriched.v1.policy.csv \
  --sample-per-label 10 \
  --sample-unlabeled 10 \
  --progress-every 100000
```

`--sample-per-label` 只限制每个历史题型标签保留的示例题号数量；
`--sample-unlabeled` 只限制每个组合保留的无标签示例题号数量。两者都不会
限制全量扫描或改变统计值。

`--progress-every` 控制进度提示频率。默认每处理 100,000 条有效记录向
标准错误输出打印一次进度，适合通过终端或 `nohup` 日志观察长任务。

## 验证

```bash
python -m unittest discover -s tests -p 'test_type_inventory_enriched.py' -v
```
