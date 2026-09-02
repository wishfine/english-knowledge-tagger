"""Local, no-LLM clustering for major-question type discovery results."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import re
import unicodedata
from typing import Any, Mapping, Sequence


_WHITESPACE = re.compile(r"\s+")
_WRAPPED_WRITING_LABEL = re.compile(
    r"^(?:英语)?(?:书面表达|应用文写作)[（(]([^）)]+)[）)]$"
)


class LocalTypeClusteringError(RuntimeError):
    """Raised when local clustering input or dependencies are invalid."""


def normalize_candidate_label(label: str) -> str:
    """Apply conservative surface normalization without inventing a new type."""
    normalized = unicodedata.normalize("NFKC", label).strip()
    normalized = _WHITESPACE.sub("", normalized)
    if normalized.startswith("英语") and len(normalized) > 4:
        normalized = normalized.removeprefix("英语")
    wrapped = _WRAPPED_WRITING_LABEL.fullmatch(normalized)
    if wrapped:
        inner = wrapped.group(1)
        if inner in {"邮件", "电子邮件"}:
            return "电子邮件写作"
        return inner if inner.endswith("写作") else f"{inner}写作"
    if normalized == "邮件写作":
        normalized = "电子邮件写作"
    normalized = normalized.replace("作文", "写作")
    return normalized


def safe_label_directory_name(source_type_label: str) -> str:
    """Keep the original label readable while escaping the path separator."""
    if not source_type_label or "\0" in source_type_label:
        raise ValueError("source type label must be a non-empty filesystem-safe string")
    return source_type_label.replace("/", "／")


def _question_key(row: Mapping[str, Any]) -> str:
    return f"{row.get('question_id')}:{row.get('source_line')}"


def _quality_tier(
    row: Mapping[str, Any], *, core_threshold: float, auxiliary_threshold: float
) -> tuple[str, str | None]:
    if row.get("status") != "candidate":
        return "excluded", "status_error"
    if row.get("information_sufficiency") == "insufficient":
        return "excluded", "information_insufficient"
    label = row.get("candidate_type_label")
    mechanism = row.get("task_mechanism")
    if not isinstance(label, str) or not label.strip():
        return "excluded", "missing_candidate_type_label"
    if label.strip() == "无法判断题型":
        return "excluded", "unable_to_determine_type"
    if not isinstance(mechanism, str) or not mechanism.strip():
        return "excluded", "missing_task_mechanism"
    confidence = row.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return "excluded", "invalid_confidence"
    if (
        row.get("information_sufficiency") in {"sufficient", "partial"}
        and confidence >= core_threshold
    ):
        return "core", None
    if confidence >= auxiliary_threshold:
        return "auxiliary", None
    return "excluded", "confidence_below_auxiliary_threshold"


def _stable_cluster_id(source_type_label: str, question_keys: Sequence[str]) -> str:
    payload = source_type_label + "\0" + "\0".join(sorted(question_keys))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"LOCAL-{digest}"


def cluster_local_results(
    rows: Sequence[Mapping[str, Any]],
    *,
    source_type_label: str,
    core_confidence_threshold: float = 0.7,
    auxiliary_confidence_threshold: float = 0.4,
    local_distance_threshold: float = 0.48,
    auxiliary_similarity_threshold: float = 0.52,
    candidate_label_weight: float = 0.3,
    task_mechanism_weight: float = 0.7,
    representative_count: int = 5,
) -> dict[str, Any]:
    """Cluster one source label using existing candidate labels and mechanisms only."""
    try:
        import numpy as np
        from scipy.sparse import hstack
        from sklearn.cluster import AgglomerativeClustering
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.preprocessing import normalize
    except ImportError as error:
        raise LocalTypeClusteringError(
            "local clustering requires requirements-clustering.txt"
        ) from error

    if not rows:
        raise ValueError("local clustering requires at least one result row")
    if not 0 < local_distance_threshold < 1:
        raise ValueError("local_distance_threshold must be between 0 and 1")
    if not 0 <= auxiliary_similarity_threshold <= 1:
        raise ValueError("auxiliary_similarity_threshold must be between 0 and 1")
    if candidate_label_weight <= 0 or task_mechanism_weight <= 0:
        raise ValueError("text feature weights must be positive")
    if representative_count <= 0:
        raise ValueError("representative_count must be positive")

    prepared: list[dict[str, Any]] = []
    outliers: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for row in rows:
        question_key = _question_key(row)
        if question_key in seen_keys:
            raise ValueError(f"duplicate question in local result: {question_key}")
        seen_keys.add(question_key)
        tier, reason = _quality_tier(
            row,
            core_threshold=core_confidence_threshold,
            auxiliary_threshold=auxiliary_confidence_threshold,
        )
        if tier == "excluded":
            outliers.append({**row, "question_key": question_key, "outlier_reason": reason})
            continue
        prepared.append(
            {
                "row": row,
                "question_key": question_key,
                "quality_tier": tier,
                "normalized_label": normalize_candidate_label(row["candidate_type_label"]),
                "mechanism": _WHITESPACE.sub(" ", row["task_mechanism"]).strip(),
            }
        )

    core_indices = [index for index, item in enumerate(prepared) if item["quality_tier"] == "core"]
    if not core_indices:
        return {
            "clusters": [],
            "members": [],
            "outliers": [
                *outliers,
                *[
                    {
                        **item["row"],
                        "question_key": item["question_key"],
                        "outlier_reason": "no_core_cluster_available",
                    }
                    for item in prepared
                ],
            ],
            "report": {
                "source_type_label": source_type_label,
                "total_rows": len(rows),
                "core_rows": 0,
                "auxiliary_rows": len(prepared),
                "cluster_count": 0,
                "stable_cluster_count": 0,
                "micro_cluster_count": 0,
                "unresolved_cluster_count": 0,
                "unresolved_row_count": 0,
                "clustered_rows": 0,
                "outlier_rows": len(rows),
            },
        }

    labels = [item["normalized_label"] for item in prepared]
    mechanisms = [item["mechanism"] for item in prepared]
    label_vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(1, 4), sublinear_tf=True)
    mechanism_vectorizer = TfidfVectorizer(
        analyzer="char", ngram_range=(2, 4), sublinear_tf=True
    )
    label_matrix = label_vectorizer.fit_transform(labels) * candidate_label_weight
    mechanism_matrix = mechanism_vectorizer.fit_transform(mechanisms) * task_mechanism_weight
    features = normalize(hstack([label_matrix, mechanism_matrix], format="csr"))
    core_features = features[core_indices]

    if len(core_indices) == 1:
        core_cluster_labels = np.array([0])
    else:
        model = AgglomerativeClustering(
            n_clusters=None,
            metric="cosine",
            linkage="average",
            distance_threshold=local_distance_threshold,
            compute_full_tree=True,
        )
        core_cluster_labels = model.fit_predict(core_features.toarray())

    grouped_indices: dict[int, list[int]] = defaultdict(list)
    for prepared_index, cluster_label in zip(core_indices, core_cluster_labels):
        grouped_indices[int(cluster_label)].append(prepared_index)

    cluster_centroids: dict[int, Any] = {}
    for cluster_label, indices in grouped_indices.items():
        centroid = np.asarray(features[indices].mean(axis=0)).ravel()
        norm = np.linalg.norm(centroid)
        cluster_centroids[cluster_label] = centroid / norm if norm else centroid

    auxiliary_indices = [
        index for index, item in enumerate(prepared) if item["quality_tier"] == "auxiliary"
    ]
    auxiliary_similarity: dict[int, float] = {}
    for index in auxiliary_indices:
        vector = features[index]
        similarities = {
            cluster_label: float(vector.dot(centroid).item())
            for cluster_label, centroid in cluster_centroids.items()
        }
        best_cluster, best_similarity = max(similarities.items(), key=lambda item: item[1])
        if best_similarity >= auxiliary_similarity_threshold:
            grouped_indices[best_cluster].append(index)
            auxiliary_similarity[index] = best_similarity
        else:
            item = prepared[index]
            outliers.append(
                {
                    **item["row"],
                    "question_key": item["question_key"],
                    "outlier_reason": "auxiliary_similarity_below_threshold",
                    "nearest_cluster_similarity": best_similarity,
                }
            )

    clusters: list[dict[str, Any]] = []
    members: list[dict[str, Any]] = []
    ordered_groups = sorted(
        grouped_indices.values(),
        key=lambda indices: (-len(indices), min(prepared[index]["question_key"] for index in indices)),
    )
    for indices in ordered_groups:
        question_keys = [prepared[index]["question_key"] for index in indices]
        cluster_id = _stable_cluster_id(source_type_label, question_keys)
        centroid = np.asarray(features[indices].mean(axis=0)).ravel()
        centroid_norm = np.linalg.norm(centroid)
        if centroid_norm:
            centroid = centroid / centroid_norm
        similarities = {
            index: float(features[index].dot(centroid).item()) for index in indices
        }
        ranked_indices = sorted(
            indices,
            key=lambda index: (-similarities[index], prepared[index]["question_key"]),
        )
        raw_label_counts = Counter(
            prepared[index]["row"]["candidate_type_label"] for index in indices
        )
        normalized_label_counts = Counter(
            prepared[index]["normalized_label"] for index in indices
        )
        local_candidate_type_label = sorted(
            normalized_label_counts.items(), key=lambda item: (-item[1], item[0])
        )[0][0]
        medoid = prepared[ranked_indices[0]]
        member_count = len(indices)
        if member_count >= 5:
            cluster_status = "stable"
        elif member_count >= 2:
            cluster_status = "micro"
        else:
            cluster_status = "unresolved"
        clusters.append(
            {
                "local_cluster_id": cluster_id,
                "source_type_label": source_type_label,
                "local_candidate_type_label": local_candidate_type_label,
                "cluster_status": cluster_status,
                "candidate_label_counts": dict(
                    sorted(raw_label_counts.items(), key=lambda item: (-item[1], item[0]))
                ),
                "canonical_task_mechanism": medoid["mechanism"],
                "mechanism_signature": {
                    "candidate_type_label": local_candidate_type_label,
                    "task_mechanism": medoid["mechanism"],
                },
                "member_count": member_count,
                "representative_question_ids": [
                    prepared[index]["row"].get("question_id")
                    for index in ranked_indices[:representative_count]
                ],
            }
        )
        for index in indices:
            item = prepared[index]
            members.append(
                {
                    "question_id": item["row"].get("question_id"),
                    "source_line": item["row"].get("source_line"),
                    "local_cluster_id": cluster_id,
                    "quality_tier": item["quality_tier"],
                    "similarity_to_centroid": round(similarities[index], 6),
                }
            )

    members.sort(key=lambda row: (row["local_cluster_id"], str(row["question_id"])))
    clusters.sort(key=lambda row: (-row["member_count"], row["local_cluster_id"]))
    cluster_status_counts = Counter(cluster["cluster_status"] for cluster in clusters)
    unresolved_row_count = sum(
        cluster["member_count"]
        for cluster in clusters
        if cluster["cluster_status"] == "unresolved"
    )
    return {
        "clusters": clusters,
        "members": members,
        "outliers": outliers,
        "report": {
            "source_type_label": source_type_label,
            "total_rows": len(rows),
            "core_rows": len(core_indices),
            "auxiliary_rows": len(auxiliary_indices),
            "cluster_count": len(clusters),
            "stable_cluster_count": cluster_status_counts["stable"],
            "micro_cluster_count": cluster_status_counts["micro"],
            "unresolved_cluster_count": cluster_status_counts["unresolved"],
            "unresolved_row_count": unresolved_row_count,
            "clustered_rows": len(members),
            "outlier_rows": len(outliers),
            "cluster_size_distribution": [cluster["member_count"] for cluster in clusters],
            "parameters": {
                "core_confidence_threshold": core_confidence_threshold,
                "auxiliary_confidence_threshold": auxiliary_confidence_threshold,
                "local_distance_threshold": local_distance_threshold,
                "auxiliary_similarity_threshold": auxiliary_similarity_threshold,
                "candidate_label_weight": candidate_label_weight,
                "task_mechanism_weight": task_mechanism_weight,
                "representative_count": representative_count,
                "vectorizer": "character-tfidf",
                "clustering": "agglomerative-cosine-average",
            },
        },
    }
