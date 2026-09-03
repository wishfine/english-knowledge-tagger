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
    if row.get("information_sufficiency") == "sufficient" and confidence >= core_threshold:
        return "core", None
    if confidence >= auxiliary_threshold:
        return "auxiliary", None
    return "excluded", "confidence_below_auxiliary_threshold"


def _stable_cluster_id(
    source_type_label: str, question_keys: Sequence[str], *, prefix: str = "LOCAL"
) -> str:
    payload = source_type_label + "\0" + "\0".join(sorted(question_keys))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _unit_vector(vector: Any, np: Any) -> Any:
    """Normalize one dense feature block before applying its configured weight."""
    norm = np.linalg.norm(vector)
    return vector / norm if norm else vector


def cluster_local_results(
    rows: Sequence[Mapping[str, Any]],
    *,
    source_type_label: str,
    core_confidence_threshold: float = 0.7,
    auxiliary_confidence_threshold: float = 0.4,
    local_distance_threshold: float = 0.48,
    merge_distance_threshold: float = 0.48,
    auxiliary_similarity_threshold: float = 0.52,
    candidate_label_weight: float = 0.7,
    task_mechanism_weight: float = 0.3,
    merge_candidate_label_weight: float = 0.2,
    merge_task_mechanism_weight: float = 0.8,
    representative_count: int = 5,
) -> dict[str, Any]:
    """Build V1-compatible base clusters, then merge whole base clusters only."""
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
    if not 0 < merge_distance_threshold < 1:
        raise ValueError("merge_distance_threshold must be between 0 and 1")
    if not 0 <= auxiliary_similarity_threshold <= 1:
        raise ValueError("auxiliary_similarity_threshold must be between 0 and 1")
    if candidate_label_weight <= 0 or task_mechanism_weight <= 0:
        raise ValueError("base text feature weights must be positive")
    if merge_candidate_label_weight <= 0 or merge_task_mechanism_weight <= 0:
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
            "base_clusters": [],
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
                "base_cluster_count": 0,
                "split_base_cluster_count": 0,
                "multi_base_final_cluster_count": 0,
                "candidate_label_group_count": len(
                    {item["normalized_label"] for item in prepared}
                ),
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
    label_matrix = label_vectorizer.fit_transform(labels)
    mechanism_matrix = mechanism_vectorizer.fit_transform(mechanisms)
    base_features = normalize(
        hstack(
            [
                label_matrix * candidate_label_weight,
                mechanism_matrix * task_mechanism_weight,
            ],
            format="csr",
        )
    )
    merge_features = normalize(
        hstack(
            [
                label_matrix * merge_candidate_label_weight,
                mechanism_matrix * merge_task_mechanism_weight,
            ],
            format="csr",
        )
    )

    # Stage 1: reproduce the original V1 item-level clustering.
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
        core_cluster_labels = model.fit_predict(base_features[core_indices].toarray())

    base_grouped_indices: dict[int, list[int]] = defaultdict(list)
    for prepared_index, cluster_label in zip(core_indices, core_cluster_labels):
        base_grouped_indices[int(cluster_label)].append(prepared_index)

    base_centroids: dict[int, Any] = {}
    for cluster_label, indices in base_grouped_indices.items():
        centroid = np.asarray(base_features[indices].mean(axis=0)).ravel()
        base_centroids[cluster_label] = _unit_vector(centroid, np)

    auxiliary_indices = [index for index, item in enumerate(prepared) if item["quality_tier"] == "auxiliary"]
    for index in auxiliary_indices:
        vector = base_features[index]
        similarities = {
            cluster_label: float(vector.dot(centroid).item())
            for cluster_label, centroid in base_centroids.items()
        }
        best_cluster, best_similarity = max(similarities.items(), key=lambda item: item[1])
        if best_similarity >= auxiliary_similarity_threshold:
            base_grouped_indices[best_cluster].append(index)
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

    ordered_base_groups = sorted(
        base_grouped_indices.values(),
        key=lambda indices: (
            -len(indices),
            min(prepared[index]["question_key"] for index in indices),
        ),
    )
    base_clusters: list[dict[str, Any]] = []
    base_cluster_ids: list[str] = []
    base_group_features = []
    for indices in ordered_base_groups:
        question_keys = [prepared[index]["question_key"] for index in indices]
        base_cluster_id = _stable_cluster_id(
            source_type_label, question_keys, prefix="BASE"
        )
        base_cluster_ids.append(base_cluster_id)
        label_centroid = _unit_vector(
            np.asarray(label_matrix[indices].mean(axis=0)).ravel(), np
        )
        mechanism_centroid = _unit_vector(
            np.asarray(mechanism_matrix[indices].mean(axis=0)).ravel(), np
        )
        base_group_features.append(
            _unit_vector(
                np.concatenate(
                    [
                        label_centroid * merge_candidate_label_weight,
                        mechanism_centroid * merge_task_mechanism_weight,
                    ]
                ),
                np,
            )
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
        centroid = _unit_vector(
            np.asarray(base_features[indices].mean(axis=0)).ravel(), np
        )
        ranked_indices = sorted(
            indices,
            key=lambda index: (
                -float(base_features[index].dot(centroid).item()),
                prepared[index]["question_key"],
            ),
        )
        medoid = prepared[ranked_indices[0]]
        base_clusters.append(
            {
                "base_cluster_id": base_cluster_id,
                "source_type_label": source_type_label,
                "local_candidate_type_label": local_candidate_type_label,
                "candidate_label_counts": dict(
                    sorted(raw_label_counts.items(), key=lambda item: (-item[1], item[0]))
                ),
                "canonical_task_mechanism": medoid["mechanism"],
                "member_count": len(indices),
                "representative_question_ids": [
                    prepared[index]["row"].get("question_id")
                    for index in ranked_indices[:representative_count]
                ],
            }
        )

    # Stage 2: cluster V1 base-cluster vectors and only merge whole base clusters.
    base_group_features = np.asarray(base_group_features)
    if len(ordered_base_groups) == 1:
        merge_cluster_labels = np.array([0])
    else:
        merge_model = AgglomerativeClustering(
            n_clusters=None,
            metric="cosine",
            linkage="average",
            distance_threshold=merge_distance_threshold,
            compute_full_tree=True,
        )
        merge_cluster_labels = merge_model.fit_predict(base_group_features)

    merged_base_positions: dict[int, list[int]] = defaultdict(list)
    for base_position, cluster_label in enumerate(merge_cluster_labels):
        merged_base_positions[int(cluster_label)].append(base_position)

    clusters: list[dict[str, Any]] = []
    members: list[dict[str, Any]] = []
    ordered_merged_groups = sorted(
        merged_base_positions.values(),
        key=lambda positions: (
            -sum(len(ordered_base_groups[position]) for position in positions),
            min(
                prepared[index]["question_key"]
                for position in positions
                for index in ordered_base_groups[position]
            ),
        ),
    )
    for base_positions in ordered_merged_groups:
        indices = [
            index
            for position in base_positions
            for index in ordered_base_groups[position]
        ]
        source_base_cluster_ids = sorted(
            base_cluster_ids[position] for position in base_positions
        )
        question_keys = [prepared[index]["question_key"] for index in indices]
        cluster_id = _stable_cluster_id(source_type_label, question_keys)
        centroid = _unit_vector(
            np.asarray(merge_features[indices].mean(axis=0)).ravel(), np
        )
        similarities = {
            index: float(merge_features[index].dot(centroid).item()) for index in indices
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
                "base_cluster_ids": source_base_cluster_ids,
                "base_cluster_count": len(source_base_cluster_ids),
                "candidate_label_counts": dict(
                    sorted(raw_label_counts.items(), key=lambda item: (-item[1], item[0]))
                ),
                "candidate_label_group_count": len(normalized_label_counts),
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
        base_id_by_index = {
            index: base_cluster_ids[position]
            for position in base_positions
            for index in ordered_base_groups[position]
        }
        for index in indices:
            item = prepared[index]
            members.append(
                {
                    "question_id": item["row"].get("question_id"),
                    "source_line": item["row"].get("source_line"),
                    "local_cluster_id": cluster_id,
                    "base_cluster_id": base_id_by_index[index],
                    "candidate_label_group": item["normalized_label"],
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
        "base_clusters": base_clusters,
        "clusters": clusters,
        "members": members,
        "outliers": outliers,
        "report": {
            "source_type_label": source_type_label,
            "total_rows": len(rows),
            "core_rows": len(core_indices),
            "auxiliary_rows": len(auxiliary_indices),
            "base_cluster_count": len(base_clusters),
            "cluster_count": len(clusters),
            "split_base_cluster_count": 0,
            "multi_base_final_cluster_count": sum(
                cluster["base_cluster_count"] > 1 for cluster in clusters
            ),
            "stable_cluster_count": cluster_status_counts["stable"],
            "micro_cluster_count": cluster_status_counts["micro"],
            "unresolved_cluster_count": cluster_status_counts["unresolved"],
            "unresolved_row_count": unresolved_row_count,
            "clustered_rows": len(members),
            "outlier_rows": len(outliers),
            "cluster_size_distribution": [cluster["member_count"] for cluster in clusters],
            "candidate_label_group_count": len(
                {item["normalized_label"] for item in prepared}
            ),
            "parameters": {
                "core_confidence_threshold": core_confidence_threshold,
                "auxiliary_confidence_threshold": auxiliary_confidence_threshold,
                "local_distance_threshold": local_distance_threshold,
                "merge_distance_threshold": merge_distance_threshold,
                "auxiliary_similarity_threshold": auxiliary_similarity_threshold,
                "candidate_label_weight": candidate_label_weight,
                "task_mechanism_weight": task_mechanism_weight,
                "merge_candidate_label_weight": merge_candidate_label_weight,
                "merge_task_mechanism_weight": merge_task_mechanism_weight,
                "representative_count": representative_count,
                "vectorizer": "character-tfidf",
                "clustering_unit": "stage1-question;stage2-base-cluster",
                "base_cluster_constraint": "merge-only-never-split",
                "group_feature_block_normalization": "l2-before-weighting",
                "clustering": "two-stage-agglomerative-cosine-average",
            },
        },
    }
