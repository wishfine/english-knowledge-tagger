# English Knowledge Tagger Design

## Goal

训练一个可离线部署的英语题目多知识点标注器：输入题干及其可选上下文，输出来自受控知识点目录的一至多个标签。

## Options considered

1. 多标签分类头：结构化、推理快，但标签集合变化需要重建分类头和重训；层级标签的可解释性也较差。
2. 纯提示词调用：无训练成本，但每题都有外部推理成本、输出一致性和内网部署都不可控。
3. 受控 JSON 的 LoRA completion-only SFT：可输出多个标签，保持与现有题库打标提示词相同的工作方式，并通过后处理限制在 taxonomy 内。

选择方案 3。它与同目录 Qwen3.5-4B LoRA 项目的部署方式一致，同时保留以后改为分类头的训练数据资产。

## Architecture

`prepare_data.py` 读取标注 JSONL，验证必填字段和 taxonomy，按 NFKC 标准化后的可见题目文本生成内容哈希；同哈希的题目永远落在同一个数据分区，避免重复题泄漏。它输出训练/验证 JSONL 和含样本计数、标签频率、哈希及随机种子的 manifest。

训练前将题目渲染成固定对话：system message 指定仅输出 JSON，user message 包含题干、选项、答案与解析，assistant message 为排序后的 `{"knowledge_points": [...]}`。训练脚本依据 tokenizer 的 chat template 建立 `input_ids`，只对 assistant completion 计算交叉熵。PEFT 注入 LoRA，启用 `--use-qlora` 时以 bitsandbytes NF4 4-bit 加载。

推理脚本加载基础模型和适配器，使用同一渲染器生成输出，并解析为 JSON、去重、仅保留 taxonomy 中的标签。评估指标为样本级 exact match 和多标签 micro/macro precision、recall、F1。

## Data contract

输入每行必须为对象：

```json
{"id":"stable-id","question":"non-empty text","knowledge_points":["taxonomy label"]}
```

`options` 可为字符串或字符串数组，`answer`、`analysis` 与 `source` 均为可选字符串。空题干、重复 id、空/非字符串标签和 taxonomy 外标签均是硬错误。正式数据在仓库外保存；仓库仅保留 taxonomy 和无真实内容的示例。

## Server and dependency decision

同类项目已经验证 Qwen3.5-4B + LoRA 在 `QuRater` Conda 环境上运行；xdf-35 历史路径为 `/local_data/zhangyonglin/conda_envs/QuRater` 与 `/local_data/zhangyonglin/models/Qwen3.5-4B`。本项目不改动该环境里的 PyTorch/CUDA，只补齐缺失的 Transformers、PEFT、Accelerate、Datasets、bitsandbytes 和 safetensors。国内下载优先使用 ModelScope，但首轮应复用已有本地权重。

从当前机器测试到 xdf-35 与 xdf-45 都在 SSH banner 前关闭连接，因此部署脚本先执行只读环境检查；恢复连接后才允许 pull、依赖同步和 smoke train。

## Testing

无需下载模型的单元测试覆盖：taxonomy 加载、输入验证、确定性分组切分、训练样本的 canonical JSON、生成结果解析和多标签指标。服务器脚本执行环境检查和极小 smoke 训练；完整训练前以 manifest 核验数据版本和无跨分区内容哈希。
