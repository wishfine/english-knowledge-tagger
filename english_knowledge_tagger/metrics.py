"""Metrics for controlled multi-label knowledge-point predictions."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence


def _safe_divide(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def multilabel_metrics(
    gold: Sequence[Iterable[str]], predicted: Sequence[Iterable[str]]
) -> dict[str, float | int]:
    """Return exact-match and micro/macro metrics for aligned label collections."""
    if len(gold) != len(predicted):
        raise ValueError("gold and predicted collections must have equal length")
    if not gold:
        raise ValueError("at least one aligned example is required for metrics")

    micro_true_positive = micro_false_positive = micro_false_negative = 0
    per_label: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    exact_matches = 0
    for gold_labels, predicted_labels in zip(gold, predicted, strict=True):
        gold_set = set(gold_labels)
        predicted_set = set(predicted_labels)
        exact_matches += gold_set == predicted_set
        for label in gold_set & predicted_set:
            per_label[label]["tp"] += 1
            micro_true_positive += 1
        for label in predicted_set - gold_set:
            per_label[label]["fp"] += 1
            micro_false_positive += 1
        for label in gold_set - predicted_set:
            per_label[label]["fn"] += 1
            micro_false_negative += 1

    micro_precision = _safe_divide(micro_true_positive, micro_true_positive + micro_false_positive)
    micro_recall = _safe_divide(micro_true_positive, micro_true_positive + micro_false_negative)
    label_scores = []
    for counts in per_label.values():
        precision = _safe_divide(counts["tp"], counts["tp"] + counts["fp"])
        recall = _safe_divide(counts["tp"], counts["tp"] + counts["fn"])
        label_scores.append((precision, recall, _f1(precision, recall)))

    return {
        "support": len(gold),
        "label_count": len(per_label),
        "example_exact_match": exact_matches / len(gold),
        "micro_precision": micro_precision,
        "micro_recall": micro_recall,
        "micro_f1": _f1(micro_precision, micro_recall),
        "macro_precision": sum(score[0] for score in label_scores) / len(label_scores),
        "macro_recall": sum(score[1] for score in label_scores) / len(label_scores),
        "macro_f1": sum(score[2] for score in label_scores) / len(label_scores),
    }
