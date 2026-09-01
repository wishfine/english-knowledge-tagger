import json
from pathlib import Path
import tempfile
import unittest

from english_knowledge_tagger.knowledge_definition_ablation_analysis import (
    summarize_definition_ablation,
)


class KnowledgeDefinitionAblationAnalysisTests(unittest.TestCase):
    def _write(self, directory: str, name: str, rows: list[dict]) -> Path:
        path = Path(directory) / name
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
        return path

    def test_summary_pairs_same_tasks_and_counts_decision_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            baseline = self._write(
                directory,
                "baseline.jsonl",
                [
                    {
                        "task_id": "t1",
                        "status": "tree_candidate",
                        "candidate_label": "知识点->词汇->构词法->转化法",
                        "task_elapsed_ms": 10,
                    },
                    {
                        "task_id": "t2",
                        "status": "uncovered",
                        "candidate_label": None,
                        "task_elapsed_ms": 20,
                    },
                ],
            )
            override = self._write(
                directory,
                "override.jsonl",
                [
                    {
                        "task_id": "t1",
                        "status": "tree_candidate",
                        "candidate_label": "知识点->词汇->构词法->派生法（词根词缀）",
                        "task_elapsed_ms": 30,
                    },
                    {
                        "task_id": "t2",
                        "status": "uncovered",
                        "candidate_label": None,
                        "task_elapsed_ms": 40,
                    },
                ],
            )

            report = summarize_definition_ablation(baseline, override)

        self.assertEqual(report["common_tasks"], 2)
        self.assertEqual(report["decision_changes"], 1)
        self.assertEqual(report["candidate_changes"], 1)
        self.assertEqual(report["status_changes"], 0)
        self.assertEqual(report["candidate_change_task_ids"], ["t1"])
        self.assertEqual(report["baseline_status_counts"], {"tree_candidate": 1, "uncovered": 1})
        self.assertEqual(report["override_status_counts"], {"tree_candidate": 1, "uncovered": 1})
        self.assertEqual(report["timing_ms"]["baseline"]["mean"], 15)
        self.assertEqual(report["timing_ms"]["override"]["mean"], 35)

    def test_summary_rejects_different_task_sets(self):
        with tempfile.TemporaryDirectory() as directory:
            baseline = self._write(directory, "baseline.jsonl", [{"task_id": "t1"}])
            override = self._write(directory, "override.jsonl", [{"task_id": "t2"}])
            with self.assertRaisesRegex(ValueError, "task sets differ"):
                summarize_definition_ablation(baseline, override)


if __name__ == "__main__":
    unittest.main()
