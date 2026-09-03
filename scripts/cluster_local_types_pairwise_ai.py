#!/usr/bin/env python3
"""Cluster V1 bases via streamed pairwise AI decisions, then name fixed groups."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any, Iterator, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.local_type_clustering import safe_label_directory_name
from english_knowledge_tagger.pairwise_type_clustering import (
    NAMING_PROMPT_VERSION,
    PAIR_PROMPT_VERSION,
    PairwiseTypeClient,
    make_local_cluster_id,
    strict_complete_link_groups,
)
from english_knowledge_tagger.type_reclassification import (
    QuestionTypeServiceConfig,
    QuestionTypeServiceError,
)


DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "type-clustering-pairwise-ai-pilot-v1.json"
DEFAULT_PAIR_PROMPT = (
    PROJECT_ROOT
    / "configs"
    / "prompts"
    / "question-major-type-pairwise-equivalence-v1.txt"
)
DEFAULT_NAMING_PROMPT = (
    PROJECT_ROOT
    / "configs"
    / "prompts"
    / "question-major-type-cluster-naming-v1.txt"
)
DEFAULT_ENDPOINTS = (
    "http://172.22.0.35:9102/v1/chat/completions",
    "http://172.22.0.35:9103/v1/chat/completions",
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return payload


def _jsonl_rows(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path} line {line_number}: invalid JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"{path} line {line_number}: expected an object")
            yield row


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Iterator[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _pair_key(left_id: str, right_id: str) -> tuple[str, str]:
    left, right = sorted((left_id, right_id))
    if left == right:
        raise ValueError("a pair must contain two different base clusters")
    return left, right


def _all_pairs(base_clusters: Sequence[Mapping[str, Any]]) -> list[tuple[str, str]]:
    ids = sorted(str(cluster["base_cluster_id"]) for cluster in base_clusters)
    return [
        (ids[left], ids[right])
        for left in range(len(ids))
        for right in range(left + 1, len(ids))
    ]


def _load_pair_decisions(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    decisions: dict[tuple[str, str], dict[str, Any]] = {}
    for row in _jsonl_rows(path):
        key = _pair_key(row.get("base_cluster_id_a"), row.get("base_cluster_id_b"))
        decision = {
            field: row[field]
            for field in (
                "same_type",
                "same_primary_operation",
                "same_answer_generation",
                "same_required_support",
                "confidence",
            )
        }
        previous = decisions.get(key)
        if previous is not None and previous != decision:
            raise ValueError(f"conflicting saved pair decision: {key}")
        decisions[key] = decision
    return decisions


def _validate_config(payload: Mapping[str, Any]) -> tuple[list[str], float, int]:
    labels = payload.get("source_type_labels")
    if not isinstance(labels, list) or not labels or any(
        not isinstance(label, str) or not label.strip() for label in labels
    ):
        raise ValueError("source_type_labels must be a non-empty string array")
    threshold = payload.get("minimum_merge_confidence")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ValueError("minimum_merge_confidence must be numeric")
    if not 0 <= threshold <= 1:
        raise ValueError("minimum_merge_confidence must be between 0 and 1")
    representative_count = payload.get("representative_count", 5)
    if not isinstance(representative_count, int) or representative_count <= 0:
        raise ValueError("representative_count must be a positive integer")
    return labels, float(threshold), representative_count


def _validate_base_clusters(
    payload: Mapping[str, Any], *, source_type_label: str
) -> list[dict[str, Any]]:
    if payload.get("source_type_label") != source_type_label:
        raise ValueError(f"base-clusters.json source label mismatch: {source_type_label}")
    clusters = payload.get("clusters")
    if not isinstance(clusters, list) or not clusters:
        raise ValueError(f"base-clusters.json has no clusters: {source_type_label}")
    required = {
        "base_cluster_id",
        "member_count",
        "candidate_label_counts",
        "canonical_task_mechanism",
    }
    ids: set[str] = set()
    for cluster in clusters:
        if not isinstance(cluster, dict) or not required.issubset(cluster):
            raise ValueError(f"invalid base cluster: {source_type_label}")
        base_id = cluster["base_cluster_id"]
        if not isinstance(base_id, str) or not base_id or base_id in ids:
            raise ValueError(f"base cluster IDs must be unique: {source_type_label}")
        ids.add(base_id)
    return clusters


def _materialize_clusters(
    *,
    source_type_label: str,
    groups: Sequence[Sequence[str]],
    base_clusters: Sequence[Mapping[str, Any]],
    naming_decisions: Sequence[Mapping[str, Any]],
    representative_count: int,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    by_base_id = {str(cluster["base_cluster_id"]): cluster for cluster in base_clusters}
    by_local_id = {
        str(decision["local_cluster_id"]): decision for decision in naming_decisions
    }
    output: list[dict[str, Any]] = []
    base_to_local: dict[str, str] = {}
    for group in groups:
        local_id = make_local_cluster_id(group)
        naming = by_local_id[local_id]
        label_counts: Counter[str] = Counter()
        representatives: list[str] = []
        member_count = 0
        for base_id in sorted(group):
            base = by_base_id[base_id]
            base_to_local[base_id] = local_id
            member_count += int(base["member_count"])
            label_counts.update(
                {key: int(value) for key, value in base["candidate_label_counts"].items()}
            )
            for question_id in base.get("representative_question_ids", []):
                if question_id not in representatives:
                    representatives.append(question_id)
        output.append(
            {
                "local_cluster_id": local_id,
                "source_type_label": source_type_label,
                "canonical_type_label": naming["canonical_type_label"],
                "canonical_task_mechanism": naming["canonical_task_mechanism"],
                "decision_status": naming["decision_status"],
                "base_cluster_ids": sorted(group),
                "base_cluster_count": len(group),
                "member_count": member_count,
                "candidate_label_counts": dict(sorted(label_counts.items())),
                "representative_question_ids": representatives[:representative_count],
            }
        )
    output.sort(key=lambda cluster: (-cluster["member_count"], cluster["local_cluster_id"]))
    return output, base_to_local


def _client(
    *,
    endpoint: str,
    model: str,
    max_tokens: int,
    timeout_seconds: float,
    api_key: str | None,
    pair_prompt: str,
    naming_prompt: str,
    max_retries: int,
) -> PairwiseTypeClient:
    return PairwiseTypeClient(
        QuestionTypeServiceConfig(
            endpoint=endpoint,
            model=model,
            max_tokens=max_tokens,
            temperature=0,
            timeout_seconds=timeout_seconds,
            api_key=api_key,
        ),
        pair_prompt=pair_prompt,
        naming_prompt=naming_prompt,
        max_retries=max_retries,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--pair-prompt", type=Path, default=DEFAULT_PAIR_PROMPT)
    parser.add_argument("--naming-prompt", type=Path, default=DEFAULT_NAMING_PROMPT)
    parser.add_argument("--endpoint", action="append")
    parser.add_argument("--model", default="DeepSeek-V4-Flash")
    parser.add_argument("--per-endpoint-concurrency", type=int, default=15)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--pair-max-tokens", type=int, default=256)
    parser.add_argument("--naming-max-tokens", type=int, default=4096)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--api-key-env", default="ENGLISH_TAGGER_DS_V4_API_KEY")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    if args.output_root.exists() and not args.resume:
        parser.error("output root already exists; use --resume or choose a new directory")
    if not args.input_root.is_dir():
        parser.error("input root does not exist or is not a directory")
    if args.per_endpoint_concurrency <= 0:
        parser.error("--per-endpoint-concurrency must be positive")
    if args.timeout_seconds <= 0 or args.max_retries <= 0:
        parser.error("timeout and retries must be positive")
    if args.pair_max_tokens <= 0 or args.naming_max_tokens <= 0:
        parser.error("token limits must be positive")

    endpoints = args.endpoint or list(DEFAULT_ENDPOINTS)
    try:
        config = _read_json(args.config)
        labels, min_confidence, representative_count = _validate_config(config)
        pair_prompt = args.pair_prompt.read_text(encoding="utf-8")
        naming_prompt = args.naming_prompt.read_text(encoding="utf-8")
        if not pair_prompt.strip() or not naming_prompt.strip():
            raise ValueError("prompts must be non-empty")
        api_key = os.getenv(args.api_key_env) or None
        pair_clients = [
            _client(
                endpoint=endpoint,
                model=args.model,
                max_tokens=args.pair_max_tokens,
                timeout_seconds=args.timeout_seconds,
                api_key=api_key,
                pair_prompt=pair_prompt,
                naming_prompt=naming_prompt,
                max_retries=args.max_retries,
            )
            for endpoint in endpoints
            for _ in range(args.per_endpoint_concurrency)
        ]
        naming_clients = [
            _client(
                endpoint=endpoint,
                model=args.model,
                max_tokens=args.naming_max_tokens,
                timeout_seconds=args.timeout_seconds,
                api_key=api_key,
                pair_prompt=pair_prompt,
                naming_prompt=naming_prompt,
                max_retries=args.max_retries,
            )
            for endpoint in endpoints
        ]

        args.output_root.mkdir(parents=True, exist_ok=True)
        manifest: list[dict[str, Any]] = []
        for label_index, source_type_label in enumerate(labels):
            directory_name = safe_label_directory_name(source_type_label)
            input_directory = args.input_root / directory_name
            output_directory = args.output_root / directory_name
            output_directory.mkdir(exist_ok=True)
            base_path = input_directory / "base-clusters.json"
            members_path = input_directory / "local-cluster-members.jsonl"
            outliers_path = input_directory / "local-outliers.jsonl"
            if not base_path.exists() or not members_path.exists():
                raise ValueError(f"missing V1 cluster files for label: {source_type_label}")
            base_clusters = _validate_base_clusters(
                _read_json(base_path), source_type_label=source_type_label
            )
            by_id = {
                str(cluster["base_cluster_id"]): cluster for cluster in base_clusters
            }
            required_pairs = _all_pairs(base_clusters)
            pair_path = output_directory / "pair-decisions.jsonl"
            saved = _load_pair_decisions(pair_path)
            unknown_saved = set(saved) - set(required_pairs)
            if unknown_saved:
                raise ValueError(f"saved decisions contain unknown pairs: {unknown_saved}")
            missing_pairs = [pair for pair in required_pairs if pair not in saved]
            print(
                json.dumps(
                    {
                        "status": "comparing",
                        "source_type_label": source_type_label,
                        "base_cluster_count": len(base_clusters),
                        "total_pair_count": len(required_pairs),
                        "saved_pair_count": len(saved),
                        "remaining_pair_count": len(missing_pairs),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

            failures: list[dict[str, Any]] = []
            if missing_pairs:
                with pair_path.open("a", encoding="utf-8") as output, ThreadPoolExecutor(
                    max_workers=len(pair_clients)
                ) as executor:
                    futures = {}
                    for pair_index, (left_id, right_id) in enumerate(missing_pairs):
                        client = pair_clients[pair_index % len(pair_clients)]
                        future = executor.submit(
                            client.compare, by_id[left_id], by_id[right_id]
                        )
                        futures[future] = (left_id, right_id)
                    completed = 0
                    for future in as_completed(futures):
                        left_id, right_id = futures[future]
                        completed += 1
                        try:
                            result = future.result()
                        except Exception as error:
                            failures.append(
                                {
                                    "base_cluster_id_a": left_id,
                                    "base_cluster_id_b": right_id,
                                    "error": str(error),
                                }
                            )
                        else:
                            row = {
                                "base_cluster_id_a": left_id,
                                "base_cluster_id_b": right_id,
                                **result.decision,
                            }
                            output.write(
                                json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                            )
                            output.flush()
                            saved[(left_id, right_id)] = result.decision
                        if completed % 25 == 0 or completed == len(missing_pairs):
                            print(
                                json.dumps(
                                    {
                                        "status": "pair_progress",
                                        "source_type_label": source_type_label,
                                        "completed_this_run": completed,
                                        "remaining_this_run": len(missing_pairs) - completed,
                                        "failures_this_run": len(failures),
                                    },
                                    ensure_ascii=False,
                                ),
                                flush=True,
                            )
            if failures:
                error_path = output_directory / "pair-errors.jsonl"
                with error_path.open("a", encoding="utf-8") as output:
                    for row in failures:
                        output.write(
                            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                        )
                raise QuestionTypeServiceError(
                    f"{source_type_label}: {len(failures)} pair requests failed; rerun with --resume"
                )

            groups = strict_complete_link_groups(
                sorted(by_id), saved, min_confidence=min_confidence
            )
            print(
                json.dumps(
                    {
                        "status": "naming",
                        "source_type_label": source_type_label,
                        "cluster_count": len(groups),
                        "endpoint": endpoints[label_index % len(endpoints)],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            naming_result = naming_clients[label_index % len(naming_clients)].name(
                groups=groups, base_clusters=base_clusters
            )
            clusters, base_to_local = _materialize_clusters(
                source_type_label=source_type_label,
                groups=groups,
                base_clusters=base_clusters,
                naming_decisions=naming_result.decisions,
                representative_count=representative_count,
            )
            members = list(_jsonl_rows(members_path))
            if {row.get("base_cluster_id") for row in members} - set(base_to_local):
                raise ValueError(f"member rows reference unknown bases: {source_type_label}")
            expected_member_count = sum(cluster["member_count"] for cluster in clusters)
            if len(members) != expected_member_count:
                raise ValueError(f"member count mismatch: {source_type_label}")

            _write_json(
                output_directory / "local-clusters.json",
                {
                    "schema_version": "pairwise-ai-local-type-clusters-v1",
                    "source_type_label": source_type_label,
                    "clusters": clusters,
                },
            )
            _write_jsonl(
                output_directory / "base-cluster-decisions.jsonl",
                (
                    {"base_cluster_id": base_id, "local_cluster_id": local_id}
                    for base_id, local_id in sorted(base_to_local.items())
                ),
            )
            _write_jsonl(
                output_directory / "local-cluster-members.jsonl",
                (
                    {**row, "local_cluster_id": base_to_local[row["base_cluster_id"]]}
                    for row in members
                ),
            )
            if outliers_path.exists():
                shutil.copyfile(outliers_path, output_directory / "local-outliers.jsonl")
            (output_directory / "naming-raw-response.txt").write_text(
                naming_result.raw_response.rstrip() + "\n", encoding="utf-8"
            )
            report = {
                "schema_version": "pairwise-ai-local-type-cluster-report-v1",
                "source_type_label": source_type_label,
                "base_cluster_count": len(base_clusters),
                "pair_count": len(required_pairs),
                "mergeable_pair_count": sum(
                    decision["same_type"]
                    and decision["same_primary_operation"]
                    and decision["same_answer_generation"]
                    and decision["same_required_support"]
                    and decision["confidence"] >= min_confidence
                    for decision in saved.values()
                ),
                "minimum_merge_confidence": min_confidence,
                "cluster_count": len(clusters),
                "multi_base_cluster_count": sum(
                    cluster["base_cluster_count"] > 1 for cluster in clusters
                ),
                "clustered_rows": len(members),
                "outlier_rows": sum(1 for _ in _jsonl_rows(outliers_path)),
                "naming_request_id": naming_result.request_id,
            }
            _write_json(output_directory / "report.json", report)
            manifest.append({**report, "output_directory": str(output_directory)})
            print(
                json.dumps(
                    {
                        "status": "completed",
                        "source_type_label": source_type_label,
                        "cluster_count": len(clusters),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

        root_report = {
            "schema_version": "pairwise-ai-local-type-clustering-summary-v1",
            "input_root": str(args.input_root),
            "output_root": str(args.output_root),
            "config_path": str(args.config),
            "pair_prompt_path": str(args.pair_prompt),
            "pair_prompt_version": config.get("pair_prompt_version", PAIR_PROMPT_VERSION),
            "pair_prompt_sha256": hashlib.sha256(pair_prompt.encode("utf-8")).hexdigest(),
            "naming_prompt_path": str(args.naming_prompt),
            "naming_prompt_version": config.get(
                "naming_prompt_version", NAMING_PROMPT_VERSION
            ),
            "naming_prompt_sha256": hashlib.sha256(
                naming_prompt.encode("utf-8")
            ).hexdigest(),
            "model": args.model,
            "endpoints": endpoints,
            "stream": True,
            "per_endpoint_concurrency": args.per_endpoint_concurrency,
            "pair_max_tokens": args.pair_max_tokens,
            "naming_max_tokens": args.naming_max_tokens,
            "labels": manifest,
        }
        _write_json(args.output_root / "pilot-report.json", root_report)
    except (OSError, ValueError, QuestionTypeServiceError) as error:
        parser.error(str(error))

    print(json.dumps(root_report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
