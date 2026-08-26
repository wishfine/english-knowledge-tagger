import unittest

try:
    from english_knowledge_tagger.knowledge_validation_timing import (
        summarize_validation_timing,
    )
except ModuleNotFoundError:
    summarize_validation_timing = None


class KnowledgeValidationTimingTests(unittest.TestCase):
    def test_summary_aggregates_request_latency_and_canonical_target_parents(self):
        self.assertTrue(
            callable(summarize_validation_timing),
            "summarize_validation_timing must be implemented",
        )
        rows = [
            {
                "review_id": "slow-review",
                "question_id": "q-slow",
                "canonical_label": "知识点->词法->介词->时间介词",
                "status": "candidate",
                "task_elapsed_ms": 20.0,
                "queue_elapsed_ms": 3.0,
                "model_call_elapsed_ms": 12.0,
                "prompt_chars": 400,
                "response_chars": 120,
            },
            {
                "review_id": "fast-review",
                "question_id": "q-fast",
                "canonical_label": "知识点->词法->介词->地点介词",
                "status": "candidate",
                "task_elapsed_ms": 10.0,
                "queue_elapsed_ms": 1.0,
                "model_call_elapsed_ms": 2.0,
                "prompt_chars": 100,
                "response_chars": 60,
            },
            {
                "review_id": "skipped-review",
                "canonical_label": "知识点->语篇->语篇主题",
                "status": "skipped",
                "task_elapsed_ms": 1.0,
                "queue_elapsed_ms": 0.0,
            },
        ]

        report = summarize_validation_timing(rows, wall_elapsed_ms=100.0, concurrency=16)

        self.assertEqual(report["processed"], 3)
        self.assertEqual(report["status_counts"], {"candidate": 2, "skipped": 1})
        self.assertEqual(report["task_elapsed_ms"]["p95"], 20.0)
        self.assertEqual(report["model_call_elapsed_ms"]["count"], 2)
        self.assertEqual(report["target_parents"][0]["target_parent_path"], "知识点->词法->介词")
        self.assertEqual(report["target_parents"][0]["calls"], 2)
        self.assertEqual(report["target_parents"][0]["mean_prompt_chars"], 250.0)
        self.assertEqual(report["slow_rows"][0]["review_id"], "slow-review")
        self.assertNotIn("question_id", report["slow_rows"][0])
        self.assertNotIn("question_context", report["slow_rows"][0])
        self.assertNotIn("raw_response", report["slow_rows"][0])
        self.assertNotIn("evidence", report["slow_rows"][0])


if __name__ == "__main__":
    unittest.main()
