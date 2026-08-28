import json
from pathlib import Path
import tempfile
import unittest


try:
    from english_knowledge_tagger.web_gpt_raw_review_analysis import (
        analyze_web_gpt_raw_reviews,
    )
except ImportError:
    analyze_web_gpt_raw_reviews = None


LABEL = "知识点@语法词法@动词@实义动词@及物动词"


def _source_row(question_id: str, *, direct_match: bool, parent_id: str | None = None) -> dict[str, object]:
    return {
        "verify_label": LABEL,
        "question_id": question_id,
        "parent_id": parent_id or question_id,
        "is_sub_question": False,
        "input": "题型结构为：单选题\n题型名称为：选择题\n题目题干：test",
        "output_all": LABEL,
        "llm_match": direct_match,
        "llm_should_be": "正确" if direct_match else "知识点@词汇@固定搭配/句型",
    }


def _review(question_id: str, parent_id: str, decision: str, reason_code: str) -> dict[str, object]:
    return {
        "question_id": question_id,
        "parent_id": parent_id,
        "decision": decision,
        "reason_code": reason_code,
        "reason": f"{decision} evidence",
    }


class WebGptRawReviewAnalysisTests(unittest.TestCase):
    def test_validates_complete_raw_review_and_reports_ds_cross_tab(self):
        self.assertTrue(callable(analyze_web_gpt_raw_reviews))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source_path = directory / "source.jsonl"
            source_path.write_text(
                "\n".join(
                    json.dumps(row, ensure_ascii=False)
                    for row in (
                        _source_row("q1", direct_match=True),
                        _source_row("q2", direct_match=False),
                        _source_row("q3", direct_match=False),
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            review_path = directory / "reviews.txt"
            review_path.write_text(
                " ".join(
                    json.dumps(row, ensure_ascii=False)
                    for row in (
                        _review("q1", "q1", "keep", "object_case"),
                        _review("q2", "q2", "remove", "lexical_or_spelling_only"),
                        _review("q3", "q3", "uncertain", "insufficient_context"),
                    )
                ),
                encoding="utf-8",
            )

            report, normalized = analyze_web_gpt_raw_reviews(
                source_path,
                reviewer_results_path=review_path,
                verify_label=LABEL,
            )

        self.assertEqual(report["source_records"], 3)
        self.assertEqual(report["review_records"], 3)
        self.assertEqual(report["decisions"], {"keep": 1, "remove": 1, "uncertain": 1})
        self.assertEqual(report["mentor_direct_verdict_x_web_decision"]["match"], {"keep": 1, "remove": 0, "uncertain": 0})
        self.assertEqual(report["mentor_direct_verdict_x_web_decision"]["mismatch"], {"keep": 0, "remove": 1, "uncertain": 1})
        self.assertEqual(report["release_status"], "reviewer_evidence_only")
        self.assertEqual(len(normalized), 3)
        self.assertEqual(normalized[0]["source_line"], 1)
        self.assertEqual(normalized[1]["route_key"]["declared_type_name"], "选择题")

    def test_rejects_parent_id_mismatch(self):
        self.assertTrue(callable(analyze_web_gpt_raw_reviews))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source_path = directory / "source.jsonl"
            source_path.write_text(json.dumps(_source_row("q1", direct_match=True), ensure_ascii=False) + "\n", encoding="utf-8")
            review_path = directory / "reviews.jsonl"
            review_path.write_text(
                json.dumps(_review("q1", "wrong-parent", "keep", "object_case"), ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "parent_id does not match"):
                analyze_web_gpt_raw_reviews(
                    source_path,
                    reviewer_results_path=review_path,
                    verify_label=LABEL,
                )


if __name__ == "__main__":
    unittest.main()
