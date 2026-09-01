# 劣质知识点释义稳定性与动态相邻叶实验

本流程解决两个独立问题：

1. DS 只看题目、一个末级标签及一个释义版本时，能否稳定输出 `keep / non_target / insufficient`；
2. 原标签被三次稳定否定后，局部 resolver 能否从直接兄弟、历史混淆邻居和必要的跨父分支中稳定找到替代标签。

流程不新增人工复核，不修改正式源 JSONL，不修改老师 CSV，也不直接生成 HQ。已有网页 GPT/Codex 结论统一称为 pseudo-gold；老师工作簿严格解析并 approved 的结果称为 teacher gold。召回率只报告，不参与门禁；不稳定、信息不足或 pseudo-gold uncertain 记录自动 `hold`。

## 1. 输入和输出

输入模板为 `configs/low_quality_labels/definition-experiment-inputs-v1.example.json`。运行前设置：

```bash
export PROJECT_ROOT=/local_data/zhangyonglin/english-knowledge-tagger
export RUNTIME=/local_data/zhangyonglin/english-knowledge-tagger-runtime
export MENTOR_ROOT=/local_data/zhangyonglin/english-knowledge-tagger-data/mentor-direct-v1
export INPUT_MANIFEST="$PROJECT_ROOT/configs/low_quality_labels/definition-experiment-inputs-v1.example.json"
export RUN_ROOT="$RUNTIME/low-quality-definition-stability-$(date +%Y%m%d-%H%M%S)"
```

模板包含 20 个本地 pseudo-gold 标签和转化法 500 条，共 21 个标签。程序会先核验全部路径和预期题数。所有输出只写 `$RUN_ROOT`，单题状态只有：

- `stable_keep_candidate`
- `stable_drop_candidate`
- `stable_relabel_candidate`
- `hold`

前三者仍是实验候选，不是 source patch。

## 2. E0：386 个知识点歧义画像

```bash
mkdir -p "$RUN_ROOT/e0"

python3 scripts/build_definition_ambiguity_profile.py \
  --teacher-csv "$PROJECT_ROOT/data/rulebooks/初中英语知识点题型方法释义.csv" \
  --definition-overrides "$PROJECT_ROOT/configs/knowledge_definition_overrides/knowledge-definition-overrides-v0.1.json" \
  --taxonomy-migration "$PROJECT_ROOT/configs/knowledge_taxonomy_migrations/legacy-rendered-to-teacher-v1.json" \
  --mentor-results "$MENTOR_ROOT/verification_results.jsonl" \
  --p0-policy "$PROJECT_ROOT/configs/low_quality_labels/p0-terminal-labels-20260828.json" \
  --output-json "$RUN_ROOT/e0/definition-ambiguity.json" \
  --output-csv "$RUN_ROOT/e0/definition-ambiguity.csv" \
  --report "$RUN_ROOT/e0/summary.json"
```

已有 flat replace 或 tree candidate evidence 时可重复追加：

```bash
--confusion-evidence /path/to/flat-verdicts.jsonl \
--confusion-evidence /path/to/tree-results.jsonl
```

输出包括 mentor yield、P0、override、文本风险、审计歧义家族、直接兄弟数、定义长度和混淆邻居。`summary.json` 给出 Fisher exact、odds ratio 和 Spearman 相关；只用于排优先级。

mentor 的全量 `verification_results.jsonl` 可能同时包含 `知识点@...` 和 `题型@...` 结果。E0 只把 `知识点@...` 纳入 386 个知识点统计；题型等其他 scope 会记录在 `summary.mentor_result_diagnostics.out_of_scope_records`。当前 migration 除两个旧根前缀外，还明确合并 `how/wh 类特殊疑问句→特殊疑问词` 和 `(don't/doesn't/didn't) have to→have to` 三个名称变更；`can/can't 表示推测` 仍不映射。经过 migration 仍不在老师 CSV 中的历史知识点会进入 `unknown_knowledge_labels` 隔离清单，不参与当前标签的分母，也不会让整轮画像失败。

已识别知识点但缺少有效 `question_id`、`llm_match` 不是 JSON 布尔值或出现重复 `label/question_id` 的记录，会进入 `quarantine_by_reason` 和最多 20 条 `quarantine_samples`，同样不进入任何标签分母；JSON 损坏、记录不是对象或缺少 `verify_label` 仍会直接报错，以免掩盖文件损坏。

## 3. 离线准备 21 个标签

```bash
python3 scripts/prepare_low_quality_definition_batch.py \
  --manifest "$INPUT_MANIFEST" \
  --output-root "$RUN_ROOT/e1-batch" \
  --seed definition-stability-v1
```

该命令不调用 DS。每个标签生成 `materialized.jsonl` 和 `stability.packet.jsonl`，总索引为 `e1-batch/batch.index.json`。同一 question 的 D0/D1/D2 使用完全相同的 60% train、20% dev、20% locked-test 分层切分；route 和 pseudo-gold 不进入 prompt。如果某条 `input` 只包含题型元数据，清洗后没有题干、选项、答案或解析，程序会将其记为 `skipped_insufficient_questions`，保留 question_id、源行号和原因，并从 E1 packet 排除；该题不会被当成 `non_target`，也不会让同一 label 的其他题停止处理。

## 4. E1：D0/D1/D2 三分类稳定性

先只过滤 dev，避免提前使用 locked-test：

```bash
python3 scripts/filter_terminal_label_stability_packet.py \
  --input "$LABEL_DIR/stability.packet.jsonl" \
  --split definition_dev \
  --definition-variant D0 \
  --definition-variant D1 \
  --definition-variant D2 \
  --output "$LABEL_DIR/dev-baselines.packet.jsonl"
```

固定运行三次，显式关闭 thinking，并按 `run_name × question_id` 哈希轮换 9102/9103：

```bash
for REPEAT in 1 2 3; do
  python3 scripts/validate_terminal_label_stability.py \
    --input "$LABEL_DIR/dev-baselines.packet.jsonl" \
    --output "$LABEL_DIR/dev-baseline-r${REPEAT}.jsonl" \
    --report "$LABEL_DIR/dev-baseline-r${REPEAT}.report.json" \
    --endpoint http://172.22.0.35:9102/v1/chat/completions \
    --endpoint http://172.22.0.35:9103/v1/chat/completions \
    --model DeepSeek-V4-Flash \
    --run-name "dev-baseline-r${REPEAT}" \
    --concurrency 10 \
    --timeout-seconds 180
done

python3 scripts/analyze_terminal_label_stability_runs.py \
  --packet "$LABEL_DIR/dev-baselines.packet.jsonl" \
  --run r1="$LABEL_DIR/dev-baseline-r1.jsonl" \
  --run r2="$LABEL_DIR/dev-baseline-r2.jsonl" \
  --run r3="$LABEL_DIR/dev-baseline-r3.jsonl" \
  --output "$LABEL_DIR/dev-baseline.analysis.json"

python3 scripts/select_terminal_definition_variants.py \
  --analysis "$LABEL_DIR/dev-baseline.analysis.json" \
  --split definition_dev \
  --output "$LABEL_DIR/dev-baseline.selection.json"
```

释义门禁为：三次 decision 一致率 `>=95%`、unanimous keep precision `>=95%`、high-confidence false-positive rate `<=1%`、uncertain unanimous high keep 为 0。recall 不参与门禁。

## 5. D3：失败标签的自动对比式释义

D0–D2 在 dev 全部失败时，生成器只读取 definition-train：

```bash
python3 scripts/generate_contrastive_definitions.py \
  --packet "$LABEL_DIR/stability.packet.jsonl" \
  --ambiguity-manifest "$RUN_ROOT/e0/definition-ambiguity.json" \
  --canonical-label "$CANONICAL_LABEL" \
  --output "$LABEL_DIR/d3.definitions.json" \
  --report "$LABEL_DIR/d3.generation.report.json" \
  --endpoint http://172.22.0.35:9102/v1/chat/completions \
  --model DeepSeek-V4-Flash

python3 scripts/expand_contrastive_definition_packet.py \
  --packet "$LABEL_DIR/stability.packet.jsonl" \
  --definitions "$LABEL_DIR/d3.definitions.json" \
  --split definition_dev \
  --output "$LABEL_DIR/d3-dev.packet.jsonl"
```

D3 dev 仍运行三次。将 D0–D2 和 D3 的 analysis `groups` 无冲突合并后选优：

```bash
python3 scripts/select_contrastive_definition.py \
  --analysis "$LABEL_DIR/dev-all.analysis.json" \
  --definitions "$LABEL_DIR/d3.definitions.json" \
  --canonical-label "$CANONICAL_LABEL" \
  --output "$LABEL_DIR/d3.selection.json"
```

D3 必须通过门禁且严格优于最佳通过 baseline，才进入 locked-test。用 `expand_contrastive_definition_packet.py --selected-variant D3-N --split locked_test` 只展开胜者。

## 6. locked-test 与 E1 决策

选出的 baseline 或 D3 只在 locked-test 再运行三次。随后：

```bash
python3 scripts/select_terminal_definition_variants.py \
  --analysis "$LABEL_DIR/locked.analysis.json" \
  --split locked_test \
  --output "$LABEL_DIR/locked.selection.json"

python3 scripts/assemble_terminal_stability_decisions.py \
  --packet "$LABEL_DIR/locked.packet.jsonl" \
  --run r1="$LABEL_DIR/locked-r1.jsonl" \
  --run r2="$LABEL_DIR/locked-r2.jsonl" \
  --run r3="$LABEL_DIR/locked-r3.jsonl" \
  --definition-selection "$LABEL_DIR/locked.selection.json" \
  --output "$LABEL_DIR/terminal-decisions.jsonl"
```

3/3 high keep 才生成 `stable_keep_candidate`；3/3 high non-target 才生成 `stable_drop_candidate`；pseudo-gold uncertain 永远为 `hold`。

## 7. E2：teacher gold 候选覆盖

```bash
python3 scripts/analyze_dynamic_leaf_coverage.py \
  --teacher-csv "$PROJECT_ROOT/data/rulebooks/初中英语知识点题型方法释义.csv" \
  --definition-overrides "$PROJECT_ROOT/configs/knowledge_definition_overrides/knowledge-definition-overrides-v0.1.json" \
  --corrections /path/to/approved-teacher-corrections.jsonl \
  --ambiguity-manifest "$RUN_ROOT/e0/definition-ambiguity.json" \
  --baseline-packet /path/to/retrieval12-sibling8.packet.jsonl \
  --output "$RUN_ROOT/e2/dynamic-leaf-coverage.json"
```

比较 direct siblings all、dynamic top-4/top-8/all 和当前 retrieval12+sibling8。每个 `historical parent × gold parent` 独立选择与 dynamic-all coverage 相差不超过 1 个百分点的最小预算。

## 8. E3：siblings、dynamic 与 root

代表标签见 `configs/low_quality_labels/dynamic-leaf-representative-labels-v1.json`。只有 direct 3/3 non_target 的记录生成任务：

```bash
python3 scripts/build_dynamic_leaf_tasks.py \
  --packet "$LABEL_DIR/locked.packet.jsonl" \
  --direct-run r1="$LABEL_DIR/locked-r1.jsonl" \
  --direct-run r2="$LABEL_DIR/locked-r2.jsonl" \
  --direct-run r3="$LABEL_DIR/locked-r3.jsonl" \
  --ambiguity-manifest "$RUN_ROOT/e0/definition-ambiguity.json" \
  --definition-selection "$LABEL_DIR/locked.selection.json" \
  --teacher-corrections /path/to/approved-teacher-corrections.jsonl \
  --output "$LABEL_DIR/dynamic.tasks.jsonl" \
  --hold-output "$LABEL_DIR/dynamic.hold.jsonl" \
  --report "$LABEL_DIR/dynamic.tasks.report.json"
```

`siblings` 只发送直接兄弟；`dynamic` 初始发送 4 个相邻叶，支持 `__MORE__ / __BACKTRACK__ / __HOLD__` 并可回退到其他父分支：

```bash
for MODE in siblings dynamic; do
  for REPEAT in 1 2 3; do
    python3 scripts/validate_dynamic_leaf_routing.py \
      --input "$LABEL_DIR/dynamic.tasks.jsonl" \
      --teacher-csv "$PROJECT_ROOT/data/rulebooks/初中英语知识点题型方法释义.csv" \
      --definition-overrides "$PROJECT_ROOT/configs/knowledge_definition_overrides/knowledge-definition-overrides-v0.1.json" \
      --output "$LABEL_DIR/${MODE}-r${REPEAT}.jsonl" \
      --report "$LABEL_DIR/${MODE}-r${REPEAT}.report.json" \
      --endpoint http://172.22.0.35:9102/v1/chat/completions \
      --endpoint http://172.22.0.35:9103/v1/chat/completions \
      --model DeepSeek-V4-Flash \
      --mode "$MODE" \
      --run-name "${MODE}-r${REPEAT}" \
      --page-size 4 \
      --max-steps 8 \
      --max-backtracks 2 \
      --concurrency 10 \
      --timeout-seconds 180
  done
done
```

T0 root 继续复用 `scripts/route_knowledge_tree.py`，不复制另一套 root 实现。动态候选 3/3 一致后构造独立 verifier packet：

```bash
python3 scripts/build_dynamic_candidate_verifier_packet.py \
  --tasks "$LABEL_DIR/dynamic.tasks.jsonl" \
  --resolver-run r1="$LABEL_DIR/dynamic-r1.jsonl" \
  --resolver-run r2="$LABEL_DIR/dynamic-r2.jsonl" \
  --resolver-run r3="$LABEL_DIR/dynamic-r3.jsonl" \
  --teacher-csv "$PROJECT_ROOT/data/rulebooks/初中英语知识点题型方法释义.csv" \
  --definition-overrides "$PROJECT_ROOT/configs/knowledge_definition_overrides/knowledge-definition-overrides-v0.1.json" \
  --output "$LABEL_DIR/dynamic-candidate-verifier.packet.jsonl"
```

该 packet 再用 `validate_terminal_label_stability.py` 独立运行三次。最终：

```bash
python3 scripts/analyze_dynamic_leaf_experiment.py \
  --tasks "$LABEL_DIR/dynamic.tasks.jsonl" \
  --resolver-run r1="$LABEL_DIR/dynamic-r1.jsonl" \
  --resolver-run r2="$LABEL_DIR/dynamic-r2.jsonl" \
  --resolver-run r3="$LABEL_DIR/dynamic-r3.jsonl" \
  --verifier-run v1="$LABEL_DIR/candidate-v1.jsonl" \
  --verifier-run v2="$LABEL_DIR/candidate-v2.jsonl" \
  --verifier-run v3="$LABEL_DIR/candidate-v3.jsonl" \
  --root-baseline-mean-calls 5.0 \
  --output "$LABEL_DIR/dynamic.analysis.json"
```

`stable_relabel_candidate` 必须满足 resolver 3/3 同候选、verifier 3/3 high keep、teacher gold 存在时命中 gold，且不是 pseudo-gold uncertain。批次通过还要求候选一致率 `>=90%`、teacher-gold precision `>=95%`、uncertain 强制细化率 `<=1%`、平均调用数较 root 下降 `>=30%`。

## 9. 禁止项

- 不把稳定性当成正确性；
- 不强行处理 pseudo-gold uncertain；
- route 默认只能改变排序，不能删候选；仅现有 route-guidance 中四个老师明确限制非复合单选的词性辨析标签允许 hard filter；
- 不把单次 tree candidate 写回 source；
- 不用一个候选替代整题多标签集合；
- 不让 D3 读取 dev/test 题面或理由。
