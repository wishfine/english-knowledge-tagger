# 知识点释义覆盖层

## 用途

`configs/knowledge_definition_overrides/knowledge-definition-overrides-v0.1.json` 是实验用的释义覆盖层。它只替换 DS prompt 中看到的末级知识点释义，不修改教师原始 CSV，也不自动改写题目的历史标签。

当前覆盖层包含 10 个边界明确的修订：

- 构词法：转化法、派生法、合成法；
- 词汇音/形/义：名词、动词、形容词、副词、介词 5 个标签；
- 词汇固定搭配/句型；
- 语用时间：顺序。

覆盖层中的 `status=active_for_experiment` 只表示“允许用于实验”，不表示已经通过金标验收。每次扩大范围前，仍需做 DS 抽样、独立人工复核和全量结果审计。

## 运行方式

知识树路由脚本增加了可选参数：

```bash
python3 scripts/route_knowledge_tree.py \
  --input "$TREE_INPUT" \
  --teacher-csv data/rulebooks/初中英语知识点题型方法释义.csv \
  --definition-overrides \
    configs/knowledge_definition_overrides/knowledge-definition-overrides-v0.1.json \
  --output "$RUN/tree-results.jsonl" \
  --report "$RUN/tree-timing.report.json" \
  --endpoint http://172.22.0.35:9102/v1/chat/completions \
  --model DeepSeek-V4-Flash \
  --limit "$LIMIT" \
  --concurrency 10 \
  --max-steps 8 \
  --max-backtracks 2 \
  --terminal-definition-mode compressed \
  --timeout-seconds 180
```

不传 `--definition-overrides` 时，行为与原来一致。运行报告会记录 `definition_overrides` 路径，结果中的 `prompt_version` 不变，因此必须同时保存报告和覆盖层文件。

## A/B 实验

两次运行必须使用同一个冻结的 `TREE_INPUT`、同一个 endpoint、同一个并发数和同一组 search 参数。先跑 baseline，再跑 override；不要把两次结果混写到同一个文件。

```bash
export TREE_INPUT="/path/to/frozen/tree-input.jsonl"
export ABLATION_DIR="/path/to/runtime/knowledge-definition-ablation-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$ABLATION_DIR"

# A：原始释义
python3 scripts/route_knowledge_tree.py \
  --input "$TREE_INPUT" \
  --teacher-csv data/rulebooks/初中英语知识点题型方法释义.csv \
  --output "$ABLATION_DIR/baseline.jsonl" \
  --report "$ABLATION_DIR/baseline.report.json" \
  --endpoint http://172.22.0.35:9102/v1/chat/completions \
  --model DeepSeek-V4-Flash \
  --limit 60 \
  --concurrency 10 \
  --max-steps 8 \
  --max-backtracks 2 \
  --terminal-definition-mode compressed \
  --timeout-seconds 180

# B：释义覆盖层
python3 scripts/route_knowledge_tree.py \
  --input "$TREE_INPUT" \
  --teacher-csv data/rulebooks/初中英语知识点题型方法释义.csv \
  --definition-overrides configs/knowledge_definition_overrides/knowledge-definition-overrides-v0.1.json \
  --output "$ABLATION_DIR/override.jsonl" \
  --report "$ABLATION_DIR/override.report.json" \
  --endpoint http://172.22.0.35:9102/v1/chat/completions \
  --model DeepSeek-V4-Flash \
  --limit 60 \
  --concurrency 10 \
  --max-steps 8 \
  --max-backtracks 2 \
  --terminal-definition-mode compressed \
  --timeout-seconds 180

python3 scripts/analyze_knowledge_definition_ablation.py \
  --baseline "$ABLATION_DIR/baseline.jsonl" \
  --override "$ABLATION_DIR/override.jsonl" \
  --output "$ABLATION_DIR/summary.json"
```

`summary.json` 只回答“覆盖释义是否改变 DS 的路径/耗时”，不回答哪一个结果是真值。候选发生变化的题目还要交给网页 GPT 或人工复核；出现 `unparsed`、`budget_exhausted`、`uncovered` 的题目统一保留为 hold，不自动替换标签。

## 覆盖层格式

每条覆盖至少包含：

```json
{
  "label": "知识点->...",
  "replacement_definition": "DS 看到的新释义",
  "change_kind": "semantic_boundary",
  "reason": "为什么修改",
  "status": "active_for_experiment"
}
```

加载器会检查：

- JSON schema 版本正确；
- 标签以 `知识点->` 开头且存在于教师 CSV；
- 标签不重复；
- 替换释义非空；
- 状态只能是 `active` 或 `active_for_experiment`。

任何一项不满足都会在发起 DS 请求前失败，避免静默使用错误配置。

## 版本和验收规则

1. 原始 CSV 始终只读保留，覆盖层单独版本化。
2. 修改覆盖层后必须生成新的 `policy_id`，不要覆盖旧版本。
3. 单个标签先跑小样本，并使用网页 GPT/Gemini 或人工复核结果做对照。
4. 只有目标标签精度、召回和误标模式都达到该标签的验收门槛，才允许把覆盖层用于该标签的全量处理。
5. 多标签题仍按“逐标签判定、最后按 `question_id` 合并”，覆盖层不改变这一原则。
