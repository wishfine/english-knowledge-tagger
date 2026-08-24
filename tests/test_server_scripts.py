from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_smoke_script_uses_4b_and_ms_swift_model_argument():
    script = (ROOT / "scripts" / "server_smoke.sh").read_text(encoding="utf-8")

    assert "Qwen3.5-4B" in script
    assert '--model "$MODEL_PATH"' in script
    assert "--base-model" not in script


def test_server_scripts_require_a_taxonomy_file_before_training():
    for filename in ("server_smoke.sh", "server_train.sh"):
        script = (ROOT / "scripts" / filename).read_text(encoding="utf-8")

        assert 'if [ ! -f "$TAXONOMY_FILE" ]' in script
