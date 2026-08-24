"""Runtime readiness checks for the GPU fine-tuning environment."""

from __future__ import annotations

from typing import Mapping


REQUIRED_PACKAGES = ("torch", "transformers", "peft", "accelerate", "datasets", "bitsandbytes")


def build_environment_report(
    *, cuda_available: bool, gpu_count: int, package_versions: Mapping[str, str]
) -> dict[str, object]:
    """Create a JSON-serializable readiness report without mutating the runtime."""
    problems: list[str] = []
    if not cuda_available:
        problems.append("CUDA is unavailable")
    if gpu_count <= 0:
        problems.append("no CUDA GPUs are visible")
    for package in REQUIRED_PACKAGES:
        if not package_versions.get(package):
            problems.append(f"missing package: {package}")
    return {
        "ready": not problems,
        "cuda_available": cuda_available,
        "gpu_count": gpu_count,
        "required_packages": list(REQUIRED_PACKAGES),
        "package_versions": dict(sorted(package_versions.items())),
        "problems": problems,
    }
