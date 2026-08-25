import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class BuildKnowledgeValidationPacketCliTests(unittest.TestCase):
    def test_cli_joins_selected_source_rows_to_teacher_definitions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = directory / "source.jsonl"
            source.write_text(
                json.dumps(
                    {
                        "question_id": "child-1",
                        "parent_id": "parent-1",
                        "is_sub_question": True,
                        "input": "题干：It is ___ umbrella.\n答案：an\n解析：考查 a/an 的区别。",
                        "output": "知识点@词法@冠词@a/an的区别",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            review = directory / "review.jsonl"
            review.write_text(
                json.dumps(
                    {
                        "source_line": 1,
                        "route_key": {
                            "scope": "child",
                            "declared_type_structure": "复合题",
                            "declared_type_name": "语法选择",
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            teacher = directory / "teacher.csv"
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
                writer.writerow(
                    {
                        "末级知识点": "知识点->词法->冠词->a/an的区别",
                        "打标解读（标绿的标签，新题不再打）": "按读音选择 a/an。",
                        "大模型压缩+人工微调的释义": "按读音选择 a/an。",
                    }
                )
            policy = directory / "policy.json"
            policy.write_text(
                json.dumps(
                    {
                        "schema_version": "knowledge-candidate-policy-v1",
                        "rules": [
                            {
                                "scope": "child",
                                "declared_type_structure": "复合题",
                                "declared_type_name": "语法选择",
                                "allowed_knowledge_prefixes": ["知识点->词法"],
                                "max_retrieved_candidates": 12,
                                "max_sibling_candidates": 8,
                                "max_output_labels": 3,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            output = directory / "packet.jsonl"
            report = directory / "report.json"
            script = Path(__file__).resolve().parents[1] / "scripts" / "build_knowledge_validation_packet.py"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--source",
                    str(source),
                    "--review-packet",
                    str(review),
                    "--teacher-csv",
                    str(teacher),
                    "--candidate-policy",
                    str(policy),
                    "--output",
                    str(output),
                    "--report",
                    str(report),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["records"], 1)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["taxonomy_status"], "known")


if __name__ == "__main__":
    unittest.main()
