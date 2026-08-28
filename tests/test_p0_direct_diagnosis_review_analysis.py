import json
from pathlib import Path
import tempfile
import unittest


try:
    from english_knowledge_tagger.p0_direct_diagnosis_review_analysis import (
        analyze_p0_direct_diagnosis_reviews,
    )
except ImportError:
    analyze_p0_direct_diagnosis_reviews = None


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def _blind(review_id: str) -> dict[str, object]:
    return {
        "schema_version": "p0-direct-diagnosis-blind-review-v1",
        "review_id": review_id,
        "legacy_label": "知识点@语法词法@动词@实义动词@及物动词",
        "active_taxonomy_label": "知识点->词法->动词->实义动词->及物动词",
        "question_context": "题目题干：test",
    }


def _audit(
    review_id: str,
    *,
    review_set: str,
    route: str = "parent × 单选题 × 选择题",
    suggestion_family: str | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "p0-direct-diagnosis-audit-v1",
        "review_id": review_id,
        "review_set": review_set,
        "selection_stratum": "direct_true_all" if review_set == "true" else "false_route_suggestion",
        "route_key": {
            "scope": route.split(" × ")[0],
            "declared_type_structure": route.split(" × ")[1],
            "declared_type_name": route.split(" × ")[2],
        },
        "suggestion_family": suggestion_family,
    }


def _review(review_id: str, decision: str) -> dict[str, object]:
    return {"review_id": review_id, "decision": decision, "reason": f"{decision} reason"}


class P0DirectDiagnosisReviewAnalysisTests(unittest.TestCase):
    def test_joins_complete_reviews_and_reports_conditional_false_retention(self):
        self.assertTrue(callable(analyze_p0_direct_diagnosis_reviews))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            true_path = _write_jsonl(directory / "true.jsonl", [_blind("t1"), _blind("t2")])
            false_path = _write_jsonl(directory / "false.jsonl", [_blind("f1"), _blind("f2"), _blind("f3")])
            audit_path = _write_jsonl(
                directory / "audit.jsonl",
                [
                    _audit("t1", review_set="true"),
                    _audit("t2", review_set="true", route="parent × 填空题 × 单词拼写"),
                    _audit("f1", review_set="false", suggestion_family="知识点@语法词法@动词时态"),
                    _audit("f2", review_set="false", suggestion_family="知识点@语法词法@被动语态"),
                    _audit("f3", review_set="false", suggestion_family="知识点@词汇@固定搭配/句型"),
                ],
            )
            review_path = _write_jsonl(
                directory / "reviews.jsonl",
                [_review("t1", "keep"), _review("t2", "remove"), _review("f1", "remove"), _review("f2", "keep"), _review("f3", "uncertain")],
            )

            report = analyze_p0_direct_diagnosis_reviews(
                true_path,
                false_packet_path=false_path,
                audit_index_path=audit_path,
                reviewer_results_path=review_path,
            )

        self.assertEqual(report["reviewed_records"], 5)
        self.assertEqual(report["true_set"]["decisions"], {"keep": 1, "remove": 1, "uncertain": 0})
        self.assertEqual(report["false_set"]["decisions"], {"keep": 1, "remove": 1, "uncertain": 1})
        self.assertEqual(report["false_set"]["conditional_retain_rate_excluding_uncertain"], 0.5)
        self.assertEqual(report["release_status"], "hold_true_review_has_non_keep")
        self.assertEqual(
            report["false_set"]["by_suggestion_family"]["知识点@语法词法@被动语态"],
            {"keep": 1, "remove": 0, "uncertain": 0},
        )

    def test_rejects_review_result_when_expected_id_is_missing(self):
        self.assertTrue(callable(analyze_p0_direct_diagnosis_reviews))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            true_path = _write_jsonl(directory / "true.jsonl", [_blind("t1")])
            false_path = _write_jsonl(directory / "false.jsonl", [_blind("f1")])
            audit_path = _write_jsonl(
                directory / "audit.jsonl",
                [_audit("t1", review_set="true"), _audit("f1", review_set="false")],
            )
            review_path = _write_jsonl(directory / "reviews.jsonl", [_review("t1", "keep")])

            with self.assertRaisesRegex(ValueError, "missing review results"):
                analyze_p0_direct_diagnosis_reviews(
                    true_path,
                    false_packet_path=false_path,
                    audit_index_path=audit_path,
                    reviewer_results_path=review_path,
                )


if __name__ == "__main__":
    unittest.main()
