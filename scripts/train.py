#!/usr/bin/env python3
"""Fine-tune a causal language model to emit controlled knowledge-point JSON."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.data import load_records, load_taxonomy
from english_knowledge_tagger.training_data import build_training_example


def load_config(path: Path) -> dict[str, Any]:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load training config {path}: {error}") from error
    if not isinstance(config, dict):
        raise ValueError("training config must be a JSON object")
    return config


def config_value(args: argparse.Namespace, config: dict[str, Any], name: str) -> Any:
    value = getattr(args, name)
    if value is not None:
        return value
    if name not in config:
        raise ValueError(f"missing required setting {name!r} in both CLI and config")
    return config[name]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--train-file", type=Path, required=True)
    parser.add_argument("--validation-file", type=Path)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-model")
    parser.add_argument("--resume-from-checkpoint", type=Path)
    parser.add_argument("--max-train-samples", type=int)
    args = parser.parse_args()
    config = load_config(args.config)

    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        DataCollatorForSeq2Seq,
        Trainer,
        TrainingArguments,
    )

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for training; run scripts/check_environment.py on the target server")
    base_model = config_value(args, config, "base_model")
    max_length = int(config_value(args, config, "max_length"))
    use_qlora = bool(config_value(args, config, "use_qlora"))
    bf16 = bool(config_value(args, config, "bf16"))
    taxonomy = load_taxonomy(args.taxonomy)
    train_records = load_records(args.train_file, taxonomy)
    validation_records = load_records(args.validation_file, taxonomy) if args.validation_file else []
    if args.max_train_samples is not None:
        if args.max_train_samples <= 0:
            raise ValueError("max_train_samples must be positive")
        train_records = train_records[: args.max_train_samples]

    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    model_kwargs: dict[str, Any] = {"trust_remote_code": True}
    if use_qlora:
        compute_dtype = torch.bfloat16 if bf16 else torch.float16
        model_kwargs.update(
            quantization_config=BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=compute_dtype,
            ),
            device_map="auto",
        )
    else:
        model_kwargs["torch_dtype"] = torch.bfloat16 if bf16 else torch.float16
    model = AutoModelForCausalLM.from_pretrained(base_model, **model_kwargs)
    if use_qlora:
        model = prepare_model_for_kbit_training(model)
    if bool(config.get("gradient_checkpointing", True)):
        model.config.use_cache = False
        model.enable_input_require_grads()

    lora_config = LoraConfig(
        r=int(config_value(args, config, "lora_r")),
        lora_alpha=int(config_value(args, config, "lora_alpha")),
        lora_dropout=float(config_value(args, config, "lora_dropout")),
        target_modules=list(config_value(args, config, "target_modules")),
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    train_dataset = Dataset.from_list(
        [build_training_example(tokenizer, record, max_length) for record in train_records]
    )
    validation_dataset = (
        Dataset.from_list([build_training_example(tokenizer, record, max_length) for record in validation_records])
        if validation_records
        else None
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    training_arguments = TrainingArguments(
        output_dir=str(args.output_dir),
        learning_rate=float(config_value(args, config, "learning_rate")),
        num_train_epochs=float(config_value(args, config, "num_train_epochs")),
        per_device_train_batch_size=int(config_value(args, config, "per_device_train_batch_size")),
        per_device_eval_batch_size=int(config_value(args, config, "per_device_eval_batch_size")),
        gradient_accumulation_steps=int(config_value(args, config, "gradient_accumulation_steps")),
        gradient_checkpointing=bool(config.get("gradient_checkpointing", True)),
        bf16=bf16,
        fp16=not bf16,
        logging_steps=int(config_value(args, config, "logging_steps")),
        save_steps=int(config_value(args, config, "save_steps")),
        eval_steps=int(config_value(args, config, "eval_steps")),
        save_total_limit=int(config_value(args, config, "save_total_limit")),
        eval_strategy="steps" if validation_dataset is not None else "no",
        save_strategy="steps",
        report_to=[],
        remove_unused_columns=False,
        label_names=["labels"],
        optim="paged_adamw_8bit" if use_qlora else "adamw_torch",
        seed=int(config_value(args, config, "seed")),
    )
    trainer = Trainer(
        model=model,
        args=training_arguments,
        train_dataset=train_dataset,
        eval_dataset=validation_dataset,
        data_collator=DataCollatorForSeq2Seq(tokenizer=tokenizer, label_pad_token_id=-100, padding=True),
    )
    trainer.train(resume_from_checkpoint=str(args.resume_from_checkpoint) if args.resume_from_checkpoint else None)
    adapter_dir = args.output_dir / "adapter"
    trainer.save_model(str(adapter_dir))
    tokenizer.save_pretrained(adapter_dir / "tokenizer")
    (args.output_dir / "training_config.json").write_text(
        json.dumps(
            {
                "base_model": base_model,
                "config": config,
                "train_records": len(train_records),
                "validation_records": len(validation_records),
                "max_length": max_length,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    if validation_dataset is not None:
        metrics = trainer.evaluate()
        (args.output_dir / "validation_loss.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
