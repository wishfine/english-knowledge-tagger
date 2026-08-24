# English Knowledge Tagger

对英语题目自动输出一个或多个标准知识点的 LoRA/QLoRA 微调项目。

首版把任务建模为 **completion-only 指令微调**：输入题干、选项、答案与解析，输出受固定 taxonomy 约束的 JSON：

```json
{"knowledge_points": ["一般过去时", "动词时态"]}
```

这样同一道题能拥有多标签，且在 taxonomy 演进后仍可保留层级标签；训练、验证与推理使用同一套渲染规则。

## 数据格式

原始标注数据是 UTF-8 JSONL，每行至少包含 `id`、`question`、`knowledge_points`。可选字段为 `options`、`answer`、`analysis`、`source`：

```json
{"id":"eng-0001","question":"She ___ to school yesterday.","options":["go","goes","went","has gone"],"answer":"went","analysis":"yesterday 表示过去时间，谓语用 went。","knowledge_points":["一般过去时","动词时态"]}
```

知识点必须先收录在 `data/taxonomy/knowledge_points.json`。原始题库和训练输出已被 `.gitignore` 排除。

## 本地快速检查

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
pytest
```

## 训练流程

```bash
python scripts/prepare_data.py \
  --input data/raw/english_labeled.jsonl \
  --taxonomy data/taxonomy/knowledge_points.json \
  --output-dir data/processed/v1

python scripts/train.py \
  --config configs/qwen35_4b_qlora.json \
  --train-file data/processed/v1/train.jsonl \
  --validation-file data/processed/v1/validation.jsonl \
  --taxonomy data/taxonomy/knowledge_points.json \
  --output-dir outputs/english-kp-v1
```

训练脚本只计算 assistant JSON 的 loss；适配器、tokenizer、训练配置与数据 manifest 一起保存在输出目录。开始正式训练前，先运行 `bash scripts/server_smoke.sh`。

## 服务器建议

已复核的同类项目表明，英语标签项目应优先复用 Qwen 学生模型的 **QuRater** Conda 环境和已有 `Qwen3.5-4B` 权重，而不是修改 Qwen3-32B / vLLM 的教师环境。历史记录在 xdf-35 上给出：

```text
conda env: /local_data/zhangyonglin/conda_envs/QuRater
model:     /local_data/zhangyonglin/models/Qwen3.5-4B
```

`xdf-35` 和 `xdf-45` 在 2026-08-24 从当前网络均于 SSH 密钥协商前关闭连接（`kex_exchange_identification`），因此在恢复访问前不能执行服务器安装、拉取或训练。详情及恢复后的命令见 [部署说明](docs/server-deployment.md)。

部署前检命令如下；它会在 CUDA 不可用、无 GPU 或训练依赖不完整时返回非零状态：

```bash
"$CONDA_ENV/bin/python" scripts/check_environment.py
```
