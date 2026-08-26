import unittest

try:
    from english_knowledge_tagger.knowledge_candidate_budget_coverage import (
        analyze_candidate_budget_coverage,
    )
except ModuleNotFoundError as error:
    analyze_candidate_budget_coverage = None
    IMPORT_ERROR = str(error)
else:
    IMPORT_ERROR = ""


HISTORICAL = "知识点->词法->介词->其他介词"
SIBLING = "知识点->词法->介词->时间介词"
RETRIEVED = "知识点->句法->句子成分->状语"
ABSENT = "知识点->词法->冠词->定冠词"


def packet_row(*, alternatives: list[dict[str, str]]) -> dict[str, object]:
    return {
        "review_id": "kp-validation:q-1:other-preposition",
        "source_line": 18,
        "question_id": "q-1",
        "parent_id": "p-1",
        "canonical_label": HISTORICAL,
        "legacy_label": "知识点@词法@介词@其他介词",
        "target_definition": "旧标签释义",
        "alternative_labels": alternatives,
    }


def gold_row() -> dict[str, object]:
    return {
        "review_id": "kp-validation:q-1:other-preposition",
        "source_line": 18,
        "question_id": "q-1",
        "parent_id": "p-1",
        "historical_label": HISTORICAL,
        "gold_labels": [HISTORICAL, SIBLING, RETRIEVED, ABSENT],
        "adjudication_status": "approved",
    }


class KnowledgeCandidateBudgetCoverageTests(unittest.TestCase):
    def test_compares_candidate_coverage_for_multilabel_gold_correction(self):
        self.assertTrue(
            callable(analyze_candidate_budget_coverage),
            f"analyze_candidate_budget_coverage must be implemented: {IMPORT_ERROR}",
        )
        packet_sets = {
            "k4": (
                packet_row(
                    alternatives=[
                        {"label": SIBLING, "source": "sibling", "definition": "时间介词"},
                    ]
                ),
            ),
            "k12": (
                packet_row(
                    alternatives=[
                        {"label": SIBLING, "source": "sibling", "definition": "时间介词"},
                        {"label": RETRIEVED, "source": "type_retrieval", "definition": "句子成分"},
                    ]
                ),
            ),
        }

        report = analyze_candidate_budget_coverage(packet_sets, (gold_row(),))

        self.assertEqual(report["approved_gold_records"], 1)
        self.assertEqual(report["matched_packet_rows"], 1)
        self.assertEqual(report["primary_correction_packet_rows"], 1)
        self.assertEqual(report["primary_correction_label_instances"], 3)
        self.assertEqual(
            report["packets"]["k4"]["all_gold_label_coverage"]["counts"],
            {
                "historical_target": 1,
                "sibling": 1,
                "type_retrieval": 0,
                "other_candidate": 0,
                "absent": 2,
            },
        )
        self.assertEqual(
            report["packets"]["k12"]["primary_correction_label_coverage"]["counts"],
            {
                "historical_target": 0,
                "sibling": 1,
                "type_retrieval": 1,
                "other_candidate": 0,
                "absent": 1,
            },
        )
        self.assertEqual(report["packets"]["k4"]["candidate_count"]["mean"], 1.0)
        self.assertEqual(report["packets"]["k12"]["candidate_count"]["mean"], 2.0)
        self.assertEqual(
            report["packets"]["k12"]["prompt_definition_chars"]["mean"],
            len("旧标签释义时间介词句子成分"),
        )
        self.assertEqual(
            report["by_historical_target_parent"]["知识点->词法->介词"]["packets"]["k12"]
            ["primary_correction_label_instances"],
            3,
        )
        self.assertEqual(
            report["by_gold_parent"]["知识点->句法->句子成分"]["packets"]["k12"]
            ["all_gold_label_coverage"]["counts"]["type_retrieval"],
            1,
        )

    def test_question_level_gold_with_historical_labels_matches_each_label_instance(self):
        second_historical = "知识点->句法->句子成分->状语"
        second_packet = {
            **packet_row(alternatives=[]),
            "review_id": "kp-validation:q-1:adverbial",
            "canonical_label": second_historical,
            "legacy_label": "知识点@句法@句子成分@状语",
            "target_definition": "状语释义",
        }
        question_gold = {
            "source_line": 18,
            "question_id": "q-1",
            "parent_id": "p-1",
            "child_rank": 2,
            "historical_labels": [HISTORICAL, second_historical],
            "gold_labels": [SIBLING],
            "adjudication_status": "approved",
        }

        report = analyze_candidate_budget_coverage(
            {
                "k4": (packet_row(alternatives=[]), second_packet),
                "k12": (packet_row(alternatives=[]), second_packet),
            },
            (question_gold,),
        )

        self.assertEqual(report["approved_gold_records"], 1)
        self.assertEqual(report["gold_rows_with_child_rank"], 1)
        self.assertEqual(report["matched_packet_rows"], 2)
        self.assertEqual(report["primary_correction_packet_rows"], 2)
        self.assertEqual(
            report["by_historical_target_parent"]["知识点->句法->句子成分"]["packets"]["k4"]
            ["primary_correction_label_coverage"]["counts"]["absent"],
            1,
        )

    def test_rejects_gold_review_id_when_immutable_question_identity_differs(self):
        mismatched_gold = {
            **gold_row(),
            "source_line": 19,
        }

        with self.assertRaisesRegex(ValueError, "review_id disagrees"):
            analyze_candidate_budget_coverage(
                {
                    "k4": (packet_row(alternatives=[]),),
                    "k12": (packet_row(alternatives=[]),),
                },
                (mismatched_gold,),
            )


if __name__ == "__main__":
    unittest.main()
