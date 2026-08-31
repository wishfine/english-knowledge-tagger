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


def _source_row_without_direct_verdict(question_id: str) -> dict[str, object]:
    row = _source_row(question_id, direct_match=False)
    row["llm_match"] = None
    row["llm_should_be"] = ""
    return row


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

    def test_accepts_one_final_web_gpt_conclusion_after_review_rows(self):
        self.assertTrue(callable(analyze_web_gpt_raw_reviews))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source_path = directory / "source.jsonl"
            source_path.write_text(
                json.dumps(_source_row("q1", direct_match=True), ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            review_path = directory / "reviews.jsonl"
            review_path.write_text(
                "\n".join(
                    json.dumps(row, ensure_ascii=False)
                    for row in (
                        _review("q1", "q1", "keep", "object_case"),
                        {
                            "record_type": "label_conclusion",
                            "verify_label": LABEL,
                            "recommended_disposition": "teacher_policy_required",
                            "teacher_question_ids": ["q1"],
                            "rationale": "当前标签存在待老师冻结的边界。",
                        },
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            report, normalized = analyze_web_gpt_raw_reviews(
                source_path,
                reviewer_results_path=review_path,
                verify_label=LABEL,
            )

        self.assertEqual(len(normalized), 1)
        self.assertEqual(report["web_gpt_conclusion"]["recommended_disposition"], "teacher_policy_required")
        self.assertEqual(report["web_gpt_conclusion"]["teacher_question_ids"], ["q1"])

    def test_preserves_unavailable_mentor_verdict_without_counting_it_as_mismatch(self):
        self.assertTrue(callable(analyze_web_gpt_raw_reviews))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source_path = directory / "source.jsonl"
            source_path.write_text(
                "\n".join(
                    json.dumps(row, ensure_ascii=False)
                    for row in (
                        _source_row("q1", direct_match=True),
                        _source_row_without_direct_verdict("q2"),
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            review_path = directory / "reviews.jsonl"
            review_path.write_text(
                "\n".join(
                    json.dumps(_review(qid, qid, "keep", "other"), ensure_ascii=False)
                    for qid in ("q1", "q2")
                )
                + "\n",
                encoding="utf-8",
            )

            report, normalized = analyze_web_gpt_raw_reviews(
                source_path,
                reviewer_results_path=review_path,
                verify_label=LABEL,
            )

        self.assertEqual(report["mentor_direct_verdict_x_web_decision"]["match"], {"keep": 1, "remove": 0, "uncertain": 0})
        self.assertEqual(report["mentor_direct_verdict_x_web_decision"]["mismatch"], {"keep": 0, "remove": 0, "uncertain": 0})
        self.assertEqual(report["mentor_direct_verdict_x_web_decision"]["unavailable"], {"keep": 1, "remove": 0, "uncertain": 0})
        self.assertEqual(normalized[1]["mentor_direct_verdict"], "unavailable")

    def test_accepts_collective_noun_review_reason_codes(self):
        self.assertTrue(callable(analyze_web_gpt_raw_reviews))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source_path = directory / "source.jsonl"
            source_path.write_text(json.dumps(_source_row("q1", direct_match=True), ensure_ascii=False) + "\n", encoding="utf-8")
            review_path = directory / "reviews.jsonl"
            review_path.write_text(
                json.dumps(_review("q1", "q1", "keep", "whole_member_agreement"), ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            report, normalized = analyze_web_gpt_raw_reviews(
                source_path,
                reviewer_results_path=review_path,
                verify_label=LABEL,
            )

        self.assertEqual(report["decisions"], {"keep": 1, "remove": 0, "uncertain": 0})
        self.assertEqual(normalized[0]["reason_code"], "whole_member_agreement")


if __name__ == "__main__":
    unittest.main()
