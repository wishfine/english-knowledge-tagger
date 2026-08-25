import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class BuildKnowledgeTreeTasksCliTests(unittest.TestCase):
    def test_cli_builds_required_missing_label_task(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = directory / "source.jsonl"
            source.write_text(
                json.dumps(
                    {
                        "question_id": "child-add",
                        "is_sub_question": True,
                        "input": "题型结构为：复合题\n题型名称为：语法选择\n题干：It is ___ umbrella. 答案：an。",
                        "output": "题型@特殊题型@语法选择",
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
            packet = directory / "packet.jsonl"
            packet.write_text("", encoding="utf-8")
            verdicts = directory / "verdicts.jsonl"
            verdicts.write_text("", encoding="utf-8")
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
                                "knowledge_policy": "required",
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
            output = directory / "tasks.jsonl"
            report = directory / "report.json"
            script = Path(__file__).resolve().parents[1] / "scripts" / "build_knowledge_tree_tasks.py"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--source",
                    str(source),
                    "--review-packet",
                    str(review),
                    "--validation-packet",
                    str(packet),
                    "--validation-verdicts",
                    str(verdicts),
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
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8"))["trigger_kinds"],
                ["add_missing_required"],
            )
            self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["tasks"], 1)


if __name__ == "__main__":
    unittest.main()
