import json
from pathlib import Path
import tempfile
import unittest

try:
    from english_knowledge_tagger.mentor_direct_materialization import materialize_mentor_direct_verdicts
except ModuleNotFoundError:
    materialize_mentor_direct_verdicts = None


LABEL = "知识点@词汇@构词法@转化法"


def _sample(question_id: str) -> dict[str, object]:
    return {
        "verify_label": LABEL,
        "question_id": question_id,
        "parent_id": f"parent-{question_id}",
        "is_sub_question": False,
        "input": "题型结构为：单选题\n题型名称为：选择题\n题目题干：text",
        "output_all": LABEL,
        "contain_audio": False,
        "whole_image": False,
    }


def _verdict(question_id: str, *, match: bool) -> dict[str, object]:
    return {
        "verify_label": LABEL,
        "question_id": question_id,
        "output_all": LABEL,
        "llm_match": match,
        "llm_reason": "理由",
        "llm_should_be": "正确" if match else "知识点@词汇@构词法@派生法（词根词缀）",
    }


class MentorDirectMaterializationTests(unittest.TestCase):
    def test_joins_exact_label_question_identity_and_preserves_sample_order(self):
        self.assertTrue(callable(materialize_mentor_direct_verdicts))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            samples = directory / "samples.jsonl"
            results = directory / "results.jsonl"
            output = directory / "materialized.jsonl"
            samples.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in (_sample("q2"), _sample("q1"))) + "\n",
                encoding="utf-8",
            )
            results.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in (_verdict("q1", match=True), _verdict("q2", match=False))) + "\n",
                encoding="utf-8",
            )

            report = materialize_mentor_direct_verdicts(
                samples,
                results_path=results,
                verify_label=LABEL,
                output_path=output,
            )
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(report["result_records"], 2)
        self.assertEqual(report["sample_records"], 2)
        self.assertEqual(report["materialized_records"], 2)
        self.assertEqual([row["question_id"] for row in rows], ["q2", "q1"])
        self.assertFalse(rows[0]["llm_match"])
        self.assertEqual(rows[1]["parent_id"], "parent-q1")

    def test_rejects_result_without_matching_sample(self):
        self.assertTrue(callable(materialize_mentor_direct_verdicts))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            samples = directory / "samples.jsonl"
            results = directory / "results.jsonl"
            output = directory / "materialized.jsonl"
            samples.write_text(json.dumps(_sample("q1"), ensure_ascii=False) + "\n", encoding="utf-8")
            results.write_text(json.dumps(_verdict("missing", match=True), ensure_ascii=False) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "missing sample"):
                materialize_mentor_direct_verdicts(
                    samples,
                    results_path=results,
                    verify_label=LABEL,
                    output_path=output,
                )


if __name__ == "__main__":
    unittest.main()
