import unittest

try:
    from english_knowledge_tagger.knowledge_tree_definition_review_analysis import (
        summarize_definition_ablation_reviews,
    )
except ModuleNotFoundError:
    summarize_definition_ablation_reviews = None


COMPARISON_PARENT = "知识点->句法->主谓一致"
INTERROGATIVE_PARENT = "知识点->句法->主从复合句->宾语从句->宾语从句的引导词"
AGREEMENT = COMPARISON_PARENT + "->语法一致"
NEAREST = COMPARISON_PARENT + "->就近/就远原则"
THAT = INTERROGATIVE_PARENT + "->that引导宾语从句"
WHAT = INTERROGATIVE_PARENT + "->what引导宾语从句"


def _mapping(
    review_id: str,
    *,
    a_mode: str,
    a_label: str,
    b_mode: str,
    b_label: str,
) -> dict[str, str]:
    return {
        "review_id": review_id,
        "option_a_mode": a_mode,
        "option_a_label": a_label,
        "option_b_mode": b_mode,
        "option_b_label": b_label,
    }


class KnowledgeTreeDefinitionReviewAnalysisTests(unittest.TestCase):
    def test_uses_per_review_mapping_instead_of_assuming_a_or_b_modes(self):
        self.assertTrue(
            callable(summarize_definition_ablation_reviews),
            "summarize_definition_ablation_reviews must be implemented",
        )
        report = summarize_definition_ablation_reviews(
            (
                _mapping(
                    "r-a",
                    a_mode="compressed",
                    a_label=AGREEMENT,
                    b_mode="none",
                    b_label=NEAREST,
                ),
                _mapping(
                    "r-b",
                    a_mode="none",
                    a_label=WHAT,
                    b_mode="compressed",
                    b_label=THAT,
                ),
                _mapping(
                    "r-both",
                    a_mode="compressed",
                    a_label=AGREEMENT,
                    b_mode="none",
                    b_label=NEAREST,
                ),
                _mapping(
                    "r-neither",
                    a_mode="none",
                    a_label=WHAT,
                    b_mode="compressed",
                    b_label=THAT,
                ),
            ),
            (
                {"review_id": "r-a", "review_decision": "A", "review_evidence": "first"},
                {"review_id": "r-b", "review_decision": "B"},
                {"review_id": "r-both", "review_decision": "both"},
                {"review_id": "r-neither", "review_decision": "neither"},
                {"review_id": "unmapped", "review_decision": "A"},
            ),
        )

        self.assertEqual(report["resolved_reviews"], 4)
        self.assertEqual(report["correct_option_assignments"], 4)
        self.assertEqual(
            report["review_decision_counts"], {"A": 1, "B": 1, "both": 1, "neither": 1}
        )
        self.assertEqual(report["both_reviews"], 1)
        self.assertEqual(report["neither_reviews"], 1)
        self.assertEqual(report["unresolved_mapping_errors"][0]["code"], "missing_mapping")

        by_mode = {row["mode"]: row for row in report["by_mode"]}
        self.assertEqual(by_mode["compressed"]["correct_option_assignments"], 3)
        self.assertEqual(by_mode["compressed"]["both_option_assignments"], 1)
        self.assertEqual(by_mode["none"]["correct_option_assignments"], 1)
        self.assertEqual(by_mode["none"]["both_option_assignments"], 1)

        compressed_labels = {
            row["candidate_label"]: row for row in by_mode["compressed"]["candidate_labels"]
        }
        self.assertEqual(compressed_labels[AGREEMENT]["correct_option_assignments"], 2)
        self.assertEqual(compressed_labels[THAT]["correct_option_assignments"], 1)
        self.assertEqual(
            by_mode["compressed"]["candidate_parents"],
            [
                {
                    "candidate_parent": COMPARISON_PARENT,
                    "both_option_assignments": 1,
                    "correct_option_assignments": 2,
                    "single_option_assignments": 1,
                },
                {
                    "candidate_parent": INTERROGATIVE_PARENT,
                    "both_option_assignments": 0,
                    "correct_option_assignments": 1,
                    "single_option_assignments": 1,
                },
            ],
        )

    def test_reports_invalid_decision_and_ambiguous_mapping_without_guessing(self):
        self.assertTrue(callable(summarize_definition_ablation_reviews))
        report = summarize_definition_ablation_reviews(
            (
                _mapping(
                    "duplicated",
                    a_mode="compressed",
                    a_label=AGREEMENT,
                    b_mode="none",
                    b_label=NEAREST,
                ),
                _mapping(
                    "duplicated",
                    a_mode="none",
                    a_label=WHAT,
                    b_mode="compressed",
                    b_label=THAT,
                ),
            ),
            (
                {"review_id": "duplicated", "review_decision": "A"},
                {"review_id": "bad-decision", "review_decision": "C"},
            ),
        )

        self.assertEqual(report["resolved_reviews"], 0)
        self.assertEqual(report["correct_option_assignments"], 0)
        self.assertEqual(
            {error["code"] for error in report["unresolved_mapping_errors"]},
            {"duplicate_mapping", "ambiguous_mapping", "invalid_review_decision"},
        )


if __name__ == "__main__":
    unittest.main()
