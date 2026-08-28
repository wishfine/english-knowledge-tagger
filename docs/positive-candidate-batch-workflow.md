# 正例候选批次：一次扫描盘点流程

## 目的与边界

`positive-candidates-20260827.json` 是一个**工作队列快照**，不是最终标签 policy。它只说明某历史末级标签在当时满足：

```text
mentor 原始抽样：单侧 95% Wilson 下界 ≥70%
完整人工复核：true = 12/12 retain
current teacher taxonomy：active 且可映射
```

该 snapshot 当前包含 69 个 candidate、3 个 taxonomy-blocked label 和 92 个未满足门槛的 label。它由以下 authority ledger 快照生成：

```text
full-sample ledger SHA-256:
cc9003872ff327da7fd39f0ab9a6bc0511995da5d170e7beb0f22415e3e294d8
```

它**不包含** `positive_disposition`、`negative_disposition` 或 route policy；不能直接放行任何 DS true，也不能删除任何 DS false。

## 为什么先盘点、后物化 packet

69 个标签不能各自扫描一次 4.3 GB 最终源，也不能在 route 未确认前复制 69 套完整题面。正确顺序是：

```text
candidate manifest
  → 一次扫描最终源
  → label × route 全量统计 + 每 route 固定样本
  → 人工确认 route policy
  → 仅对已批准 label × route 物化 final packet
  → final-v1 校准、DS smoke、全量判别、gate
```

`route` 不会由模型决定。CSV 中写“常见题型”时只是业务证据，不自动等价于唯一 eligible route；只有 CSV 的明确排他规则或人工确认才可以写入 route policy。

## 一次扫描生成的两类输出

### `inventory.json`

对每个 candidate 标签记录：

- 历史带该标签的 source 记录总数；
- `parent/child × 题型结构 × 题型名称` 全量分布；
- 每条命中题中，所有 active 历史知识点是否都已位于本 69 标签队列；
- 队列外 active 标签的频次。

最后两项是**完整标签覆盖预测**。若一题存在队列外 active 标签，即使当前标签最终判别为 true，也无法马上成为 `silver_question_candidate`；它只会产生单标签 evidence，等待其他标签处理。

### `route-review-samples.jsonl`

每个 `标签 × route` 至多 5 条可重复的 hash 抽样。它包含目标标签、身份、route 和清洗后的题目内容；不包含 `output_all`、其他历史标签、`instruction`、题型头或 SFT 分类指令。它供人确认 route 边界，不供模型作最终判别。

## 服务器运行

在 35 执行。此过程不调用 DS，也不会修改最终 source：

```bash
cd /local_data/zhangyonglin/english-knowledge-tagger
git pull --ff-only origin main

export FINAL_SOURCE=/local_data/zhangyonglin/english-knowledge-tagger-data/sources/cleaned_final_enhanced_v2.jsonl
export TEACHER_CSV=data/rulebooks/初中英语知识点题型方法释义.csv
export KP_MIGRATION=configs/knowledge_taxonomy_migrations/legacy-rendered-to-teacher-v1.json
export MANIFEST=configs/candidate_batches/positive-candidates-20260827.json
export MENTOR_LABEL_DEFINITIONS=/local_data/zhangyonglin/english-knowledge-tagger-data/mentor-direct-v1/label_definitions_for_verification.json
export RUNTIME=/local_data/zhangyonglin/english-knowledge-tagger-runtime
export RUN="$RUNTIME/candidate-batches/positive-candidates-20260827-$(date +%Y%m%d-%H%M%S)"

test -r "$FINAL_SOURCE"
test -r "$MANIFEST"
test -r "$MENTOR_LABEL_DEFINITIONS"
mkdir -p "$RUN"
```

先验证 manifest 中的每个历史 rendered label 都可用 mentor definition JSON 构造最终 prompt：

```bash
python3 - "$MANIFEST" "$MENTOR_LABEL_DEFINITIONS" <<'PY'
import json
import sys
from pathlib import Path

from english_knowledge_tagger.mentor_direct_rollout import load_mentor_label_definitions

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
definitions = load_mentor_label_definitions(Path(sys.argv[2]))
labels = [row["legacy_label"] for row in manifest["candidates"]]
missing = sorted(set(labels) - set(definitions))
print(json.dumps({
    "candidate_labels": len(labels),
    "definition_labels": len(definitions),
    "missing_definition_labels": missing,
}, ensure_ascii=False, indent=2))
raise SystemExit(1 if missing else 0)
PY
```

只有 `missing_definition_labels: []` 时才开始唯一一次全源扫描：

```bash
python3 scripts/inventory_positive_candidate_batch.py \
  --source "$FINAL_SOURCE" \
  --manifest "$MANIFEST" \
  --teacher-csv "$TEACHER_CSV" \
  --taxonomy-migration "$KP_MIGRATION" \
  --inventory-output "$RUN/inventory.json" \
  --route-samples-output "$RUN/route-review-samples.jsonl" \
  --report "$RUN/inventory.report.json" \
  --sample-size-per-route 5 \
  --seed "positive-candidates-20260827"

cat "$RUN/inventory.report.json"
wc -l "$RUN/route-review-samples.jsonl"
```

生成紧凑摘要，供下一轮逐标签 route policy 讨论：

```bash
python3 - "$RUN/inventory.json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for label, row in payload["labels"].items():
    routes = sorted(row["route_counts"].items(), key=lambda item: (-item[1], item[0]))
    coverage = row["coverage"]
    print(json.dumps({
        "label": label,
        "records": row["matching_source_records"],
        "top_routes": routes[:5],
        "queue_complete_potential": coverage["all_active_labels_in_candidate_queue"],
        "queue_incomplete": coverage["has_active_labels_outside_candidate_queue"],
        "top_missing_active_labels": sorted(
            coverage["missing_active_label_counts"].items(),
            key=lambda item: (-item[1], item[0]),
        )[:5],
    }, ensure_ascii=False))
PY
```

## 盘点后的决策

每个标签逐一生成四选一结论：

| 结论 | 后续动作 |
|---|---|
| CSV 有明确排他 route，样本一致 | 写 route policy，进入 packet 物化队列 |
| CSV 写多个常见题型 | 对每个 route 分别抽样确认，不把常见题型当唯一限制 |
| route 元数据与内容冲突 | 进入题型清洗联动队列，不对该 route 运行最终判别 |
| 题面缺失、音频/图片决定信息 | 标记输入不完整，等待多模态或文本补全 |

即使通过 route policy，仍要在 `final-label-discriminator-v1` 下重新用 24 条人工样本校准；现有 mentor-v1 policy 不能复用。

## 一次扫描物化 final-v1 packet

route guidance 已明确区分：只有四个词性（短语）辨析标签使用硬 route 过滤；其余 65 个候选标签的 CSV“常见题型”只用于结果切片，所有 route 都保持候选。详见 [正例候选标签题型约束解释](candidate-route-guidance.md)。

因此 DS 停止期间可用一次全源扫描创建 69 个**非放行** final-v1 packet，避免以后逐标签重复扫描 4.3GB source。它只会写 runtime 目录；`final.packet.jsonl` 不包含 `input`、`instruction`、历史 `output` 或题型头，不能直接视为 silver。

```bash
cd /local_data/zhangyonglin/english-knowledge-tagger

export FINAL_SOURCE=/local_data/zhangyonglin/english-knowledge-tagger-data/sources/cleaned_final_enhanced_v2.jsonl
export MANIFEST=configs/candidate_batches/positive-candidates-20260827.json
export GUIDANCE=configs/candidate_batches/positive-candidates-20260827.route-guidance.json
export TEACHER_CSV=data/rulebooks/初中英语知识点题型方法释义.csv
export MENTOR_LABEL_DEFINITIONS=/local_data/zhangyonglin/english-knowledge-tagger-data/mentor-direct-v1/label_definitions_for_verification.json
export RUNTIME=/local_data/zhangyonglin/english-knowledge-tagger-runtime
export RUN="$RUNTIME/candidate-final-packets/positive-candidates-20260827-$(date +%Y%m%d-%H%M%S)"

mkdir -p "$RUN"

python3 scripts/build_candidate_final_packet_batch.py \
  --source "$FINAL_SOURCE" \
  --manifest "$MANIFEST" \
  --guidance "$GUIDANCE" \
  --teacher-csv "$TEACHER_CSV" \
  --label-definitions "$MENTOR_LABEL_DEFINITIONS" \
  --output-dir "$RUN/packets" \
  --report "$RUN/build.report.json"

cat "$RUN/build.report.json"
```

输出目录中的 `batch.index.json` 是唯一运行索引，记录每个标签的 packet 路径、全量命中数、选中数、硬 route hold、题面不完整 hold 以及每个 route 的分布。DS 恢复后，仍按**一个标签一个标签**读取对应 packet，先完成该 label 的 final-v1 校准，再执行 smoke 与全量判别。
