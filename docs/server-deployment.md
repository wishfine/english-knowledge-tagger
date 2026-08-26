# 服务器部署与训练（历史归档，当前不可执行）

> **不要按本文命令创建环境、安装 MS-Swift 或启动训练。** 本页保留的是 2026-08-24 的 Qwen3.5 + MS-Swift + LoRA 方案与当时的服务器调查记录。当前正式训练目标已改为 `Qwen3-VL-8B-Instruct` BF16 全参 SFT，且 `hq-v*` 和冻结评测集尚未准备完毕。实际训练方案将在 HQ 数据冻结、GPU 环境复核后另行发布；当前数据工作只遵循 [数据清洗执行手册](data-cleaning-playbook.md)。

## 当前调查结果

本机的两个内部 SSH 配置是 `xdf-35`（172.22.0.35）和 `xdf-45`（172.22.0.45）。2026-08-24 的只读连接测试均在 SSH banner 前返回 `kex_exchange_identification: Connection closed by remote host`，所以当前不能确认实时 GPU、CUDA 或仓库目录，也不能执行拉取。

同类 `physics-difficulty-rater` 项目的已记录环境在 xdf-35：

```text
environment: /local_data/zhangyonglin/conda_envs/QuRater
4B model:    /local_data/zhangyonglin/models/Qwen3.5-4B
9B model:    /local_data/zhangyonglin/models/Qwen3.5-9B
```

这正是本项目的环境克隆源。它已用于 Qwen3.5-4B + LoRA；不要把 Qwen3-32B / vLLM 教师环境用于本项目，也不要升级克隆源里已验证的 PyTorch、CUDA 或驱动。本项目的运行环境是独立克隆，正式训练用 Qwen3.5-9B，Qwen3.5-4B 只用于 smoke。

## 恢复 SSH 访问后的首次检查

以下命令在服务器上执行；先把 `<repo-dir>` 替换为实际克隆目录。

```bash
cd <repo-dir>
git pull --ff-only origin main

SOURCE_ENV=/local_data/zhangyonglin/conda_envs/QuRater
CONDA_ENV=/data/$USER/conda_envs/english-knowledge-tagger-swift
if [ ! -d "$CONDA_ENV" ]; then
  conda create --prefix "$CONDA_ENV" --clone "$SOURCE_ENV"
fi
"$CONDA_ENV/bin/python" -m pip install --upgrade -r requirements.txt
"$CONDA_ENV/bin/python" scripts/check_environment.py
```

`requirements.txt` 故意不包含 `torch`。MS-Swift 及其依赖只会安装到项目私有环境。若报告缺 `modelscope` 且需要下载模型，可单独安装：

```bash
"$CONDA_ENV/bin/python" -m pip install modelscope -i https://pypi.tuna.tsinghua.edu.cn/simple
```

在开训前确认两套本地模型可用：

```bash
test -f /local_data/zhangyonglin/models/Qwen3.5-4B/config.json
test -f /local_data/zhangyonglin/models/Qwen3.5-9B/config.json
```

若任一路径不存在，再向模型管理员确认共享 Qwen3.5-4B / Qwen3.5-9B 目录；不要在 Git 仓库内保存模型。

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

先运行最多 8 条样本的 **Qwen3.5-4B** Smoke。只有此步骤有正常退出码且 `environment.json` 的 `ready` 为 `true` 时，才进入 **Qwen3.5-9B** 正式训练。

```bash
CONDA_ENV=/data/$USER/conda_envs/english-knowledge-tagger-swift \
MODEL_PATH=/local_data/zhangyonglin/models/Qwen3.5-4B \
bash scripts/server_smoke.sh \
  "$RUNTIME_ROOT/prepared/v1/swift_train.jsonl" \
  "$RUNTIME_ROOT/prepared/v1/swift_validation.jsonl" \
  data/taxonomy/knowledge_points.json \
  "$RUNTIME_ROOT/outputs/smoke-v1"
```

完整训练和断点续训：

```bash
CONDA_ENV=/data/$USER/conda_envs/english-knowledge-tagger-swift \
MODEL_PATH=/local_data/zhangyonglin/models/Qwen3.5-9B \
bash scripts/server_train.sh \
  "$RUNTIME_ROOT/prepared/v1/swift_train.jsonl" \
  "$RUNTIME_ROOT/prepared/v1/swift_validation.jsonl" \
  data/taxonomy/knowledge_points.json \
  "$RUNTIME_ROOT/outputs/english-kp-v1"

bash scripts/server_train.sh \
  "$RUNTIME_ROOT/prepared/v1/swift_train.jsonl" \
  "$RUNTIME_ROOT/prepared/v1/swift_validation.jsonl" \
  data/taxonomy/knowledge_points.json \
  "$RUNTIME_ROOT/outputs/english-kp-v1" \
  "$RUNTIME_ROOT/outputs/english-kp-v1/checkpoint-100"
```

训练输出必须保留 `adapter/`、`adapter/tokenizer/`、`training_config.json`、validation loss 和环境报告，作为一个不可拆分的发布包。
