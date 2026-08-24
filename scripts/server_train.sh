#!/usr/bin/env bash
# Run a full resumable LoRA/QLoRA training job after a smoke run has passed.
set -euo pipefail

if [ "$#" -lt 4 ] || [ "$#" -gt 5 ]; then
  echo "Usage: $0 TRAIN_JSONL VALIDATION_JSONL TAXONOMY_JSON OUTPUT_DIR [RESUME_CHECKPOINT]" >&2
  exit 2
fi

TRAIN_FILE=$1
VALIDATION_FILE=$2
TAXONOMY_FILE=$3
OUTPUT_DIR=$4
RESUME_CHECKPOINT=${5:-}
CONDA_ENV=${CONDA_ENV:-/local_data/zhangyonglin/conda_envs/QuRater}
MODEL_PATH=${MODEL_PATH:-/local_data/zhangyonglin/models/Qwen3.5-4B}

if [ ! -x "$CONDA_ENV/bin/python" ]; then
  echo "Conda environment does not exist: $CONDA_ENV" >&2
  exit 1
fi
if [ ! -f "$MODEL_PATH/config.json" ]; then
  echo "Base model config.json does not exist: $MODEL_PATH" >&2
  exit 1
fi

"$CONDA_ENV/bin/python" scripts/check_environment.py --output "$OUTPUT_DIR/environment.json"
TRAIN_COMMAND=(
  "$CONDA_ENV/bin/python" scripts/train.py
  --config configs/qwen35_4b_qlora.json
  --base-model "$MODEL_PATH"
  --train-file "$TRAIN_FILE"
  --validation-file "$VALIDATION_FILE"
  --taxonomy "$TAXONOMY_FILE"
  --output-dir "$OUTPUT_DIR"
)
if [ -n "$RESUME_CHECKPOINT" ]; then
  TRAIN_COMMAND+=(--resume-from-checkpoint "$RESUME_CHECKPOINT")
fi
"${TRAIN_COMMAND[@]}"
