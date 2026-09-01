import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class RepairParentContextCliTests(unittest.TestCase):
    def test_cli_builds_audited_derived_source_without_changing_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw.jsonl"
            enhanced = root / "enhanced.jsonl"
            index = root / "raw-index.sqlite3"
            output = root / "v3.jsonl"
            audit = root / "audit.jsonl"
            report = root / "report.json"
            manifest = root / "manifest.json"

            raw.write_text(
                json.dumps(
                    {
                        "question_id": "p1",
                        "parent_id": "p1",
                        "stem": "A passage.",
                        "options": "",
                        "analysis": "",
                        "answer": "",
                        "knowledge_points": ["知识点@parent"],
                        "question_types": [],
                        "sub_questions": [
                            {
                                "question_id": "c1",
                                "parent_id": "p1",
                                "stem": "What?",
                                "options": "A. yes",
                                "analysis": "Because.",
                                "answer": "A",
                                "knowledge_points": ["知识点@child"],
                                "question_types": [],
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            enhanced.write_text(
                "\n".join(
                    json.dumps(row, ensure_ascii=False)
                    for row in (
                        {
                            "input": "当前小题题干：What?",
                            "output": "知识点@child",
                            "question_id": "c1",
                            "parent_id": "p1",
                            "is_sub_question": True,
                            "contain_audio": False,
                            "whole_image": False,
                        },
                        {
                            "input": "父题不变",
                            "output": "题型@选择题",
                            "question_id": "p1",
                            "parent_id": "p1",
                            "is_sub_question": False,
                            "contain_audio": False,
                            "whole_image": False,
                        },
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            script = Path(__file__).resolve().parents[1] / "scripts" / "repair_parent_context.py"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--raw",
                    str(raw),
                    "--enhanced",
                    str(enhanced),
                    "--index",
                    str(index),
                    "--output",
                    str(output),
                    "--audit",
                    str(audit),
                    "--report",
                    str(report),
                    "--manifest",
                    str(manifest),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            output_rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            audit_rows = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
            report_payload = json.loads(report.read_text(encoding="utf-8"))
            manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))

            self.assertEqual(len(output_rows), 2)
            self.assertIn("A passage.", output_rows[0]["input"])
            self.assertEqual(output_rows[0]["output"], "知识点@child")
            self.assertEqual(
                set(output_rows[0]) - {"input"},
                {"output", "question_id", "parent_id", "is_sub_question", "contain_audio", "whole_image"},
            )
            self.assertEqual(output_rows[1]["input"], "父题不变")
            self.assertEqual(
                [row["status"] for row in audit_rows], ["added", "not_child"]
            )
            self.assertEqual(report_payload["changed_rows"], 1)
            self.assertEqual(report_payload["source_sha256"], manifest_payload["source_sha256"])
            self.assertEqual(report_payload["raw_sha256"], manifest_payload["raw_sha256"])
            self.assertEqual(manifest_payload["raw_index_path"], str(index))


if __name__ == "__main__":
    unittest.main()
