import unittest

try:
    from english_knowledge_tagger.knowledge_tree_timing import summarize_tree_timing
except ModuleNotFoundError:
    summarize_tree_timing = None


class KnowledgeTreeTimingTests(unittest.TestCase):
    def test_summary_aggregates_task_choice_and_node_timings(self):
        self.assertTrue(callable(summarize_tree_timing), "summarize_tree_timing must be implemented")
        rows = [
            {
                "task_id": "slow",
                "status": "tree_candidate",
                "task_elapsed_ms": 20.0,
                "queue_elapsed_ms": 3.0,
                "trace": [
                    {
                        "parent_path": "知识点->词法->介词",
                        "choice": "知识点->词法->介词->时间介词",
                        "choice_elapsed_ms": 12.0,
                        "model_call_elapsed_ms": 11.0,
                        "candidate_count": 7,
                        "prompt_chars": 400,
                    },
                    {
                        "parent_path": "知识点->词法->介词",
                        "choice": "__NO_MATCH__",
                        "choice_elapsed_ms": 5.0,
                        "model_call_elapsed_ms": 4.0,
                        "candidate_count": 3,
                        "prompt_chars": 200,
                    },
                ],
            },
            {
                "task_id": "fast",
                "status": "tree_candidate",
                "task_elapsed_ms": 10.0,
                "queue_elapsed_ms": 1.0,
                "trace": [
                    {
                        "parent_path": "知识点->词法->冠词",
                        "choice": "知识点->词法->冠词->a/an的区别",
                        "choice_elapsed_ms": 3.0,
                        "model_call_elapsed_ms": 2.0,
                        "candidate_count": 2,
                        "prompt_chars": 100,
                    }
                ],
            },
        ]

        report = summarize_tree_timing(rows, wall_elapsed_ms=100.0, concurrency=16)

        self.assertEqual(report["processed"], 2)
        self.assertEqual(report["wall_elapsed_ms"], 100.0)
        self.assertEqual(report["task_elapsed_ms"]["p95"], 20.0)
        self.assertEqual(report["choice_elapsed_ms"]["count"], 3)
        self.assertEqual(report["nodes"][0]["parent_path"], "知识点->词法->介词")
        self.assertEqual(report["nodes"][0]["calls"], 2)
        self.assertEqual(report["nodes"][0]["no_match_calls"], 1)
        self.assertEqual(report["nodes"][0]["mean_candidate_count"], 5.0)
        self.assertEqual(report["slow_tasks"][0]["task_id"], "slow")


if __name__ == "__main__":
    unittest.main()
