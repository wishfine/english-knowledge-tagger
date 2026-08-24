# 服务器部署与训练

## 当前调查结果

本机的两个内部 SSH 配置是 `xdf-35`（172.22.0.35）和 `xdf-45`（172.22.0.45）。2026-08-24 的只读连接测试均在 SSH banner 前返回 `kex_exchange_identification: Connection closed by remote host`，所以当前不能确认实时 GPU、CUDA 或仓库目录，也不能执行拉取。

同类 `physics-difficulty-rater` 项目的已记录可复用环境在 xdf-35：

```text
environment: /local_data/zhangyonglin/conda_envs/QuRater
base model:  /local_data/zhangyonglin/models/Qwen3.5-4B
```

这正是本项目的建议首选。它已用于 Qwen3.5-4B + LoRA；不要把 Qwen3-32B / vLLM 教师环境用于本项目，也不要升级这个环境里已验证的 PyTorch、CUDA 或驱动。

## 恢复 SSH 访问后的首次检查

以下命令在服务器上执行；先把 `<repo-dir>` 替换为实际克隆目录。

```bash
cd <repo-dir>
git pull --ff-only origin main

CONDA_ENV=/local_data/zhangyonglin/conda_envs/QuRater
"$CONDA_ENV/bin/python" -m pip install -r requirements.txt
"$CONDA_ENV/bin/python" scripts/check_environment.py
```

`requirements.txt` 故意不包含 `torch`。若报告缺 `modelscope` 且需要下载模型，可单独安装：

```bash
"$CONDA_ENV/bin/python" -m pip install modelscope -i https://pypi.tuna.tsinghua.edu.cn/simple
```

在开训前确认本地模型可用：

```bash
test -f /local_data/zhangyonglin/models/Qwen3.5-4B/config.json
```

若该路径不存在，再向模型管理员确认共享 Qwen3.5-4B 目录；不要在 Git 仓库内保存模型。

## 数据准备、Smoke 与正式训练

原始标注和训练产物必须位于 Git 仓库外。先生成无内容泄漏的 splits：

```bash
RUNTIME_ROOT=/data/$USER/english-knowledge-tagger
mkdir -p "$RUNTIME_ROOT"

"$CONDA_ENV/bin/python" scripts/prepare_data.py \
  --input "$RUNTIME_ROOT/raw/english_labeled.jsonl" \
  --taxonomy data/taxonomy/knowledge_points.json \
  --output-dir "$RUNTIME_ROOT/prepared/v1"
```

先运行最多 8 条样本的 Smoke。只有此步骤有正常退出码且 `environment.json` 的 `ready` 为 `true` 时，才进入正式训练。

```bash
CONDA_ENV=/local_data/zhangyonglin/conda_envs/QuRater \
MODEL_PATH=/local_data/zhangyonglin/models/Qwen3.5-4B \
bash scripts/server_smoke.sh \
  "$RUNTIME_ROOT/prepared/v1/train.jsonl" \
  "$RUNTIME_ROOT/prepared/v1/validation.jsonl" \
  data/taxonomy/knowledge_points.json \
  "$RUNTIME_ROOT/outputs/smoke-v1"
```

完整训练和断点续训：

```bash
CONDA_ENV=/local_data/zhangyonglin/conda_envs/QuRater \
MODEL_PATH=/local_data/zhangyonglin/models/Qwen3.5-4B \
bash scripts/server_train.sh \
  "$RUNTIME_ROOT/prepared/v1/train.jsonl" \
  "$RUNTIME_ROOT/prepared/v1/validation.jsonl" \
  data/taxonomy/knowledge_points.json \
  "$RUNTIME_ROOT/outputs/english-kp-v1"

bash scripts/server_train.sh \
  "$RUNTIME_ROOT/prepared/v1/train.jsonl" \
  "$RUNTIME_ROOT/prepared/v1/validation.jsonl" \
  data/taxonomy/knowledge_points.json \
  "$RUNTIME_ROOT/outputs/english-kp-v1" \
  "$RUNTIME_ROOT/outputs/english-kp-v1/checkpoint-100"
```

训练输出必须保留 `adapter/`、`adapter/tokenizer/`、`training_config.json`、validation loss 和环境报告，作为一个不可拆分的发布包。
