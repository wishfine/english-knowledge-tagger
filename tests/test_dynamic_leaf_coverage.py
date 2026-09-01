import csv
from pathlib import Path
import tempfile
import unittest

from english_knowledge_tagger.dynamic_leaf_coverage import summarize_dynamic_leaf_coverage
from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook


class DynamicLeafCoverageTests(unittest.TestCase):
    def test_compares_siblings_dynamic_budgets_and_baseline_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            teacher = root / "teacher.csv"
            rows = [
                ("知识点->词汇->构词法->转化法", "同形转化"),
                ("知识点->词汇->构词法->派生法", "词缀派生"),
                ("知识点->词法->名词->复数", "名词复数"),
                ("知识点->语用->时间->顺序", "事件顺序"),
            ]
            with teacher.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=(
                        "末级知识点",
                        "打标解读（标绿的标签，新题不再打）",
                        "大模型压缩+人工微调的释义",
                    ),
                )
                writer.writeheader()
                for label, definition in rows:
                    writer.writerow(
                        {
                            "末级知识点": label,
                            "打标解读（标绿的标签，新题不再打）": definition,
                            "大模型压缩+人工微调的释义": definition,
                        }
                    )
            rulebook = load_knowledge_rulebook(teacher)
            corrections = (
                {
                    "schema_version": "teacher-subquestion-gold-correction-v1",
                    "question_id": "q1",
                    "historical_label": "知识点->词汇->构词法->转化法",
                    "gold_labels": ["知识点->词汇->构词法->派生法"],
                    "route_key": {"scope": "child"},
                    "question_text": "direct变成director",
                },
                {
                    "schema_version": "teacher-subquestion-gold-correction-v1",
                    "question_id": "q2",
                    "historical_label": "知识点->词汇->构词法->转化法",
                    "gold_labels": ["知识点->词法->名词->复数"],
                    "route_key": {"scope": "child"},
                    "question_text": "名词变复数",
                },
            )
            ambiguity = {
                "labels": [
                    {
                        "canonical_label": "知识点->词汇->构词法->转化法",
                        "confusion_neighbors": [
                            {"canonical_label": "知识点->词法->名词->复数", "count": 10}
                        ],
                    }
                ]
            }
            baseline = {
                ("q1", "知识点->词汇->构词法->转化法"): {
                    "知识点->词汇->构词法->派生法"
                },
                ("q2", "知识点->词汇->构词法->转化法"): set(),
            }
            report = summarize_dynamic_leaf_coverage(
                rulebook,
                corrections=corrections,
                ambiguity_manifest=ambiguity,
                baseline_candidates=baseline,
            )
            self.assertEqual(report["correction_records"], 2)
            self.assertEqual(report["strategies"]["direct_siblings_all"]["covered_records"], 1)
            self.assertEqual(report["strategies"]["dynamic_top4"]["covered_records"], 2)
            self.assertEqual(report["strategies"]["retrieval12_sibling8"]["covered_records"], 1)
            pair = next(iter(report["by_historical_parent_and_gold_parent"].values()))
            self.assertIn(pair["selected_budget"], {"dynamic_top4", "dynamic_top8"})


if __name__ == "__main__":
    unittest.main()
