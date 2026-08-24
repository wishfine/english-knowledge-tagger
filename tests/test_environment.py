from english_knowledge_tagger.environment import build_environment_report


def test_environment_report_marks_missing_cuda_as_not_ready():
    report = build_environment_report(
        cuda_available=False,
        gpu_count=0,
        package_versions={
            "torch": "2.5.0",
            "transformers": "4.50.0",
            "peft": "0.14.0",
            "accelerate": "1.2.0",
            "datasets": "3.2.0",
            "bitsandbytes": "0.45.0",
        },
    )

    assert report["ready"] is False
    assert report["problems"] == ["CUDA is unavailable", "no CUDA GPUs are visible"]


def test_environment_report_marks_required_packages_as_not_ready():
    report = build_environment_report(
        cuda_available=True,
        gpu_count=1,
        package_versions={"torch": "2.5.0", "transformers": "4.50.0"},
    )

    assert report["ready"] is False
    assert "missing package: peft" in report["problems"]
