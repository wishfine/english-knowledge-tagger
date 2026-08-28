import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "analyze_web_gpt_raw_reviews.py"
LABEL = "知识点@语法词法@动词@实义动词@及物动词"


class AnalyzeWebGptRawReviewsCliTests(unittest.TestCase):
    def test_normalizes_complete_web_review_object_stream(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source_path = directory / "source.jsonl"
            source_path.write_text(
                json.dumps(
                    {
                        "verify_label": LABEL,
                        "question_id": "q1",
                        "parent_id": "q1",
                        "is_sub_question": False,
                        "input": "题型结构为：单选题\n题型名称为：选择题\n题目题干：He likes apples.",
                        "llm_match": True,
                        "llm_should_be": "正确",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            review_path = directory / "reviews.txt"
            review_path.write_text(
                json.dumps(
                    {
                        "question_id": "q1",
                        "parent_id": "q1",
                        "decision": "keep",
                        "reason_code": "object_case",
                        "reason": "宾语形式受及物性约束。",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            normalized_path = directory / "normalized.jsonl"
            report_path = directory / "report.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source",
                    str(source_path),
                    "--reviewer-results",
                    str(review_path),
                    "--verify-label",
                    LABEL,
                    "--normalized-output",
                    str(normalized_path),
                    "--report",
                    str(report_path),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            row = json.loads(normalized_path.read_text(encoding="utf-8"))

        self.assertEqual(report["decisions"], {"keep": 1, "remove": 0, "uncertain": 0})
        self.assertEqual(row["reviewer_mode"], "anchored_raw_source_review")
        self.assertEqual(row["mentor_direct_verdict"], "match")


if __name__ == "__main__":
    unittest.main()
