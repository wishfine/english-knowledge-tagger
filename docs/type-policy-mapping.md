# 题型打标策略映射

高质量数据先做“每种题应该如何打标”的映射，再清洗历史标签。题型策略的唯一键为：

```text
scope(parent | child) × 题型结构 × 题型名称
```

大题和小题必须分别建行。所有小题都不能继承父题知识点；父子关联仅用于题目上下文、数据血缘和去重。这里的“不继承”不等于“小题禁止知识点”：是否输出小题知识点需要每一类题单独确认。

## 生成全量题型清单

对每个数据源单独运行，不合并后再统计：

```bash
python3 scripts/inventory_question_types.py \
  --input /path/to/cleaned_all.jsonl \
  --output-json /local_data/zhangyonglin/english-knowledge-tagger-runtime/inventory/cleaned_all.json \
  --output-csv /local_data/zhangyonglin/english-knowledge-tagger-runtime/inventory/cleaned_all.policy.csv
```

JSON 是机器可读的完整统计。CSV 是人工逐行映射表，包含历史题型标签分布、历史知识点数量分布和最多三个样本题号。

## 生成盲审样本包

在填写策略前，先按每个精确组合抽取真实题面。默认包不含历史 `output` 中的题型标签，避免 Codex、Gemini 或人工复核被旧标签锚定：

```bash
python3 scripts/sample_type_review_packet.py \
  --input "$FINAL_SOURCE" \
  --output "$RUNTIME/type-routing/$RUN/blind-review.jsonl" \
  --report "$RUNTIME/type-routing/$RUN/blind-review.report.json" \
  --per-route 5
```

该命令以 `scope × 题型结构 × 题型名称` 分层，在每一层稳定抽取至多 5 道题，约得到 560 条可审查记录。它只保留题面、题号、父题号和来源行号；题型复核完成后，如确需比较历史标签，另起新目录并加 `--include-legacy-labels`，不要覆盖盲审包。

当进入某一类题的知识点处理、flat 验证或 tree 实验时，改用一个 exact route 样本包，不要混入其它题型。例如首个语法选择小题切片：

```bash
python3 scripts/sample_type_review_packet.py \
  --input "$FINAL_SOURCE" \
  --output "$RUNTIME/type-routing/$RUN/child-composite-grammar-selection.review.jsonl" \
  --report "$RUNTIME/type-routing/$RUN/child-composite-grammar-selection.review.report.json" \
  --per-route 200 \
  --scope child \
  --declared-type-structure 复合题 \
  --declared-type-name 语法选择
```

三个 route 参数必须同时给出，且只做 exact match。冻结该 packet 后，flat 验证、tree 任务和 3×2 提示消融都必须使用同一份 packet；不要在不同实验间重新抽题。

## 生成路由策略骨架

题型清单是观察结果；历史 `output` 中的题型标签不是策略真值。先从清单生成全部 `unmapped` 的 JSON 策略骨架：

```bash
python3 scripts/bootstrap_type_routing_policy.py \
  --inventory "$RUNTIME/inventory/$RUN/question_types.json" \
  --output "$RUNTIME/type-routing/$RUN/type-routing.policy.v0.1.json"
```

策略每一行的唯一键仍为 `scope × 题型结构 × 题型名称`，没有通配符或“未命中则沿用历史标签”的回退规则。初始值中 `knowledge_inheritance=never` 只是禁止父题标签下灌，`knowledge_policy=unresolved` 表示该类小题是否有知识点尚未决定。

## 填写策略 JSON

根据老师确认的题型矩阵与 CSV 释义填写每一条规则，而不是从历史 `output` 反推规则：

| 字段 | 含义 |
|---|---|
| `policy_status` | `unmapped`、`needs_review`、`approved` 或 `not_applicable` |
| `canonical_family` | 稳定业务题型族，例如 `reading`、`cloze`、`grammar_selection`；不能根据历史标签补写 |
| `type_selection_mode` | 该题型族按内容输出一个或多个细分题型；`approved` 策略不可为 `unresolved` |
| `candidate_type_prefixes` | 老师 CSV 中可供此路由选择的 canonical `题型->...` 前缀；`approved` 至少一个 |
| `knowledge_inheritance` | 当前固定为 `never`，不可设为父题标签继承 |
| `knowledge_policy` | 此 scope 下应打的知识点规则，例如 `forbidden`、`optional`、`required:<路径>` 或 `unresolved` |
| `review_notes` | 来源图片、业务解释、边界案例和待确认问题 |

`policy_status` 的有效值为 `unmapped`、`needs_review`、`approved`、`not_applicable`。只有题型路由已证实的行才可标记为 `approved`；知识点策略尚未确认时仍可保留 `knowledge_policy=unresolved`，不得擅自补成 `forbidden`。

阅读选择和阅读问答的 CSV 文字明确区分了大题语篇标签与小题细分题型；阅读还原、阅读匹配、阅读填表、信息摘录等的父/子题粒度并不都明确。因此当前统一规则是：小题不继承语篇体裁/主题，其他知识点策略以逐类审批为准，不能一刀切。

## 生成审计路由

将已填写的策略和老师 CSV 应用到源数据。输出只包含来源行号、历史题型证据、候选题型集合、策略状态和风险码，不包含任何重写后的标签。默认规则本路径为 `data/rulebooks/初中英语知识点题型方法释义.csv`：

```bash
export TEACHER_CSV=data/rulebooks/初中英语知识点题型方法释义.csv

python3 scripts/route_question_types.py \
  --input "$FINAL_SOURCE" \
  --policy "$RUNTIME/type-routing/$RUN/type-routing.policy.v0.1.json" \
  --teacher-csv "$TEACHER_CSV" \
  --output "$RUNTIME/type-routing/$RUN/routes.jsonl" \
  --report "$RUNTIME/type-routing/$RUN/report.json"
```

脚本拒绝覆盖已有 route 或 report。先用 `--limit 1000` 做小样本检查，再对最终源文件跑全量。

常见风险码：

| 风险码 | 含义 | 后续处理 |
|---|---|---|
| `unmapped_policy` | 无精确策略行，或策略仍未填写 | 不进入 hq，补策略或进入审查包 |
| `needs_policy_review` | 有候选题型族，但业务规则尚未批准 | 生成同质审查包 |
| `legacy_type_deprecated` | 历史标签对应老师明确废弃的新题标签 | 重新判定题型，不直接保留 |
| `legacy_type_not_in_rulebook` | 历史标签无法匹配老师 CSV | 隔离为 taxonomy/映射问题 |
| `legacy_type_outside_candidate_prefix` | 历史标签与当前题型族冲突 | 作为高优先级错标候选 |

## 规则生效条件

1. 每一行先由业务/老师确认题型路由 `policy_status=approved`。
2. 规则先在同质小批样本上生成审查包并复核；模型复核只能是候选证据。
3. 审核通过的标签变更以 patch 保存，不能覆写源 JSONL。
4. 只有 approved 题型路由、且其知识点策略也已确认的样本才能进入 `hq-v*` 高质量版本。
