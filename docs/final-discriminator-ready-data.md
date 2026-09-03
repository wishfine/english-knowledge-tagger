# 最终判别器待处理数据与进度

> 更新日期：2026-08-27。此表是训练数据的**准备台账**，不是训练集清单；只有通过本页所有相应门禁的题目才可成为训练候选。`final.packet.jsonl` 已于同日构建完成。

## 最终判别器的边界

最终判别器版本为 `final-label-discriminator-v1`。它参考 mentor 判别器的定义加载、结构化 JSON 输出、禁用 thinking、SSE 流式读取、可审计 evidence 与重试机制，但与 `mentor-direct-v1` 有关键区别：

| 字段 | mentor 初筛 / `mentor-direct-v1` | 最终判别 / `final-label-discriminator-v1` |
|---|---|---|
| 题型结构、题型名称 | 从模型输入移除 | 从模型输入移除 |
| 候选标签 | 发送 | 发送 |
| 候选标签释义 | 发送 | 发送 |
| 历史 `output_all`、其他历史标签 | 发送，用于复现 mentor 初筛 | **不发送** |
| `instruction` | 发送 | **不发送** |
| route / scope | 仅审计保存 | 仅在模型外作业务过滤，模型不可见 |
| 输出 | `match / reason / should_be` | `match / confidence / reason` |

因此，旧的 `mentor-direct-v1` 校准 policy 不能直接放行最终判别器结果。gate 已强制检查 `prompt_version`：若 final evidence 使用的是 mentor policy，结果会进入 `hold`，而不是 silver。

最终 prompt 实际发送的内容只有：

```text
待验证标签
+ 该标签老师释义
+ 去除题型结构/名称后的题目内容（题干、选项、答案、解析等）
```

没有历史标签锚定，意味着它更适合作为最终数据筛选器；也意味着需要在已有人工复核样本上重新完成 `label × route × final-label-discriminator-v1` 校准。

## 状态定义

```text
route_eligible_packet_ready
  = 历史带标签，且通过老师明确的 route 硬规则；仅代表“允许被最终判别”。

final_packet_ready
  = 已从 eligible packet 生成；模型输入已经去掉题型元数据、历史 output 和 instruction。

final_calibrated_screened_12
  = 最终判别器在该 label × route 的既有人审样本上，true 结果 12/12 retain。

silver_label_candidate
  = 通过 final 判别且受到同一 final prompt 版本 policy 放行的单标签证据。

silver_question_candidate
  = 同一道题的每个历史 active 知识点均有独立正向 evidence；仍不证明没有漏标。

released_silver
  = 每标签从新产生的 positive 中独立随机抽 60 条复核，60/60 retain 后发布。

train_candidate
  = released silver 之外，仍通过完整标签集、图片/音频状态和 HQ 批次门禁的题目。
```

## 已完成终判后的离线质量快照

当最终判别器已完成但源题面随后产生了父题上下文补充时，不需要重跑 DS。使用已有 run 的 per-label `evidence.jsonl` 与修复后的 v3 源执行离线快照：它会重新按 `question_id + parent_id + is_sub_question` 对齐题目，保留 `llm_match=true` 的正向证据，并要求该题历史输出中的每一个 active 知识点都有唯一正向证据，才写入 `silver_question_candidate_unreleased`。其余记录写入 `holds.jsonl`。

本次使用的是实际执行过的 `run133`：`positive-candidates-133-20260828-130222`。它与后续 `wilson141` 的交集只有 129 个标签；run133 中另外 4 个未通过快速池门禁的标签必须排除。`wilson141 - run133` 的 12 个标签没有本次终判 evidence，不会被补造；涉及这些标签的题目会因 `missing_label_evidence` 留在 hold。

模型终判没有 `uncertain` 枚举：`llm_match=false` 和 `status=error` 都是 hold；`confidence=low` 会在统计中记录，但不自动改写成 uncertain 或删除。离线快照也必须排除未通过 Wilson 快速池门禁的标签，不能把它们的 true 结果混入候选。

服务器执行示例（不调用 DS、不修改 v3 源）：

```bash
python3 scripts/build_final_quality_snapshot.py \
  --run-dir "$FINAL_RUN" \
  --source /local_data/zhangyonglin/english-knowledge-tagger-runtime/source-audit/parent-context-v3-20260901-152542/cleaned_final_enhanced_v3_parent_context.jsonl \
  --teacher-csv data/rulebooks/初中英语知识点题型方法释义.csv \
  --taxonomy-migration configs/knowledge_taxonomy_migrations/legacy-rendered-to-teacher-v1.json \
  --exclude-label '知识点@语法词法@动词时态@一般过去时@动词过去式变化规则' \
  --exclude-label '知识点@语法词法@非谓语动词@动名词@动名词的结构@动名词的一般式' \
  --exclude-label '知识点@语法词法@形容词与副词@副词的用法@副词修饰副词' \
  --exclude-label '知识点@语法词法@非谓语动词@动词不定式@动词不定式的结构@动词不定式的被动式' \
  --output-dir "$RUNTIME/final-quality-snapshot-$(date +%Y%m%d-%H%M%S)"
```

该命令产出的是未发布候选，不等于 `released_silver`；后续仍需每标签独立 60 条人工复核，以及完整题目标签集合和多模态门禁。

任何 `match=false`、服务错误、route 不符或未完成最终 prompt 校准的记录均为 `hold`，绝不自动删除 source 标签。

## 当前最终源与定义版本

| 项目 | 值 |
|---|---|
| DS 运行时最终源 | `/local_data/zhangyonglin/english-knowledge-tagger-data/sources/cleaned_final_enhanced_v2.jsonl` |
| DS 运行时源记录数 | 3,203,122 |
| DS 运行时源 SHA-256 | `995191fb78f9ef0b9e9958563704b8d3bd2752809ef838815c443a80fe2b77ec` |
| 离线快照源（父题上下文 v3） | `/local_data/zhangyonglin/english-knowledge-tagger-runtime/source-audit/parent-context-v3-20260901-152542/cleaned_final_enhanced_v3_parent_context.jsonl` |
| mentor 定义文件 | `mentor-direct-v1/label_definitions_for_verification.json` |
| 定义 SHA-256 | `2eef1146ef601808e4995d3aeda3228867a0a6b7dff6df13c9a0dfa368d08b62` |
| route packet 批次 | `lexical-pos-v0.1-20260827-140630` |

## 已准备数据

这四个标签的 CSV 均明确规定：只用于“非复合单选题”。因此 `parent × 单选题 × 选择题` 是教师显式规则，不是从 DS 结果推断。

| 候选历史标签 | 原始带标签数 | route eligible | route quarantine | 当前阶段 | 下一步 |
|---|---:|---:|---:|---|---|
| 名词（短语）辨析 | 39,756 | 32,747 | 7,009 | `final_packet_ready`（32,747 条） | 在既有人审样本上校准 final v1 |
| 副词（短语）辨析 | 21,551 | 17,495 | 4,056 | `final_packet_ready`（17,495 条） | 同上 |
| 动词（短语）辨析 | 62,986 | 55,236 | 7,750 | `final_packet_ready`（55,236 条） | 同上 |
| 形容词（短语）辨析 | 35,752 | 29,769 | 5,983 | `final_packet_ready`（29,769 条） | 同上 |
| **合计** | **160,045** | **135,247** | **24,798** | — | — |

route quarantine 是问题簇证据，而不是删除队列。它可能是历史知识点错标，也可能是题型元数据有误；在题型清洗确认前保持只读隔离。

当前对应文件均在：

```text
/local_data/zhangyonglin/english-knowledge-tagger-runtime/direct-label/
  lexical-pos-v0.1-20260827-140630/
    <noun|adverb|verb|adjective>-discrimination/
      eligible.packet.jsonl
      route-quarantine.packet.jsonl
      route-partition.report.json
```

## 69 标签候选批次：离线 packet 物化

现有四个词性辨析 packet 是老师释义明确限定 route 的首批。其余 65 个正例候选标签不能根据 CSV“常见题型”预先过滤；它们在题面完整时应作为全 route 的逐题终判候选。`build_candidate_final_packet_batch.py` 会一次扫描最终源、为 69 个标签分别生成 `final-label-discriminator-packet-v1` 文件，并只对四个词性辨析应用已冻结的硬限制。

这一步仅代表 `final_packet_ready`，不是 final-v1 校准、更不是 silver。详细命令和 index 结构见 [正例候选批次流程](positive-candidate-batch-workflow.md#一次扫描物化-final-v1-packet)。

## 离线：构造最终判别 packet

这一步不调用 DS。输出的 `final.packet.jsonl` 不含 `input`、`instruction`、`output_all`，只有已清洗的 `question_text`、候选标签、身份与血缘字段。题目内容保留题干、选项、答案和解析（若源数据存在），但不保留题型元数据或末尾 SFT 分类指令。

```bash
cd /local_data/zhangyonglin/english-knowledge-tagger

export RUNTIME=/local_data/zhangyonglin/english-knowledge-tagger-runtime
export BATCH="$RUNTIME/direct-label/lexical-pos-v0.1-20260827-140630"
export MENTOR_LABEL_DEFINITIONS=/local_data/zhangyonglin/english-knowledge-tagger-data/mentor-direct-v1/label_definitions_for_verification.json

for slug in noun-discrimination adverb-discrimination verb-discrimination adjective-discrimination; do
  run="$BATCH/$slug"
  python3 scripts/build_final_label_discriminator_packet.py \
    --input "$run/eligible.packet.jsonl" \
    --label-definitions "$MENTOR_LABEL_DEFINITIONS" \
    --output "$run/final.packet.jsonl" \
    --report "$run/final.packet.report.json"
  wc -l "$run/final.packet.jsonl"
done
```

上述四个 `final.packet.jsonl` 的行数应分别为 `32,747`、`17,495`、`55,236`、`29,769`；若不一致，先查看对应 `final.packet.report.json`，不要调用 DS。

## DS 恢复后的逐标签流程

每个标签单独执行，不能合并 evidence、policy 或 60 条审核。

1. 使用已有完整人工复核样本，筛出该标签且 route 合规的记录，运行最终判别器；这些人工结论可复用，但**模型结果不可复用**。
2. 审核本版 prompt 产生的 true：至少 12 条均为 retain，才能人为新建 `final-label-discriminator-v1` policy。已有 `mentor-direct-v1` policy 只会导致 final evidence hold，这是设计预期。
3. 先跑 20 条 smoke，核对 `prompt_version`、题目内容清洗、JSON 成功率与耗时。
4. 获得新 policy 后，显式 `--allow-full` 跑该标签完整 `final.packet.jsonl`。
5. gate 只把该 prompt/version 的 true 正例分入 `silver_label_candidate`；false、低置信度和错误仍保留在 hold。`confidence` 是抽检优先级，不是放行开关。
6. `assemble_silver_questions.py` 只会在同题所有 active 历史知识点都有正向 evidence 时生成 `silver_question_candidate`。
7. 从每个标签全量新 positive 中独立抽 60 条；60/60 retain 后才更新为 `released_silver`。之后还需过 HQ 的完整标签集和多模态门禁，才是 `train_candidate`。

### 离线：从既有人审样本构造 final-v1 校准包

已有的 `knowledge-label-calibration-sample.jsonl` 给出每条人工复核样本的 `verify_label`、题号、历史 DS 分层和 review ID。`build_final_label_calibration_packet.py` 只用这些身份字段，把它们与当前 `final.packet.jsonl` 取交集；最终 runner 依旧只会读取其清洗后的题目内容与候选标签。

需要先让 35 上能读到该 9,191 条样本文件。建议统一放到：

```text
/local_data/zhangyonglin/english-knowledge-tagger-data/calibration/knowledge-label-calibration-sample.jsonl
```

若已通过 69 标签批量物化得到 `batch.index.json`，优先使用 `scripts/build_candidate_final_calibration_batch.py` 一次读取该人工样本、再依次连接各 label 的 final packet。它会生成 `calibration.index.json`，但不会读取原始题库、调用 DS 或复制人工结论进模型输入。完整命令见 [正例候选批次流程](positive-candidate-batch-workflow.md#离线批量构造-final-v1-校准包)。

在 35 上确认文件存在后，按四个标签分别生成校准包：

```bash
export REVIEW_SAMPLE=/local_data/zhangyonglin/english-knowledge-tagger-data/calibration/knowledge-label-calibration-sample.jsonl
test -r "$REVIEW_SAMPLE" || { echo "缺少人工复核样本：$REVIEW_SAMPLE"; exit 1; }

prepare_calibration () {
  local slug="$1"
  local label="$2"
  local run="$BATCH/$slug"

  python3 scripts/build_final_label_calibration_packet.py \
    --input "$run/final.packet.jsonl" \
    --review-sample "$REVIEW_SAMPLE" \
    --verify-label "$label" \
    --output "$run/final.calibration.packet.jsonl" \
    --report "$run/final.calibration.report.json"
  cat "$run/final.calibration.report.json"
}

prepare_calibration noun-discrimination '知识点@词汇@词汇辨析@名词（短语）辨析'
prepare_calibration adverb-discrimination '知识点@词汇@词汇辨析@副词（短语）辨析'
prepare_calibration verb-discrimination '知识点@词汇@词汇辨析@动词（短语）辨析'
prepare_calibration adjective-discrimination '知识点@词汇@词汇辨析@形容词（短语）辨析'
```

报告中的 `missing_from_final_packet_question_ids` 是人工样本不属于当前 `label × route` 的证据，不能删除或补造；`eligible_calibration_records` 才是给 final-v1 重新校准的样本。DS 部署后先运行这些较小 calibration packet，再比对已有人工复核结论。

最终 runner 的 smoke 命令模板：

```bash
export TEACHER_CSV=data/rulebooks/初中英语知识点题型方法释义.csv
export KP_MIGRATION=configs/knowledge_taxonomy_migrations/legacy-rendered-to-teacher-v1.json
export RUN="$BATCH/noun-discrimination"

python3 scripts/validate_final_label_discriminator.py \
  --input "$RUN/final.packet.jsonl" \
  --label-definitions "$MENTOR_LABEL_DEFINITIONS" \
  --teacher-csv "$TEACHER_CSV" \
  --taxonomy-migration "$KP_MIGRATION" \
  --output "$RUN/final.smoke.evidence.jsonl" \
  --report "$RUN/final.smoke.report.json" \
  --limit 20 \
  --concurrency 16
```

### 双 vLLM 端点运行

当前 DS-V4-Flash 部署有两个独立 vLLM 进程：`9102` 与 `9103`。最终 runner 的 `--endpoint` 可以重复传入；它将题目按 round-robin 分给两个端点，但 `--concurrency` 是**两个端点合计**的上限，而不是每个端点各自的上限。

最终判别请求固定携带 `stream=true`，客户端按 SSE 的 `data:` 增量拼接 `choices[0].delta.content`，收到 `[DONE]` 后再解析结构化 JSON。若服务端临时返回普通 JSON，客户端保留兼容解析；网络 reset、超时和 HTTP 错误均进入单题重试，不能导致整批进程直接退出。

白天使用总并发 `30`（约每端点 15 路）；夜间经资源确认后可使用总并发 `50`。每条 evidence 会记录其实际 `endpoint`，用于后续诊断端点异常或耗时差异。两个端点仍使用完全相同的 `final-label-discriminator-v1` prompt。

先对单个 label 的 calibration packet 运行 smoke：

```bash
export DS_ENDPOINT_1=http://172.22.0.35:9102/v1/chat/completions
export DS_ENDPOINT_2=http://172.22.0.35:9103/v1/chat/completions

python3 scripts/validate_final_label_discriminator.py \
  --input "$RUN/final.calibration.packet.jsonl" \
  --label-definitions "$MENTOR_LABEL_DEFINITIONS" \
  --teacher-csv "$TEACHER_CSV" \
  --taxonomy-migration "$KP_MIGRATION" \
  --output "$RUN/final.calibration.smoke.evidence.jsonl" \
  --report "$RUN/final.calibration.smoke.report.json" \
  --endpoint "$DS_ENDPOINT_1" \
  --endpoint "$DS_ENDPOINT_2" \
  --model DeepSeek-V4-Flash \
  --limit 20 \
  --concurrency 30
```

不要将 `--allow-full` 加到 calibration smoke；全量命令仍只在标签的 final-v1 人工校准 policy 冻结后执行。

### v2 边界澄清：固定搭配/句型

`固定搭配/句型` 的 24 条 final-v1 校准中，模型将 `whatever` 引导的让步状语从句误认为固定句型。完整人工复核已将该题判为删除：从句连接词/句法功能不等于固定搭配或固定句型。因此 v1 的该标签正例审核为 `16/17`，不满足正例零 remove 的发布条件，禁止跑全量。

`configs/final_label_prompt_clarifications/final-label-discriminator-v2-fixed-phrase.json` 不修改老师定义或 source；它只向该标签的终判 prompt 增加上述边界说明，并声明独立的 `final-label-discriminator-v2`。必须用同 24 条重新运行、重新审核 v2 的 true，不能复用 v1 evidence 或 policy。

```bash
export PROMPT_CLARIFICATIONS=configs/final_label_prompt_clarifications/final-label-discriminator-v2-fixed-phrase.json
export DS_HOST=172.22.0.35
export DS_ENDPOINT_1="http://${DS_HOST}:9102/v1/chat/completions"
export DS_ENDPOINT_2="http://${DS_HOST}:9103/v1/chat/completions"

python3 scripts/validate_final_label_discriminator.py \
  --input "$CALIBRATION_PACKET" \
  --label-definitions "$MENTOR_LABEL_DEFINITIONS" \
  --teacher-csv "$TEACHER_CSV" \
  --taxonomy-migration "$KP_MIGRATION" \
  --output "$SMOKE_RUN/v2.evidence.jsonl" \
  --report "$SMOKE_RUN/v2.report.json" \
  --prompt-clarifications "$PROMPT_CLARIFICATIONS" \
  --endpoint "$DS_ENDPOINT_1" \
  --endpoint "$DS_ENDPOINT_2" \
  --model DeepSeek-V4-Flash \
  --limit 24 \
  --concurrency 30
```

预期只将连接词/从句功能误判为 true 的样本纠正为 false；若 v2 又错误删除固定词组、固定句型或同义替换题，停止该 v2，不执行全量。

全量命令只有在 final-v1 的该标签 policy 已人工冻结后才能执行：

```bash
python3 scripts/validate_final_label_discriminator.py \
  --input "$RUN/final.packet.jsonl" \
  --label-definitions "$MENTOR_LABEL_DEFINITIONS" \
  --teacher-csv "$TEACHER_CSV" \
  --taxonomy-migration "$KP_MIGRATION" \
  --output "$RUN/final.full.evidence.jsonl" \
  --report "$RUN/final.full.report.json" \
  --allow-full \
  --concurrency 64
```

在任何版本中，最终判别器都不修改 `cleaned_final_enhanced_v2.jsonl`，所有结果写入 runtime 目录。
