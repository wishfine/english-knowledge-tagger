#!/usr/bin/env bash
# Run a tiny real QLoRA training job only after the runtime has passed inspection.
set -euo pipefail

if [ "$#" -ne 4 ]; then
  echo "Usage: $0 TRAIN_JSONL VALIDATION_JSONL TAXONOMY_JSON OUTPUT_DIR" >&2
  exit 2
fi

TRAIN_FILE=$1
VALIDATION_FILE=$2
TAXONOMY_FILE=$3
OUTPUT_DIR=$4
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
"$CONDA_ENV/bin/python" scripts/train.py \
  --config configs/qwen35_4b_qlora.json \
  --base-model "$MODEL_PATH" \
  --train-file "$TRAIN_FILE" \
  --validation-file "$VALIDATION_FILE" \
  --taxonomy "$TAXONOMY_FILE" \
  --output-dir "$OUTPUT_DIR" \
  --max-train-samples 8
