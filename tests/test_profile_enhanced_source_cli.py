import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ProfileEnhancedSourceCliTests(unittest.TestCase):
    def test_cli_writes_report_and_stratified_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jsonl"
            report = root / "report.json"
            index = root / "index.sqlite3"
            samples = root / "samples.jsonl"
            source.write_text(
                json.dumps(
                    {
                        "input": "题型结构为：单选题\n题型名称为：选择题\n题目题干：What?",
                        "output": "知识点@x",
                        "question_id": "q1",
                        "parent_id": "q1",
                        "is_sub_question": False,
                        "contain_audio": False,
                        "whole_image": False,
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            script = Path(__file__).resolve().parents[1] / "scripts" / "profile_enhanced_source.py"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--input",
                    str(source),
                    "--output-report",
                    str(report),
                    "--index",
                    str(index),
                    "--samples",
                    str(samples),
                    "--sample-per-bucket",
                    "1",
                    "--seed",
                    "cli-test",
                    "--progress-every",
                    "1",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            report_payload = json.loads(report.read_text(encoding="utf-8"))
            sample_rows = [
                json.loads(line)
                for line in samples.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(report_payload["valid_records"], 1)
            self.assertEqual(report_payload["type_bucket_count"], 1)
            self.assertEqual(len(sample_rows), 2)
            self.assertIn('"processed_valid_records": 1', completed.stderr)


if __name__ == "__main__":
    unittest.main()
