import unittest

try:
    from english_knowledge_tagger.knowledge_tree_run_analysis import summarize_run_groups
except ModuleNotFoundError:
    summarize_run_groups = None


def _row(task_id: str, label: str | None, *, mode: str, trigger_kinds: list[str]) -> dict[str, object]:
    return {
        "task_id": task_id,
        "status": "tree_candidate" if label is not None else "uncovered",
        "candidate_label": label,
        "terminal_definition_mode": mode,
        "trigger_kinds": trigger_kinds,
        "trace": [
            {"choice": "知识点->词法"},
            {"choice": label or "__NO_MATCH__"},
        ],
    }


class KnowledgeTreeRunAnalysisTests(unittest.TestCase):
    def test_summary_reports_three_repeat_stability_and_replace_slice(self):
        self.assertTrue(callable(summarize_run_groups), "summarize_run_groups must be implemented")
        candidate_a = "知识点->词法->冠词->a/an的区别"
        candidate_b = "知识点->词法->冠词->the的用法"
        compressed = tuple(
            (
                f"compressed-{index}",
                (
                    _row("replace-1", candidate_a, mode="compressed", trigger_kinds=["replace"]),
                    _row("add-1", candidate_a, mode="compressed", trigger_kinds=["add_missing_required"]),
                ),
            )
            for index in (1, 2, 3)
        )
        none = (
            (
                "none-1",
                (
                    _row("replace-1", candidate_a, mode="none", trigger_kinds=["replace"]),
                    _row("add-1", candidate_a, mode="none", trigger_kinds=["add_missing_required"]),
                ),
            ),
            (
                "none-2",
                (
                    _row("replace-1", candidate_b, mode="none", trigger_kinds=["replace"]),
                    _row("add-1", candidate_a, mode="none", trigger_kinds=["add_missing_required"]),
                ),
            ),
            (
                "none-3",
                (
                    _row("replace-1", candidate_a, mode="none", trigger_kinds=["replace"]),
                    _row("add-1", candidate_a, mode="none", trigger_kinds=["add_missing_required"]),
                ),
            ),
        )

        report = summarize_run_groups({"compressed": compressed, "none": none})

        self.assertEqual(report["groups"]["compressed"]["mode"], "compressed")
        self.assertEqual(
            report["groups"]["compressed"]["replace"]["all_three_candidate_agreement"], 1.0
        )
        self.assertEqual(report["groups"]["none"]["replace"]["all_three_candidate_agreement"], 0.0)
        self.assertEqual(
            report["groups"]["none"]["replace"]["candidate_disagreement_task_ids"],
            ["replace-1"],
        )
        self.assertEqual(report["groups"]["none"]["all_tasks"]["all_three_candidate_agreement"], 0.5)
        self.assertEqual(report["comparison"]["common_tasks_all_six"], 2)
        self.assertEqual(report["comparison"]["unanimous_candidate_disagreements"], 0)

    def test_summary_rejects_group_without_exactly_three_runs(self):
        self.assertTrue(callable(summarize_run_groups), "summarize_run_groups must be implemented")

        with self.assertRaisesRegex(ValueError, "exactly three"):
            summarize_run_groups({"compressed": (("one", ()),), "none": (("one", ()),)})


if __name__ == "__main__":
    unittest.main()
