#!/usr/bin/env python3
"""Merge V1 local base clusters with streamed AI decisions, one source label at a time."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any, Iterator, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.ai_type_cluster_merge import (
    AIClusterMergeClient,
    PROMPT_VERSION,
    materialize_ai_clusters,
)
from english_knowledge_tagger.local_type_clustering import safe_label_directory_name
from english_knowledge_tagger.type_reclassification import (
    QuestionTypeServiceConfig,
    QuestionTypeServiceError,
)


DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "type-clustering-ai-merge-pilot-v2.json"
DEFAULT_PROMPT = (
    PROJECT_ROOT
    / "configs"
    / "prompts"
    / "question-major-type-cluster-merge-v2.txt"
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
    with path.open("x", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _load_config(path: Path) -> dict[str, Any]:
    config = _read_json(path)
    labels = config.get("source_type_labels")
    profiles = config.get("guidance_profiles")
    assignments = config.get("source_type_guidance_profiles")
    if not isinstance(labels, list) or not labels or any(
        not isinstance(label, str) or not label.strip() for label in labels
    ):
        raise ValueError("source_type_labels must be a non-empty string array")
    if profiles is None and assignments is None:
        return config
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError("guidance_profiles must be a non-empty object when supplied")
    if not isinstance(assignments, dict):
        raise ValueError(
            "source_type_guidance_profiles must be an object when supplied"
        )
    for label in labels:
        profile_name = assignments.get(label)
        if not isinstance(profile_name, str) or profile_name not in profiles:
            raise ValueError(f"missing guidance profile for source label: {label}")
        guidance = profiles[profile_name]
        if not isinstance(guidance, str) or not guidance.strip():
            raise ValueError(f"guidance profile must be non-empty: {profile_name}")
    return config


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
    seen: set[str] = set()
    for cluster in clusters:
        if not isinstance(cluster, dict) or not required.issubset(cluster):
            raise ValueError(f"invalid base cluster for source label: {source_type_label}")
        base_id = cluster["base_cluster_id"]
        if not isinstance(base_id, str) or not base_id or base_id in seen:
            raise ValueError(f"base cluster IDs must be unique: {source_type_label}")
        seen.add(base_id)
    return clusters


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--audit-prompt", type=Path)
    parser.add_argument("--endpoint", action="append")
    parser.add_argument("--model", default="DeepSeek-V4-Flash")
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--api-key-env", default="ENGLISH_TAGGER_DS_V4_API_KEY")
    args = parser.parse_args()

    if args.output_root.exists():
        parser.error("output root already exists; choose a new directory")
    if not args.input_root.is_dir():
        parser.error("input root does not exist or is not a directory")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    if args.max_tokens <= 0:
        parser.error("--max-tokens must be positive")
    if args.max_retries <= 0:
        parser.error("--max-retries must be positive")

    endpoints = args.endpoint or list(DEFAULT_ENDPOINTS)
    try:
        config = _load_config(args.config)
        base_prompt = args.prompt.read_text(encoding="utf-8")
        if not base_prompt.strip():
            raise ValueError("prompt must be non-empty")
        prompt_sha256 = hashlib.sha256(base_prompt.encode("utf-8")).hexdigest()
        audit_prompt = (
            args.audit_prompt.read_text(encoding="utf-8")
            if args.audit_prompt is not None
            else None
        )
        if audit_prompt is not None and not audit_prompt.strip():
            raise ValueError("audit prompt must be non-empty")
        audit_prompt_sha256 = (
            hashlib.sha256(audit_prompt.encode("utf-8")).hexdigest()
            if audit_prompt is not None
            else None
        )
        clients = [
            AIClusterMergeClient(
                QuestionTypeServiceConfig(
                    endpoint=endpoint,
                    model=args.model,
                    max_tokens=args.max_tokens,
                    temperature=0,
                    timeout_seconds=args.timeout_seconds,
                    api_key=os.getenv(args.api_key_env) or None,
                ),
                base_prompt=base_prompt,
                max_retries=args.max_retries,
            )
            for endpoint in endpoints
        ]
        audit_clients = (
            [
                AIClusterMergeClient(
                    QuestionTypeServiceConfig(
                        endpoint=endpoint,
                        model=args.model,
                        max_tokens=args.max_tokens,
                        temperature=0,
                        timeout_seconds=args.timeout_seconds,
                        api_key=os.getenv(args.api_key_env) or None,
                    ),
                    base_prompt=audit_prompt,
                    max_retries=args.max_retries,
                )
                for endpoint in endpoints
            ]
            if audit_prompt is not None
            else []
        )
        args.output_root.mkdir(parents=True)
        manifest: list[dict[str, Any]] = []
        for label_index, source_type_label in enumerate(config["source_type_labels"]):
            directory_name = safe_label_directory_name(source_type_label)
            input_directory = args.input_root / directory_name
            base_path = input_directory / "base-clusters.json"
            members_path = input_directory / "local-cluster-members.jsonl"
            outliers_path = input_directory / "local-outliers.jsonl"
            if not base_path.exists() or not members_path.exists():
                raise ValueError(f"missing V1 cluster files for label: {source_type_label}")
            base_clusters = _validate_base_clusters(
                _read_json(base_path), source_type_label=source_type_label
            )
            profile_name = config.get("source_type_guidance_profiles", {}).get(
                source_type_label
            )
            guidance = (
                config.get("guidance_profiles", {}).get(profile_name)
                if profile_name is not None
                else None
            )
            print(
                json.dumps(
                    {
                        "status": "requesting",
                        "source_type_label": source_type_label,
                        "base_cluster_count": len(base_clusters),
                        "endpoint": endpoints[label_index % len(endpoints)],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            result = clients[label_index % len(clients)].merge(
                source_type_label=source_type_label,
                granularity_guidance=guidance,
                base_clusters=base_clusters,
            )
            initial_clusters, _ = materialize_ai_clusters(
                source_type_label=source_type_label,
                base_clusters=base_clusters,
                decisions=result.decisions,
                representative_count=int(config.get("representative_count", 5)),
            )
            final_result = result
            if audit_clients:
                audit_endpoint_index = (label_index + 1) % len(audit_clients)
                print(
                    json.dumps(
                        {
                            "status": "auditing",
                            "source_type_label": source_type_label,
                            "initial_cluster_count": len(initial_clusters),
                            "endpoint": endpoints[audit_endpoint_index],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                final_result = audit_clients[audit_endpoint_index].audit(
                    source_type_label=source_type_label,
                    base_clusters=base_clusters,
                    initial_decisions=result.decisions,
                )
            clusters, base_to_final = materialize_ai_clusters(
                source_type_label=source_type_label,
                base_clusters=base_clusters,
                decisions=final_result.decisions,
                representative_count=int(config.get("representative_count", 5)),
            )
            members = list(_jsonl_rows(members_path))
            unknown_member_base_ids = {
                row.get("base_cluster_id") for row in members
            } - set(base_to_final)
            if unknown_member_base_ids:
                raise ValueError(
                    f"member rows reference unknown base clusters: {sorted(unknown_member_base_ids)}"
                )
            expected_members = sum(int(cluster["member_count"]) for cluster in clusters)
            if len(members) != expected_members:
                raise ValueError(
                    f"member count mismatch for {source_type_label}: "
                    f"rows={len(members)}, clusters={expected_members}"
                )

            output_directory = args.output_root / directory_name
            output_directory.mkdir()
            if audit_clients:
                _write_json(
                    output_directory / "initial-local-clusters.json",
                    {
                        "schema_version": "ai-local-type-clusters-initial-v1",
                        "source_type_label": source_type_label,
                        "clusters": initial_clusters,
                    },
                )
            _write_json(
                output_directory / "local-clusters.json",
                {
                    "schema_version": "ai-local-type-clusters-v2"
                    if audit_clients
                    else "ai-local-type-clusters-v1",
                    "source_type_label": source_type_label,
                    "clusters": clusters,
                },
            )
            _write_jsonl(
                output_directory / "base-cluster-decisions.jsonl",
                (
                    {
                        "base_cluster_id": base_id,
                        "local_cluster_id": local_cluster_id,
                    }
                    for base_id, local_cluster_id in sorted(base_to_final.items())
                ),
            )
            _write_jsonl(
                output_directory / "local-cluster-members.jsonl",
                (
                    {
                        **row,
                        "local_cluster_id": base_to_final[row["base_cluster_id"]],
                    }
                    for row in members
                ),
            )
            if outliers_path.exists():
                shutil.copyfile(outliers_path, output_directory / "local-outliers.jsonl")
            if audit_clients:
                (output_directory / "initial-raw-response.txt").write_text(
                    result.raw_response.rstrip() + "\n", encoding="utf-8"
                )
                (output_directory / "audit-raw-response.txt").write_text(
                    final_result.raw_response.rstrip() + "\n", encoding="utf-8"
                )
            else:
                (output_directory / "raw-response.txt").write_text(
                    result.raw_response.rstrip() + "\n", encoding="utf-8"
                )
            status_counts = Counter(
                cluster["decision_status"] for cluster in clusters
            )
            report = {
                "schema_version": "ai-local-type-cluster-merge-report-v2"
                if audit_clients
                else "ai-local-type-cluster-merge-report-v1",
                "source_type_label": source_type_label,
                "guidance_profile": profile_name,
                "base_cluster_count": len(base_clusters),
                "initial_cluster_count": len(initial_clusters),
                "cluster_count": len(clusters),
                "merged_base_cluster_count": len(base_clusters) - len(clusters),
                "multi_base_cluster_count": sum(
                    cluster["base_cluster_count"] > 1 for cluster in clusters
                ),
                "candidate_cluster_count": status_counts["candidate"],
                "unresolved_cluster_count": status_counts["unresolved"],
                "clustered_rows": len(members),
                "outlier_rows": sum(1 for _ in _jsonl_rows(outliers_path))
                if outliers_path.exists()
                else 0,
                "request_id": result.request_id,
                "audit_request_id": final_result.request_id
                if audit_clients
                else None,
            }
            _write_json(output_directory / "report.json", report)
            manifest.append({**report, "output_directory": str(output_directory)})
            print(
                json.dumps(
                    {
                        "status": "completed",
                        "source_type_label": source_type_label,
                        "base_cluster_count": len(base_clusters),
                        "cluster_count": len(clusters),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

        root_report = {
            "schema_version": "ai-local-type-cluster-merge-summary-v2"
            if audit_clients
            else "ai-local-type-cluster-merge-summary-v1",
            "input_root": str(args.input_root),
            "output_root": str(args.output_root),
            "config_path": str(args.config),
            "prompt_path": str(args.prompt),
            "prompt_version": config.get("prompt_version", PROMPT_VERSION),
            "prompt_sha256": prompt_sha256,
            "audit_prompt_path": str(args.audit_prompt)
            if args.audit_prompt is not None
            else None,
            "audit_prompt_version": config.get("audit_prompt_version")
            if audit_clients
            else None,
            "audit_prompt_sha256": audit_prompt_sha256,
            "model": args.model,
            "endpoints": endpoints,
            "stream": True,
            "max_tokens": args.max_tokens,
            "labels": manifest,
        }
        _write_json(args.output_root / "pilot-report.json", root_report)
    except (OSError, ValueError, QuestionTypeServiceError) as error:
        parser.error(str(error))

    print(json.dumps(root_report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
