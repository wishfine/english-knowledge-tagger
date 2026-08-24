#!/usr/bin/env bash
# Run full MS-Swift QLoRA SFT with Qwen3.5-9B after the 4B smoke run passes.
set -euo pipefail

if [ "$#" -lt 4 ] || [ "$#" -gt 5 ]; then
  echo "Usage: $0 SWIFT_TRAIN_JSONL SWIFT_VALIDATION_JSONL TAXONOMY_JSON OUTPUT_DIR [RESUME_CHECKPOINT]" >&2
  exit 2
fi

TRAIN_FILE=$1
VALIDATION_FILE=$2
TAXONOMY_FILE=$3
OUTPUT_DIR=$4
RESUME_CHECKPOINT=${5:-}
CONDA_ENV=${CONDA_ENV:-/data/$USER/conda_envs/english-knowledge-tagger-swift}
MODEL_PATH=${MODEL_PATH:-/local_data/zhangyonglin/models/Qwen3.5-9B}

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
TRAIN_COMMAND=("$CONDA_ENV/bin/swift" sft configs/swift_qwen35_9b_production.json)
TRAIN_COMMAND+=(--model "$MODEL_PATH")
TRAIN_COMMAND+=(--dataset "$TRAIN_FILE")
TRAIN_COMMAND+=(--val_dataset "$VALIDATION_FILE")
TRAIN_COMMAND+=(--output_dir "$OUTPUT_DIR")
if [ -n "$RESUME_CHECKPOINT" ]; then
  TRAIN_COMMAND+=(--resume_from_checkpoint "$RESUME_CHECKPOINT")
fi
"${TRAIN_COMMAND[@]}"
