"""AI-assisted merge-only grouping for local question-type base clusters."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Callable, Mapping, Sequence

from .type_reclassification import (
    QuestionTypeServiceConfig,
    QuestionTypeServiceError,
    StreamCompletion,
    _stream_http_transport,
)


PROMPT_VERSION = "question-major-type-cluster-merge-v1"
DECISION_FIELDS = {
    "canonical_type_label",
    "canonical_task_mechanism",
    "decision_status",
    "base_cluster_ids",
}
ALLOWED_DECISION_STATUSES = {"candidate", "unresolved"}


@dataclass(frozen=True)
class AIClusterMergeResult:
    decisions: list[dict[str, Any]]
    raw_response: str
    request_id: str | None
    model: str


StreamTransport = Callable[
    [str, dict[str, Any], float, Mapping[str, str]], StreamCompletion
]


def build_cluster_merge_prompt(
    base_prompt: str,
    *,
    source_type_label: str,
    granularity_guidance: str | None = None,
    base_clusters: Sequence[Mapping[str, Any]],
) -> str:
    """Build one label-level request from compact V1 base-cluster summaries."""
    if not base_prompt.strip():
        raise ValueError("cluster merge prompt must be non-empty")
    if not source_type_label.strip():
        raise ValueError("source_type_label must be non-empty")
    summaries = []
    for cluster in base_clusters:
        summaries.append(
            {
                "base_cluster_id": cluster.get("base_cluster_id"),
                "member_count": cluster.get("member_count"),
                "candidate_label_counts": cluster.get("candidate_label_counts"),
                "canonical_task_mechanism": cluster.get(
                    "canonical_task_mechanism"
                ),
            }
        )
    payload = {
        "source_type_label": source_type_label,
        "base_clusters": summaries,
    }
    if granularity_guidance is not None:
        if not granularity_guidance.strip():
            raise ValueError("granularity guidance must be non-empty when supplied")
        payload["granularity_guidance"] = granularity_guidance
    return (
        f"{base_prompt.strip()}\n\n"
        "--------------------------------\n"
        "本批基础簇信息\n"
        "--------------------------------\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)}"
    )


def _strip_json_fence(text: str) -> str:
    normalized = text.strip()
    if normalized.startswith("```") and normalized.endswith("```"):
        lines = normalized.splitlines()
        if len(lines) >= 3:
            normalized = "\n".join(lines[1:-1]).strip()
    return normalized


def parse_cluster_merge_response(
    text: str, *, expected_base_cluster_ids: set[str]
) -> list[dict[str, Any]]:
    """Parse a complete partition of the supplied base-cluster IDs."""
    try:
        payload = json.loads(_strip_json_fence(text))
    except json.JSONDecodeError as error:
        raise QuestionTypeServiceError(
            "cluster merge response must be one complete JSON object"
        ) from error
    if not isinstance(payload, dict) or set(payload) != {"clusters"}:
        raise QuestionTypeServiceError(
            "cluster merge response must contain only the clusters field"
        )
    decisions = payload["clusters"]
    if not isinstance(decisions, list) or not decisions:
        raise QuestionTypeServiceError("clusters must be a non-empty array")

    seen: set[str] = set()
    normalized_decisions: list[dict[str, Any]] = []
    for index, decision in enumerate(decisions, 1):
        if not isinstance(decision, dict) or set(decision) != DECISION_FIELDS:
            raise QuestionTypeServiceError(
                f"cluster {index} fields must be exactly {sorted(DECISION_FIELDS)}"
            )
        label = decision["canonical_type_label"]
        mechanism = decision["canonical_task_mechanism"]
        status = decision["decision_status"]
        base_ids = decision["base_cluster_ids"]
        if not isinstance(label, str) or not label.strip() or "\n" in label:
            raise QuestionTypeServiceError(
                f"cluster {index} canonical_type_label must be one non-empty line"
            )
        if "题型@" in label:
            raise QuestionTypeServiceError(
                f"cluster {index} canonical_type_label must be a flat label"
            )
        if not isinstance(mechanism, str) or not mechanism.strip():
            raise QuestionTypeServiceError(
                f"cluster {index} canonical_task_mechanism must be non-empty"
            )
        if status not in ALLOWED_DECISION_STATUSES:
            raise QuestionTypeServiceError(
                f"cluster {index} decision_status must be candidate or unresolved"
            )
        if not isinstance(base_ids, list) or not base_ids or any(
            not isinstance(base_id, str) or not base_id for base_id in base_ids
        ):
            raise QuestionTypeServiceError(
                f"cluster {index} base_cluster_ids must be a non-empty string array"
            )
        duplicate_ids = seen.intersection(base_ids)
        if duplicate_ids:
            raise QuestionTypeServiceError(
                f"base clusters assigned more than once: {sorted(duplicate_ids)}"
            )
        unknown_ids = set(base_ids) - expected_base_cluster_ids
        if unknown_ids:
            raise QuestionTypeServiceError(
                f"response contains unknown base clusters: {sorted(unknown_ids)}"
            )
        seen.update(base_ids)
        normalized_decisions.append(
            {
                "canonical_type_label": label.strip(),
                "canonical_task_mechanism": mechanism.strip(),
                "decision_status": status,
                "base_cluster_ids": sorted(base_ids),
            }
        )
    missing_ids = expected_base_cluster_ids - seen
    if missing_ids:
        raise QuestionTypeServiceError(
            f"response omitted base clusters: {sorted(missing_ids)}"
        )
    return normalized_decisions


class AIClusterMergeClient:
    """Streaming OpenAI-compatible client for one label-level merge decision."""

    def __init__(
        self,
        config: QuestionTypeServiceConfig,
        *,
        base_prompt: str,
        transport: StreamTransport | None = None,
        max_retries: int = 3,
    ):
        if not config.endpoint.strip():
            raise ValueError("cluster merge endpoint must be non-empty")
        if max_retries <= 0:
            raise ValueError("max_retries must be positive")
        self._config = config
        self._base_prompt = base_prompt
        self._transport = transport or _stream_http_transport
        self._max_retries = max_retries

    def merge(
        self,
        *,
        source_type_label: str,
        granularity_guidance: str | None = None,
        base_clusters: Sequence[Mapping[str, Any]],
    ) -> AIClusterMergeResult:
        expected_ids = {
            str(cluster.get("base_cluster_id", "")).strip()
            for cluster in base_clusters
        }
        if "" in expected_ids or len(expected_ids) != len(base_clusters):
            raise ValueError("base_cluster_id values must be non-empty and unique")
        prompt = build_cluster_merge_prompt(
            self._base_prompt,
            source_type_label=source_type_label,
            granularity_guidance=granularity_guidance,
            base_clusters=base_clusters,
        )
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        request_payload = {
            "model": self._config.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
            "stream": True,
        }
        last_error: QuestionTypeServiceError | None = None
        for _ in range(self._max_retries):
            try:
                completion = self._transport(
                    self._config.endpoint,
                    request_payload,
                    self._config.timeout_seconds,
                    headers,
                )
                decisions = parse_cluster_merge_response(
                    completion.content,
                    expected_base_cluster_ids=expected_ids,
                )
                return AIClusterMergeResult(
                    decisions=decisions,
                    raw_response=completion.content,
                    request_id=completion.request_id,
                    model=completion.model or self._config.model,
                )
            except QuestionTypeServiceError as error:
                last_error = error
        raise last_error or QuestionTypeServiceError(
            "cluster merge request failed without an error"
        )


def materialize_ai_clusters(
    *,
    source_type_label: str,
    base_clusters: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
    representative_count: int = 5,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Aggregate base-cluster summaries and return base-to-final membership."""
    by_id = {cluster["base_cluster_id"]: cluster for cluster in base_clusters}
    clusters: list[dict[str, Any]] = []
    base_to_final: dict[str, str] = {}
    for decision in decisions:
        base_ids = sorted(decision["base_cluster_ids"])
        digest = hashlib.sha256(
            (source_type_label + "\0" + "\0".join(base_ids)).encode("utf-8")
        ).hexdigest()[:12]
        local_cluster_id = f"AI-LOCAL-{digest}"
        label_counts: dict[str, int] = {}
        representative_ids: list[str] = []
        member_count = 0
        for base_id in base_ids:
            base = by_id[base_id]
            base_to_final[base_id] = local_cluster_id
            member_count += int(base["member_count"])
            for label, count in base["candidate_label_counts"].items():
                label_counts[label] = label_counts.get(label, 0) + int(count)
            for question_id in base.get("representative_question_ids", []):
                if question_id not in representative_ids:
                    representative_ids.append(question_id)
        clusters.append(
            {
                "local_cluster_id": local_cluster_id,
                "source_type_label": source_type_label,
                "canonical_type_label": decision["canonical_type_label"],
                "canonical_task_mechanism": decision[
                    "canonical_task_mechanism"
                ],
                "decision_status": decision["decision_status"],
                "base_cluster_ids": base_ids,
                "base_cluster_count": len(base_ids),
                "member_count": member_count,
                "candidate_label_counts": dict(sorted(label_counts.items())),
                "representative_question_ids": representative_ids[
                    :representative_count
                ],
            }
        )
    clusters.sort(key=lambda cluster: (-cluster["member_count"], cluster["local_cluster_id"]))
    return clusters, base_to_final
