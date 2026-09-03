"""Pairwise AI equivalence decisions and strict local type clustering."""

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


PAIR_PROMPT_VERSION = "question-major-type-pairwise-equivalence-v1"
NAMING_PROMPT_VERSION = "question-major-type-cluster-naming-v1"
PAIR_FIELDS = {
    "same_type",
    "same_primary_operation",
    "same_answer_generation",
    "same_required_support",
    "confidence",
}
NAMING_FIELDS = {
    "local_cluster_id",
    "canonical_type_label",
    "canonical_task_mechanism",
    "decision_status",
}


StreamTransport = Callable[
    [str, dict[str, Any], float, Mapping[str, str]], StreamCompletion
]


@dataclass(frozen=True)
class PairDecisionResult:
    decision: dict[str, Any]
    raw_response: str
    request_id: str | None
    model: str


@dataclass(frozen=True)
class NamingResult:
    decisions: list[dict[str, Any]]
    raw_response: str
    request_id: str | None
    model: str


def _strip_json_fence(text: str) -> str:
    normalized = text.strip()
    if normalized.startswith("```") and normalized.endswith("```"):
        lines = normalized.splitlines()
        if len(lines) >= 3:
            normalized = "\n".join(lines[1:-1]).strip()
    return normalized


def compact_base_cluster(cluster: Mapping[str, Any]) -> dict[str, Any]:
    """Expose semantic evidence only, without old-label or size anchors."""
    counts = cluster.get("candidate_label_counts")
    if not isinstance(counts, Mapping):
        raise ValueError("candidate_label_counts must be an object")
    labels = sorted(
        label.strip()
        for label in counts
        if isinstance(label, str) and label.strip()
    )
    base_id = cluster.get("base_cluster_id")
    mechanism = cluster.get("canonical_task_mechanism")
    if not isinstance(base_id, str) or not base_id.strip():
        raise ValueError("base_cluster_id must be non-empty")
    if not labels:
        raise ValueError(f"base cluster has no candidate labels: {base_id}")
    if not isinstance(mechanism, str) or not mechanism.strip():
        raise ValueError(f"base cluster has no task mechanism: {base_id}")
    return {
        "base_cluster_id": base_id.strip(),
        "candidate_type_labels": labels,
        "task_mechanism": mechanism.strip(),
    }


def build_pair_prompt(
    base_prompt: str,
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> str:
    if not base_prompt.strip():
        raise ValueError("pairwise prompt must be non-empty")
    payload = {
        "cluster_a": compact_base_cluster(left),
        "cluster_b": compact_base_cluster(right),
    }
    return (
        f"{base_prompt.strip()}\n\n"
        "--------------------------------\n"
        "待比较的两个基础簇\n"
        "--------------------------------\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)}"
    )


def parse_pair_response(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(_strip_json_fence(text))
    except json.JSONDecodeError as error:
        raise QuestionTypeServiceError(
            "pairwise response must be one complete JSON object"
        ) from error
    if not isinstance(payload, dict) or set(payload) != PAIR_FIELDS:
        raise QuestionTypeServiceError(
            f"pairwise response fields must be exactly {sorted(PAIR_FIELDS)}"
        )
    for field in PAIR_FIELDS - {"confidence"}:
        if not isinstance(payload[field], bool):
            raise QuestionTypeServiceError(f"{field} must be boolean")
    confidence = payload["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise QuestionTypeServiceError("confidence must be a number")
    if not 0 <= confidence <= 1:
        raise QuestionTypeServiceError("confidence must be between 0 and 1")
    payload["confidence"] = float(confidence)
    return payload


def pair_is_mergeable(decision: Mapping[str, Any], *, min_confidence: float) -> bool:
    return (
        float(decision["confidence"]) >= min_confidence
        and decision["same_type"] is True
        and decision["same_primary_operation"] is True
        and decision["same_answer_generation"] is True
        and decision["same_required_support"] is True
    )


def strict_complete_link_groups(
    base_cluster_ids: Sequence[str],
    pair_decisions: Mapping[tuple[str, str], Mapping[str, Any]],
    *,
    min_confidence: float,
) -> list[list[str]]:
    """Greedily merge only groups whose every cross-pair is mergeable."""
    if not 0 <= min_confidence <= 1:
        raise ValueError("min_confidence must be between 0 and 1")
    ids = sorted(base_cluster_ids)
    if len(ids) != len(set(ids)) or any(not value for value in ids):
        raise ValueError("base cluster IDs must be non-empty and unique")
    expected_pairs = {
        (ids[left], ids[right])
        for left in range(len(ids))
        for right in range(left + 1, len(ids))
    }
    missing = expected_pairs - set(pair_decisions)
    if missing:
        raise ValueError(f"missing {len(missing)} pair decisions")

    groups: list[tuple[str, ...]] = [(base_id,) for base_id in ids]
    while True:
        candidates: list[tuple[float, tuple[str, ...], int, int]] = []
        for left_index in range(len(groups)):
            for right_index in range(left_index + 1, len(groups)):
                cross_pairs = [
                    tuple(sorted((left_id, right_id)))
                    for left_id in groups[left_index]
                    for right_id in groups[right_index]
                ]
                decisions = [pair_decisions[pair] for pair in cross_pairs]
                if all(
                    pair_is_mergeable(decision, min_confidence=min_confidence)
                    for decision in decisions
                ):
                    minimum_confidence = min(
                        float(decision["confidence"]) for decision in decisions
                    )
                    merged = tuple(sorted(groups[left_index] + groups[right_index]))
                    candidates.append(
                        (-minimum_confidence, merged, left_index, right_index)
                    )
        if not candidates:
            break
        _, merged, left_index, right_index = min(candidates)
        groups = [
            group
            for index, group in enumerate(groups)
            if index not in {left_index, right_index}
        ]
        groups.append(merged)
        groups.sort()
    return [list(group) for group in sorted(groups)]


def make_local_cluster_id(base_cluster_ids: Sequence[str]) -> str:
    digest = hashlib.sha256("\0".join(sorted(base_cluster_ids)).encode("utf-8"))
    return f"PAIR-LOCAL-{digest.hexdigest()[:12]}"


def build_naming_prompt(
    base_prompt: str,
    *,
    groups: Sequence[Sequence[str]],
    base_clusters: Sequence[Mapping[str, Any]],
) -> str:
    if not base_prompt.strip():
        raise ValueError("naming prompt must be non-empty")
    by_id = {str(cluster["base_cluster_id"]): cluster for cluster in base_clusters}
    payload = {
        "clusters": [
            {
                "local_cluster_id": make_local_cluster_id(group),
                "base_clusters": [compact_base_cluster(by_id[base_id]) for base_id in group],
            }
            for group in groups
        ]
    }
    return (
        f"{base_prompt.strip()}\n\n"
        "--------------------------------\n"
        "已确定成员的待命名簇\n"
        "--------------------------------\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)}"
    )


def parse_naming_response(
    text: str, *, expected_local_cluster_ids: set[str]
) -> list[dict[str, Any]]:
    try:
        payload = json.loads(_strip_json_fence(text))
    except json.JSONDecodeError as error:
        raise QuestionTypeServiceError(
            "naming response must be one complete JSON object"
        ) from error
    if not isinstance(payload, dict) or set(payload) != {"clusters"}:
        raise QuestionTypeServiceError("naming response must contain only clusters")
    clusters = payload["clusters"]
    if not isinstance(clusters, list) or not clusters:
        raise QuestionTypeServiceError("naming clusters must be a non-empty array")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for item in clusters:
        if not isinstance(item, dict) or set(item) != NAMING_FIELDS:
            raise QuestionTypeServiceError(
                f"naming fields must be exactly {sorted(NAMING_FIELDS)}"
            )
        local_id = item["local_cluster_id"]
        label = item["canonical_type_label"]
        mechanism = item["canonical_task_mechanism"]
        status = item["decision_status"]
        if local_id not in expected_local_cluster_ids or local_id in seen:
            raise QuestionTypeServiceError(f"unexpected or duplicate cluster: {local_id}")
        if not isinstance(label, str) or not label.strip() or "题型@" in label or "\n" in label:
            raise QuestionTypeServiceError("canonical_type_label must be one flat label")
        if not isinstance(mechanism, str) or not mechanism.strip():
            raise QuestionTypeServiceError("canonical_task_mechanism must be non-empty")
        if status not in {"candidate", "unresolved"}:
            raise QuestionTypeServiceError("decision_status is invalid")
        seen.add(local_id)
        normalized.append(
            {
                "local_cluster_id": local_id,
                "canonical_type_label": label.strip(),
                "canonical_task_mechanism": mechanism.strip(),
                "decision_status": status,
            }
        )
    missing = expected_local_cluster_ids - seen
    if missing:
        raise QuestionTypeServiceError(f"naming response omitted clusters: {sorted(missing)}")
    return sorted(normalized, key=lambda item: item["local_cluster_id"])


class PairwiseTypeClient:
    """Streaming client for pair decisions and post-clustering names."""

    def __init__(
        self,
        config: QuestionTypeServiceConfig,
        *,
        pair_prompt: str,
        naming_prompt: str,
        transport: StreamTransport | None = None,
        max_retries: int = 3,
    ):
        if not config.endpoint.strip():
            raise ValueError("endpoint must be non-empty")
        if max_retries <= 0:
            raise ValueError("max_retries must be positive")
        self._config = config
        self._pair_prompt = pair_prompt
        self._naming_prompt = naming_prompt
        self._transport = transport or _stream_http_transport
        self._max_retries = max_retries

    def _complete_once(self, prompt: str) -> StreamCompletion:
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        payload = {
            "model": self._config.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
            "stream": True,
        }
        return self._transport(
            self._config.endpoint,
            payload,
            self._config.timeout_seconds,
            headers,
        )

    def compare(
        self, left: Mapping[str, Any], right: Mapping[str, Any]
    ) -> PairDecisionResult:
        prompt = build_pair_prompt(self._pair_prompt, left, right)
        last_error: QuestionTypeServiceError | None = None
        for _ in range(self._max_retries):
            try:
                completion = self._complete_once(prompt)
                return PairDecisionResult(
                    decision=parse_pair_response(completion.content),
                    raw_response=completion.content,
                    request_id=completion.request_id,
                    model=completion.model or self._config.model,
                )
            except QuestionTypeServiceError as error:
                last_error = error
        raise last_error or QuestionTypeServiceError("pair request failed without an error")

    def name(
        self,
        *,
        groups: Sequence[Sequence[str]],
        base_clusters: Sequence[Mapping[str, Any]],
    ) -> NamingResult:
        expected_ids = {make_local_cluster_id(group) for group in groups}
        prompt = build_naming_prompt(
            self._naming_prompt,
            groups=groups,
            base_clusters=base_clusters,
        )
        last_error: QuestionTypeServiceError | None = None
        for _ in range(self._max_retries):
            try:
                completion = self._complete_once(prompt)
                return NamingResult(
                    decisions=parse_naming_response(
                        completion.content,
                        expected_local_cluster_ids=expected_ids,
                    ),
                    raw_response=completion.content,
                    request_id=completion.request_id,
                    model=completion.model or self._config.model,
                )
            except QuestionTypeServiceError as error:
                last_error = error
        raise last_error or QuestionTypeServiceError("naming request failed without an error")
