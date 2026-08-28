import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class PositiveCandidateYieldSummaryTests(unittest.TestCase):
    def test_summary_buckets_each_manifest_label_once_and_flags_below_threshold(self):
        from english_knowledge_tagger.positive_candidate_yield_summary import (
            build_positive_candidate_yield_summary,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            first = directory / "first.json"
            second = directory / "second.json"
            mentor_report = directory / "verification_report.md"
            first.write_text(
                json.dumps({"candidates": [{"legacy_label": "知识点@A"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            second.write_text(
                json.dumps({"candidates": [{"legacy_label": "知识点@B"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            mentor_report.write_text(
                "| 标签 | 总数 | 匹配 | 不匹配 | 错误 | 匹配率 |\n"
                "|---|---:|---:|---:|---:|---:|\n"
                "| 知识点@A | 100 | 95 | 5 | 0 | 95.0% |\n"
                "| 知识点@B | 100 | 60 | 40 | 0 | 60.0% |\n",
                encoding="utf-8",
            )

            report = build_positive_candidate_yield_summary((first, second), mentor_report)

        self.assertIn("## DS match ≥90%（1）", report)
        self.assertIn("## DS match <70%：快速筛选 hold（1）", report)
        self.assertIn("| 知识点@A | 95/100 = 95.0% | `eligible` |", report)
        self.assertIn("| 知识点@B | 60/100 = 60.0% | `hold` |", report)
        self.assertEqual(report.count("知识点@A"), 1)
        self.assertEqual(report.count("知识点@B"), 1)

    def test_cli_writes_summary_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            manifest = directory / "manifest.json"
            mentor_report = directory / "verification_report.md"
            output = directory / "summary.md"
            manifest.write_text(
                json.dumps({"candidates": [{"legacy_label": "知识点@A"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            mentor_report.write_text(
                "| 标签 | 总数 | 匹配 | 不匹配 | 错误 | 匹配率 |\n"
                "|---|---:|---:|---:|---:|---:|\n"
                "| 知识点@A | 100 | 95 | 5 | 0 | 95.0% |\n",
                encoding="utf-8",
            )
            script = Path(__file__).resolve().parents[1] / "scripts" / "build_positive_candidate_yield_summary.py"
            command = [
                sys.executable, str(script), "--manifest", str(manifest), "--mentor-report", str(mentor_report),
                "--output", str(output),
            ]
            first = subprocess.run(command, capture_output=True, text=True, check=False)
            second = subprocess.run(command, capture_output=True, text=True, check=False)

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn('"candidate_labels": 1', first.stdout)
            self.assertTrue(output.is_file())
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("refusing to overwrite", second.stderr)


if __name__ == "__main__":
    unittest.main()
