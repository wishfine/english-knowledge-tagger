import unittest

try:
    from english_knowledge_tagger.knowledge_effective_pool_ablation_analysis import (
        summarize_effective_pool_ablation,
    )
except ModuleNotFoundError:
    summarize_effective_pool_ablation = None


OLD_LABEL = "知识点->词法->被动语态->一般过去时的被动语态"
NEW_LABEL = "知识点->词法->被动语态->过去进行时的被动语态"


def row(review_id: str, *, verdict: str, best_label: str | None) -> dict[str, object]:
    return {
        "review_id": review_id,
        "status": "candidate",
        "validation": {
            "verdict": verdict,
            "candidate_coverage": "covered",
            "best_label": best_label,
        },
    }


class KnowledgeEffectivePoolAblationAnalysisTests(unittest.TestCase):
    def test_summary_distinguishes_stable_new_label_selection_from_accuracy(self):
        self.assertTrue(
            callable(summarize_effective_pool_ablation),
            "summarize_effective_pool_ablation must be implemented",
        )
        baseline = tuple(
            (f"v01-{index}", (row("r-new", verdict="keep", best_label=OLD_LABEL),))
            for index in (1, 2, 3)
        )
        candidate = tuple(
            (f"v02-{index}", (row("r-new", verdict="replace", best_label=NEW_LABEL),))
            for index in (1, 2, 3)
        )

        report = summarize_effective_pool_ablation(
            baseline,
            candidate,
            new_labels_by_review_id={"r-new": (NEW_LABEL,)},
        )

        self.assertEqual(report["baseline"]["all_three_decision_agreement"], 1.0)
        self.assertEqual(report["candidate"]["all_three_decision_agreement"], 1.0)
        self.assertEqual(report["comparison"]["unanimous_decision_disagreements"], 1)
        self.assertEqual(report["comparison"]["candidate_consistently_selects_new_label"], 1)
        self.assertEqual(
            report["comparison"]["candidate_consistently_selects_new_label_review_ids"],
            ["r-new"],
        )
        self.assertEqual(report["review_rows"][0]["correctness_status"], "requires_human_review")


if __name__ == "__main__":
    unittest.main()
