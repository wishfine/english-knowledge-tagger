import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_profile(filename):
    return json.loads((ROOT / "configs" / filename).read_text(encoding="utf-8"))


def test_4b_profile_is_explicitly_limited_to_smoke_validation():
    profile = load_profile("qwen35_4b_qlora.json")

    assert profile["base_model"] == "Qwen/Qwen3.5-4B"
    assert profile["profile"] == "smoke"
    assert profile["max_train_samples"] == 8


def test_9b_profile_is_the_default_full_training_profile():
    profile = load_profile("qwen35_9b_qlora.json")

    assert profile["base_model"] == "Qwen/Qwen3.5-9B"
    assert profile["profile"] == "production"
    assert profile["use_qlora"] is True
    assert profile["num_train_epochs"] == 2
