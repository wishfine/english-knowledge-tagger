#!/usr/bin/env bash
# Run a tiny MS-Swift QLoRA job with Qwen3.5-4B to validate data and hardware.
set -euo pipefail

if [ "$#" -ne 4 ]; then
  echo "Usage: $0 SWIFT_TRAIN_JSONL SWIFT_VALIDATION_JSONL TAXONOMY_JSON OUTPUT_DIR" >&2
  exit 2
fi

TRAIN_FILE=$1
VALIDATION_FILE=$2
TAXONOMY_FILE=$3
OUTPUT_DIR=$4
CONDA_ENV=${CONDA_ENV:-/data/$USER/conda_envs/english-knowledge-tagger-swift}
MODEL_PATH=${MODEL_PATH:-/local_data/zhangyonglin/models/Qwen3.5-4B}

if [ ! -x "$CONDA_ENV/bin/python" ]; then
  echo "Conda environment does not exist: $CONDA_ENV" >&2
  exit 1
fi
if [ ! -x "$CONDA_ENV/bin/swift" ]; then
  echo "MS-Swift executable does not exist: $CONDA_ENV/bin/swift" >&2
  exit 1
fi
if [ ! -f "$MODEL_PATH/config.json" ]; then
  echo "Base model config.json does not exist: $MODEL_PATH" >&2
  exit 1
fi
if [ ! -f "$TAXONOMY_FILE" ]; then
  echo "Taxonomy file does not exist: $TAXONOMY_FILE" >&2
  exit 1
fi

"$CONDA_ENV/bin/python" scripts/check_environment.py --output "$OUTPUT_DIR/environment.json"
"$CONDA_ENV/bin/swift" sft configs/swift_qwen35_4b_smoke.json \
  --model "$MODEL_PATH" \
  --dataset "$TRAIN_FILE#8" \
  --val_dataset "$VALIDATION_FILE" \
  --output_dir "$OUTPUT_DIR"
