#!/usr/bin/env python3
"""Run no-DS local clustering for configured major-question source labels."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Iterator, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.local_type_clustering import (
    LocalTypeClusteringError,
    cluster_local_results,
    safe_label_directory_name,
)


DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "type-clustering-pilot-v5.json"

OUTPUT_FILE_NAMES = (
    "base-clusters.json",
    "local-clusters.json",
    "local-cluster-members.jsonl",
    "local-outliers.jsonl",
    "report.json",
)


def _jsonl_rows(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path} line {line_number}: invalid JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"{path} line {line_number}: row must be an object")
            yield row


def _load_config(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("clustering config must be a JSON object")
    labels = payload.get("source_type_labels")
    if not isinstance(labels, list) or not labels or any(
        not isinstance(label, str) or not label for label in labels
    ):
        raise ValueError("source_type_labels must be a non-empty string array")
    return payload


def _completed_results(results_root: Path) -> dict[str, tuple[Path, Path, Mapping[str, Any]]]:
    found: dict[str, tuple[Path, Path, Mapping[str, Any]]] = {}
    for report_path in results_root.rglob("report.json"):
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if not isinstance(report, Mapping):
            raise ValueError(f"{report_path}: report must be an object")
        label = report.get("current_type_label")
        if not isinstance(label, str) or not label:
            continue
        result_path = report_path.parent / "results.jsonl"
        if not result_path.exists():
            configured = report.get("result_path")
            if isinstance(configured, str):
                result_path = Path(configured)
        if not result_path.exists():
            raise ValueError(f"{report_path}: result file does not exist")
        if label in found:
            raise ValueError(f"multiple completed result directories for label: {label}")
        found[label] = (result_path, report_path, report)
    return found


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Iterator[Mapping[str, Any]] | list[Mapping[str, Any]]) -> None:
    with path.open("x", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace only the known clustering output files in an existing output root",
    )
    args = parser.parse_args()

    if args.output_root.exists() and not args.overwrite:
        parser.error("output root already exists; use --overwrite to replace its clustering files")
    try:
        config = _load_config(args.config)
        completed = _completed_results(args.results_root)
        missing = [label for label in config["source_type_labels"] if label not in completed]
        if missing:
            raise ValueError(f"configured labels are not complete: {missing}")
        args.output_root.mkdir(parents=True, exist_ok=args.overwrite)
        manifest: list[dict[str, Any]] = []
        labels = config["source_type_labels"]
        total_labels = len(labels)
        print(f"共需处理 {total_labels} 个题型标签", flush=True)
        for label_index, label in enumerate(labels, 1):
            print(f"[{label_index}/{total_labels}] 开始处理: {label}", flush=True)
            result_path, report_path, source_report = completed[label]
            rows = list(_jsonl_rows(result_path))
            clustered = cluster_local_results(
                rows,
                source_type_label=label,
                core_confidence_threshold=float(config["core_confidence_threshold"]),
                auxiliary_confidence_threshold=float(
                    config["auxiliary_confidence_threshold"]
                ),
                local_distance_threshold=float(config["local_distance_threshold"]),
                merge_distance_threshold=float(config["merge_distance_threshold"]),
                auxiliary_similarity_threshold=float(
                    config["auxiliary_similarity_threshold"]
                ),
                candidate_label_weight=float(config["candidate_label_weight"]),
                task_mechanism_weight=float(config["task_mechanism_weight"]),
                merge_candidate_label_weight=float(
                    config["merge_candidate_label_weight"]
                ),
                merge_task_mechanism_weight=float(
                    config["merge_task_mechanism_weight"]
                ),
                representative_count=int(config["representative_count"]),
            )
            label_output = args.output_root / safe_label_directory_name(label)
            label_output.mkdir(exist_ok=args.overwrite)
            if args.overwrite:
                for file_name in OUTPUT_FILE_NAMES:
                    output_file = label_output / file_name
                    if output_file.exists():
                        output_file.unlink()
            _write_json(
                label_output / "base-clusters.json",
                {
                    "schema_version": "local-type-base-clusters-pilot-v5",
                    "source_type_label": label,
                    "clusters": clustered["base_clusters"],
                },
            )
            _write_json(
                label_output / "local-clusters.json",
                {
                    "schema_version": "local-type-clusters-pilot-v5",
                    "source_type_label": label,
                    "clusters": clustered["clusters"],
                },
            )
            _write_jsonl(
                label_output / "local-cluster-members.jsonl", clustered["members"]
            )
            _write_jsonl(label_output / "local-outliers.jsonl", clustered["outliers"])
            report = {
                "schema_version": "local-type-clustering-pilot-report-v5",
                "source_result_path": str(result_path),
                "source_report_path": str(report_path),
                "source_prompt_version": source_report.get("prompt_version"),
                **clustered["report"],
            }
            _write_json(label_output / "report.json", report)
            manifest.append(
                {
                    "source_type_label": label,
                    "output_directory": str(label_output),
                    "cluster_count": report["cluster_count"],
                    "base_cluster_count": report["base_cluster_count"],
                    "split_base_cluster_count": report["split_base_cluster_count"],
                    "multi_base_final_cluster_count": report[
                        "multi_base_final_cluster_count"
                    ],
                    "candidate_label_group_count": report["candidate_label_group_count"],
                    "stable_cluster_count": report["stable_cluster_count"],
                    "micro_cluster_count": report["micro_cluster_count"],
                    "unresolved_cluster_count": report["unresolved_cluster_count"],
                    "unresolved_row_count": report["unresolved_row_count"],
                    "clustered_rows": report["clustered_rows"],
                    "outlier_rows": report["outlier_rows"],
                }
            )
            print(
                f"[{label_index}/{total_labels}] 处理完成: {label} | "
                f"题目={len(rows)} | 基础簇={report['base_cluster_count']} | "
                f"聚类簇={report['cluster_count']} | 异常={report['outlier_rows']}",
                flush=True,
            )
        _write_json(
            args.output_root / "pilot-report.json",
            {
                "schema_version": "local-type-clustering-pilot-summary-v5",
                "config_path": str(args.config),
                "results_root": str(args.results_root),
                "labels": manifest,
            },
        )
    except (LocalTypeClusteringError, OSError, ValueError) as error:
        parser.error(str(error))

    print(json.dumps({"output_root": str(args.output_root), "labels": manifest}, ensure_ascii=False))


if __name__ == "__main__":
    main()
