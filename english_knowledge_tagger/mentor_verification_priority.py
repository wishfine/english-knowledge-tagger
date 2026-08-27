"""Rank mentor verifier labels by statistically conservative expected yield.

The resulting status is intentionally about *which label to process first*.
It is not a claim that the verifier, historical label, or source sample is
accurate.  Human calibration remains a separate mandatory gate.
"""

from __future__ import annotations

from math import sqrt
from typing import Mapping


ONE_SIDED_95_Z = 1.6448536269514722


def wilson_lower_one_sided_95(successes: int, total: int) -> float:
    """Return the one-sided 95% Wilson lower bound for a binomial proportion."""
    if not isinstance(successes, int) or isinstance(successes, bool):
        raise ValueError("successes must be an integer")
    if not isinstance(total, int) or isinstance(total, bool) or total <= 0:
        raise ValueError("total must be a positive integer")
    if successes < 0 or successes > total:
        raise ValueError("successes must be between 0 and total")
    proportion = successes / total
    z_squared = ONE_SIDED_95_Z * ONE_SIDED_95_Z
    return (
        proportion
        + z_squared / (2 * total)
        - ONE_SIDED_95_Z
        * sqrt(proportion * (1 - proportion) / total + z_squared / (4 * total * total))
    ) / (1 + z_squared / total)


def _categories(summary: object) -> list[Mapping[str, object]]:
    if isinstance(summary, list) and all(isinstance(item, Mapping) for item in summary):
        return list(summary)
    if isinstance(summary, Mapping):
        categories = summary.get("categories")
        if isinstance(categories, list) and all(isinstance(item, Mapping) for item in categories):
            return list(categories)
    raise ValueError("mentor verification summary must be a category list or object with categories list")


def _nonnegative_int(value: object, *, field: str, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"mentor summary {label}: {field} must be a non-negative integer")
    return value


def assess_mentor_verification_summary(
    summary: object,
    *,
    target_lcb: float = 0.70,
    minimum_true_records: int = 12,
) -> tuple[dict[str, object], ...]:
    """Classify labels by conservative match-true yield, not label accuracy."""
    if not 0 < target_lcb < 1:
        raise ValueError("target_lcb must be between 0 and 1")
    if not isinstance(minimum_true_records, int) or minimum_true_records <= 0:
        raise ValueError("minimum_true_records must be a positive integer")
    rows: list[dict[str, object]] = []
    seen_labels: set[str] = set()
    for category_row in _categories(summary):
        category = category_row.get("category")
        label_stats = category_row.get("label_stats")
        if not isinstance(category, str) or not category.strip() or not isinstance(label_stats, Mapping):
            raise ValueError("mentor summary categories require category and label_stats")
        for label, raw_stats in label_stats.items():
            if not isinstance(label, str) or not label.strip() or not isinstance(raw_stats, Mapping):
                raise ValueError("mentor summary label_stats must map non-empty labels to objects")
            if label in seen_labels:
                raise ValueError(f"mentor summary contains duplicate label: {label}")
            seen_labels.add(label)
            total = _nonnegative_int(raw_stats.get("total"), field="total", label=label)
            match = _nonnegative_int(raw_stats.get("match"), field="match", label=label)
            mismatch = _nonnegative_int(raw_stats.get("mismatch"), field="mismatch", label=label)
            error = _nonnegative_int(raw_stats.get("error"), field="error", label=label)
            if total <= 0 or match + mismatch + error != total:
                raise ValueError(f"mentor summary {label}: total must equal match + mismatch + error")
            lower_bound = wilson_lower_one_sided_95(match, total)
            if error:
                status = "hold_service_errors"
            elif match < minimum_true_records:
                status = "hold_too_few_true"
            elif lower_bound < target_lcb:
                status = "hold_yield_below_threshold"
            else:
                status = "rollout_candidate"
            rows.append(
                {
                    "category": category.strip(),
                    "verify_label": label.strip(),
                    "sample_total": total,
                    "match_true": match,
                    "match_false": mismatch,
                    "service_error": error,
                    "match_rate": match / total,
                    "wilson_lower_95": lower_bound,
                    "target_wilson_lower_95": target_lcb,
                    "minimum_true_records": minimum_true_records,
                    "status": status,
                    "interpretation": "yield_only_not_label_accuracy",
                }
            )
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                row["status"] != "rollout_candidate",
                -float(row["wilson_lower_95"]),
                str(row["verify_label"]),
            ),
        )
    )
