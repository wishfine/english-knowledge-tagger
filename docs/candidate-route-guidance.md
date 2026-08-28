# 正例候选标签的题型约束解释

> 适用对象：`configs/candidate_batches/positive-candidates-20260827.json` 的 69 个标签工作队列。
>
> 这是**非放行**配置：它不修改 source，不创建 silver，也不替代逐题最终判别。

## 结论

老师 CSV 中的“常见题型”不是题型白名单。当前 69 个正例候选标签中，只有四个“词汇辨析”标签具有明确的排他措辞；其余 65 个标签都只能把题型视为常见场景或诊断分层，不能据此过滤历史题目。

| 解释模式 | 数量 | 含义 |
|---|---:|---|
| `hard_exclusive` | 4 | CSV 明确限定题型；不符合的 route 不进入该标签的终判 packet，但保持 quarantine/hold。 |
| `soft_typical` | 65 | CSV 写“常见题型”；所有 route 仍可成为该标签的终判候选，题型只用于切片统计和抽检。 |

四个硬限制均为 `parent × 单选题 × 选择题`：

- 名词（短语）辨析
- 副词（短语）辨析
- 动词（短语）辨析
- 形容词（短语）辨析

证据是这四项释义中明确出现的“题型范畴限定在：单选题（非复合题）”及“只有单选题打此类标签”，不是依据历史数据的主 route 比例推断。

## 为什么不能把 65 个标签按 route 过滤

例如“固定搭配/句型”在单选、单词拼写和完成句子里都可能直接考查固定结构；“反身代词”“a/an 的区别”也可合理出现于单选、语法选择、语法填空等多种形式。某 route 的历史错标比例可能很高，但这应由最终判别器按题面逐题筛除，不能把整条 route 预先删掉。

因此 route 的职责是：

```text
route = 题型元数据切片
  → 发现题型录入异常、题面缺失、图文/听力依赖和系统性错标
  → 对 final-v1 的 true/false、置信度、人工复核结果做分层报表
  → 发现明显问题簇后才提出新的、人工确认的硬规则
```

它不是：

```text
历史主 route / CSV 常见题型
  → 自动排除其他 route
```

最终判别器仍只接收“候选标签 + 标签释义 + 清洗后的题目内容”。题型结构、题型名称、历史 `output` 和其他标签均不发送给模型。

## 与最终数据清洗的关系

| 情况 | 是否进入该标签的 final packet | 后续 |
|---|---|---|
| `hard_exclusive` 且 route 符合 | 是 | final-v1 校准、smoke、全量判别。 |
| `hard_exclusive` 且 route 不符 | 否 | `quarantine/hold`；可能是历史错标或题型元数据问题。 |
| `soft_typical` | 是，只要题面文本可用 | 结果按 route 分层；不能因 route 非常见而直接判 false。 |
| 文本为空、答案依赖未提供的图片/音频/父题材料 | 否 | 独立的输入完整性 hold / 多模态队列；这不是 route 过滤。 |

即使某题的单标签 evidence 为 true，也还需要同题全部 active 历史知识点都有各自的正向 evidence，才可能成为 `silver_question_candidate`。

## 已冻结的配置与验证

配置文件：

```text
configs/candidate_batches/positive-candidates-20260827.route-guidance.json
```

它绑定了 manifest 的 SHA-256，避免把本轮“4 硬限制 + 65 软提示”的结论误用于未来变更后的候选队列。配置只保存四个显式 override；其余 manifest 标签默认 `soft_typical`，因而不会遗漏或悄悄过滤新标签。

在 35 上运行以下命令即可验证，不调用 DS、不扫描题库、不改 source：

```bash
cd /local_data/zhangyonglin/english-knowledge-tagger

export RUNTIME=/local_data/zhangyonglin/english-knowledge-tagger-runtime
export ROUTE_GUIDANCE_RUN="$RUNTIME/candidate-route-guidance/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$ROUTE_GUIDANCE_RUN"

python3 scripts/validate_candidate_route_guidance.py \
  --guidance configs/candidate_batches/positive-candidates-20260827.route-guidance.json \
  --manifest configs/candidate_batches/positive-candidates-20260827.json \
  --teacher-csv data/rulebooks/初中英语知识点题型方法释义.csv \
  --report "$ROUTE_GUIDANCE_RUN/report.json"
```

预期摘要为：`candidate_label_count=69`、`hard_exclusive_count=4`、`soft_typical_count=65`。

## 后续执行原则

1. 四个词性辨析沿用既有硬 route packet，等待 DS 恢复后在 `final-label-discriminator-v1` 下重新校准。
2. 其余 65 个标签不需要逐个“审核题型才能开始”；可按末级标签直接准备全 route、题面完整的终判 packet。
3. 每个标签全量判别后，至少按 `scope × 题型结构 × 题型名称` 汇总 true/false、解析错误、低置信度和输入不全。
4. 若某个 route 的独立人工样本显示稳定系统性问题，先记录问题簇并由业务确认；只有 CSV 新增排他解释或人工冻结规则后，才将该 route 升级为硬过滤。
