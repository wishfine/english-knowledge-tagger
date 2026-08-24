#!/usr/bin/env python3
"""Generate knowledge-point predictions using a trained LoRA adapter."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.data import load_inference_records, load_taxonomy
from english_knowledge_tagger.parsing import ResponseParseError, parse_response
from english_knowledge_tagger.prompting import build_messages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--adapter-dir", type=Path, required=True)
    parser.add_argument("--input-file", type=Path, required=True)
    parser.add_argument("--output-file", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--max-new-tokens", type=int, default=128)
    parser.add_argument("--load-in-4bit", action="store_true")
    args = parser.parse_args()

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    taxonomy = load_taxonomy(args.taxonomy)
    records = load_inference_records(args.input_file)
    tokenizer = AutoTokenizer.from_pretrained(args.adapter_dir / "tokenizer", trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model_kwargs: dict[str, Any] = {"trust_remote_code": True, "device_map": "auto"}
    if args.load_in_4bit:
        model_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
        )
    else:
        model_kwargs["torch_dtype"] = torch.bfloat16
    model = PeftModel.from_pretrained(
        AutoModelForCausalLM.from_pretrained(args.base_model, **model_kwargs), args.adapter_dir
    )
    model.eval()
    input_device = next(model.parameters()).device

    rows: list[dict[str, object]] = []
    for record in records:
        encoded = tokenizer.apply_chat_template(
            build_messages(record), add_generation_prompt=True, return_tensors="pt", return_dict=True
        ).to(input_device)
        with torch.inference_mode():
            generated = model.generate(
                **encoded,
                max_new_tokens=args.max_new_tokens,
                do_sample=False,
                pad_token_id=tokenizer.pad_token_id,
            )
        prompt_length = encoded["input_ids"].shape[1]
        response_text = tokenizer.decode(generated[0][prompt_length:], skip_special_tokens=True)
        try:
            labels = parse_response(response_text, taxonomy)
            parse_error = None
        except ResponseParseError as error:
            labels = []
            parse_error = str(error)
        row: dict[str, object] = {"id": record.id, "knowledge_points": labels}
        if parse_error:
            row["parse_error"] = parse_error
        rows.append(row)

    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    args.output_file.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
