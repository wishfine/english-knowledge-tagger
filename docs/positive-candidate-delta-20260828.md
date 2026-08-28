# 正例快速筛选增量批次：2026-08-28

## 结论

最新权威完整样本台账共记录 384 个知识点标签。按固定准入条件重新计算后，可进入“快速筛选准备”渠道的标签从 69 个增加至 133 个：原 69 个全部仍有效，新增 64 个。

准入条件不变：

```text
mentor 原始抽样的单侧 95% Wilson 下界 ≥ 70%
且完整人工 true 审核 = 12/12 retain
且当前 teacher taxonomy 为 active
```

这只是 `final_packet_ready` 的工作队列，不是 silver、released silver 或训练集。每个标签仍要在无历史标签锚定的 `final-label-discriminator-v1` 下重新校准，且必须通过该版本 prompt 的人工门禁。

## 快照血缘

| 项目 | 值 |
|---|---|
| 原基线批次 | `positive-candidates-20260827.json`（69 标签） |
| 增量批次 | `positive-candidates-20260828-delta.json`（64 标签） |
| 合计候选 | 133 标签 |
| 最新完整台账 SHA-256 | `cc3907c40ca654b6c7814f8d8e49928e5540505040a35d46aa649a189a571265` |
| 原始 DS 产量台账 SHA-256 | `ab19806c8438e500c7ad19374cfe7b620ed2403871e99c3de05b06a30d695ad3` |

增量按 taxonomy 顶层分布如下：

| 分类 | 新增标签数 |
|---|---:|
| 词法 | 49 |
| 语篇主题 | 10 |
| 语篇体裁 | 2 |
| 语用 | 2 |
| 语音 | 1 |

高产优先的典型新增标签包括：分数/小数/百分数表达、`hundred/thousand/million`、虚拟语气、`have been to/in` 与 `have gone to` 区别、双重所有格、动名词主语/宾语、被动语态及时态相关标签。

## Route 规则

对新增 64 个标签逐条读取老师 CSV 后，没有发现“只标”“题型范畴限定”“只有某题型打”等明确排他措辞。因此全体使用 `soft_typical`：

```text
所有 route 保留为逐题终判候选
题型仅用于 final-v1 结果的分层统计、抽检和问题簇定位
```

语篇主题、语篇体裁和语用标签也不因没有 route 限制而直接发布；尤其小题、父题上下文缺失、图片/音频决定语义的情况仍会由题面完整性和 final-v1 判别保守 hold。

## 服务器：一次扫描物化新增 64 标签 packet

先拉取包含本快照的代码。下述命令只扫描 source 一次，输出一个独立 runtime 批次；不会覆盖既有 69 标签 packet。

```bash
cd /local_data/zhangyonglin/english-knowledge-tagger
git pull --ff-only origin main

export FINAL_SOURCE=/local_data/zhangyonglin/english-knowledge-tagger-data/sources/cleaned_final_enhanced_v2.jsonl
export MANIFEST=configs/candidate_batches/positive-candidates-20260828-delta.json
export GUIDANCE=configs/candidate_batches/positive-candidates-20260828-delta.route-guidance.json
export TEACHER_CSV=data/rulebooks/初中英语知识点题型方法释义.csv
export MENTOR_LABEL_DEFINITIONS=/local_data/zhangyonglin/english-knowledge-tagger-data/mentor-direct-v1/label_definitions_for_verification.json
export RUNTIME=/local_data/zhangyonglin/english-knowledge-tagger-runtime
export RUN="$RUNTIME/candidate-final-packets/positive-candidates-20260828-delta-$(date +%Y%m%d-%H%M%S)"

mkdir -p "$RUN"

python3 scripts/build_candidate_final_packet_batch.py \
  --source "$FINAL_SOURCE" \
  --manifest "$MANIFEST" \
  --guidance "$GUIDANCE" \
  --teacher-csv "$TEACHER_CSV" \
  --label-definitions "$MENTOR_LABEL_DEFINITIONS" \
  --output-dir "$RUN/packets" \
  --report "$RUN/build.report.json"
```

完成后，使用同一份 `knowledge-label-calibration-sample.jsonl` 对新 batch 构造 calibration packet。该步骤仍不调用 DS：

```bash
export REVIEW_SAMPLE=/local_data/zhangyonglin/english-knowledge-tagger-data/calibration/knowledge-label-calibration-sample.jsonl
export CALIBRATION_RUN="$RUNTIME/candidate-final-calibration/positive-candidates-20260828-delta-$(date +%Y%m%d-%H%M%S)"

test -r "$REVIEW_SAMPLE"
mkdir -p "$CALIBRATION_RUN"

python3 scripts/build_candidate_final_calibration_batch.py \
  --packet-batch-index "$RUN/packets/batch.index.json" \
  --review-sample "$REVIEW_SAMPLE" \
  --output-dir "$CALIBRATION_RUN/packets" \
  --report "$CALIBRATION_RUN/build.report.json"
```

DS 恢复后，先以每个标签的 `calibration.packet.jsonl` 分别运行 final-v1；不要将这 64 个标签与旧批次合并后共用一个 calibration policy。
