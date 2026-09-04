import json
import tempfile
import unittest
from pathlib import Path


class KnowledgeLabelStatusLedgerTests(unittest.TestCase):
    def test_builds_complete_status_table_and_reconciles_can_label(self):
        from english_knowledge_tagger.knowledge_label_status_ledger import (
            build_knowledge_label_status_ledger,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sample = root / "ledger.md"
            sample.write_text(
                "# sample\n"
                "| 末级知识点 | DS 匹配率 | True | False | 结论 | 摘要 |\n"
                "|---|---:|---:|---:|---|---|\n"
                "| 知识点@词汇@固定搭配/句型 | 90/100 = 90.0% | 12/12 = 100.0% | 0/12 = 0.0% | x | y |\n"
                "| 知识点@语法词法@动词@情态动词@can@can/can't表示推测 | 80/100 = 80.0% | 12/12 = 100.0% | 0/12 = 0.0% | x | y |\n"
                "| 知识点@词汇@待处理标签 | 10/100 = 10.0% | 8/12 = 66.7% | 1/12 = 8.3% | x | y |\n",
                encoding="utf-8",
            )
            base = root / "base.json"
            base.write_text(
                json.dumps({"candidates": [{"legacy_label": "知识点@词汇@固定搭配/句型"}]}),
                encoding="utf-8",
            )
            delta = root / "delta.json"
            delta.write_text(json.dumps({"candidates": []}), encoding="utf-8")
            delta11 = root / "delta11.json"
            delta11.write_text(json.dumps({"candidates": []}), encoding="utf-8")
            output = root / "status.md"

            report = build_knowledge_label_status_ledger(
                full_sample_ledger=sample,
                candidate_manifests=(base, delta, delta11),
                output=output,
                quality_excluded=(),
                post_sweep_hold=(),
                taxonomy_reconciled={
                    "知识点@语法词法@动词@情态动词@can@can/can't表示推测":
                    "知识点->词法->动词->情态动词->can->can't表示否定推测"
                },
                expected_label_count=3,
            )
            text = output.read_text(encoding="utf-8")

        self.assertEqual(report["total_labels"], 3)
        self.assertEqual(report["status_counts"]["training_candidate_unreleased"], 1)
        self.assertEqual(report["status_counts"]["taxonomy_reconciled_pending_rerun"], 1)
        self.assertEqual(report["status_counts"]["pending_fast_pool_review"], 1)
        self.assertIn("知识点->词法->动词->情态动词->can->can't表示否定推测", text)
        self.assertIn("taxonomy 已纠正，待重新物化/终判", text)


if __name__ == "__main__":
    unittest.main()
