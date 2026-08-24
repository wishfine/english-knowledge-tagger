#!/usr/bin/env python3
"""Print a fail-fast JSON report for the LoRA training runtime."""

from __future__ import annotations

import argparse
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.environment import REQUIRED_PACKAGES, build_environment_report


def package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for package in REQUIRED_PACKAGES:
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            continue
    return versions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="optional JSON report path")
    args = parser.parse_args()
    try:
        import torch

        cuda_available = torch.cuda.is_available()
        gpu_count = torch.cuda.device_count() if cuda_available else 0
        torch_version = torch.__version__
    except ImportError:
        cuda_available = False
        gpu_count = 0
        torch_version = ""
    versions = package_versions()
    if torch_version:
        versions["torch"] = torch_version
    report = build_environment_report(
        cuda_available=cuda_available,
        gpu_count=gpu_count,
        package_versions=versions,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if not report["ready"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
