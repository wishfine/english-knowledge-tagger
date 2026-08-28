import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_p0_direct_diagnosis_packets.py"
LABEL = "知识点@语法词法@动词@实义动词@及物动词"


class BuildP0DirectDiagnosisPacketsCliTests(unittest.TestCase):
    def test_builds_blind_packets_with_explicit_migration_and_rulebook(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            input_path = directory / "verification.jsonl"
            input_path.write_text(
                json.dumps(
                    {
                        "verify_label": LABEL,
                        "question_id": "q1",
                        "parent_id": "q1",
                        "is_sub_question": False,
                        "input": (
                            "题型结构为：单选题\n题型名称为：选择题\n"
                            "题目题干：He likes apples.\n题目解析：test\n题目答案：A"
                        ),
                        "output_all": LABEL,
                        "llm_match": True,
                        "llm_reason": "reason",
                        "llm_should_be": "正确",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            with input_path.open("a", encoding="utf-8") as output:
                output.write(
                    json.dumps(
                        {
                            "verify_label": LABEL,
                            "question_id": "q2",
                            "parent_id": "q2",
                            "is_sub_question": False,
                            "input": (
                                "题型结构为：填空题\n题型名称为：完成句子\n"
                                "题目题干：He finishes homework.\n题目解析：test\n题目答案：A"
                            ),
                            "output_all": LABEL,
                            "llm_match": False,
                            "llm_reason": "reason",
                            "llm_should_be": "知识点@词汇@固定搭配/句型",
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            true_output = directory / "true.jsonl"
            false_output = directory / "false.jsonl"
            audit_output = directory / "audit.jsonl"
            report_path = directory / "report.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input",
                    str(input_path),
                    "--verify-label",
                    LABEL,
                    "--teacher-csv",
                    str(ROOT / "data/rulebooks/初中英语知识点题型方法释义.csv"),
                    "--taxonomy-migration",
                    str(ROOT / "configs/knowledge_taxonomy_migrations/legacy-rendered-to-teacher-v1.json"),
                    "--true-output",
                    str(true_output),
                    "--false-output",
                    str(false_output),
                    "--audit-output",
                    str(audit_output),
                    "--report",
                    str(report_path),
                    "--false-sample-size",
                    "60",
                    "--false-boundary-question-id",
                    "q2",
                    "--seed",
                    "cli-test",
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            row = json.loads(true_output.read_text(encoding="utf-8").strip())

        self.assertEqual(report["selected_true_records"], 1)
        self.assertEqual(report["selected_false_records"], 1)
        self.assertEqual(report["false_boundary_question_ids"], ["q2"])
        self.assertEqual(row["active_taxonomy_label"], "知识点->词法->动词->实义动词->及物动词")


if __name__ == "__main__":
    unittest.main()
