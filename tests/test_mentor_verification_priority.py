import unittest

try:
    from english_knowledge_tagger.mentor_verification_priority import (
        assess_mentor_verification_summary,
        wilson_lower_one_sided_95,
    )
except ModuleNotFoundError:
    assess_mentor_verification_summary = None
    wilson_lower_one_sided_95 = None


LABEL = "知识点@词汇@构词法@派生法（词根词缀）"


def summary_with(match: int, total: int, *, error: int = 0) -> dict[str, object]:
    return {
        "schema": "mentor-overall-summary-fixture",
        "categories": [
            {
                "category": "知识点@词汇",
                "label_stats": {
                    LABEL: {
                        "total": total,
                        "match": match,
                        "mismatch": total - match - error,
                        "error": error,
                    }
                },
            }
        ],
    }


class MentorVerificationPriorityTests(unittest.TestCase):
    def test_500_sample_label_requires_367_matches_for_70_percent_one_sided_lower_bound(self):
        self.assertTrue(callable(assess_mentor_verification_summary))
        below = assess_mentor_verification_summary(summary_with(366, 500))
        qualifying = assess_mentor_verification_summary(summary_with(367, 500))

        self.assertEqual(below[0]["status"], "hold_yield_below_threshold")
        self.assertLess(below[0]["wilson_lower_95"], 0.70)
        self.assertEqual(qualifying[0]["status"], "rollout_candidate")
        self.assertGreaterEqual(qualifying[0]["wilson_lower_95"], 0.70)

    def test_service_error_prevents_rollout_even_when_match_rate_is_high(self):
        self.assertTrue(callable(assess_mentor_verification_summary))
        row = assess_mentor_verification_summary(summary_with(490, 500, error=1))[0]

        self.assertEqual(row["status"], "hold_service_errors")
        self.assertEqual(row["match_rate"], 0.98)

    def test_sample_size_changes_the_observed_rate_needed_for_the_same_lower_bound(self):
        self.assertTrue(callable(wilson_lower_one_sided_95))
        self.assertLess(wilson_lower_one_sided_95(350, 500), 0.70)
        self.assertGreaterEqual(wilson_lower_one_sided_95(78, 100), 0.70)


if __name__ == "__main__":
    unittest.main()
