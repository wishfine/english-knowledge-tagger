import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class BuildDefinitionAmbiguityProfileCliTests(unittest.TestCase):
    def test_writes_json_csv_and_summary_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            teacher = root / "teacher.csv"
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
                        "末级知识点": "知识点->词汇->构词法->转化法",
                        "打标解读（标绿的标签，新题不再打）": "只要出现词性变化都打。",
                        "大模型压缩+人工微调的释义": "同形词性变化。",
                    }
                )
            overrides = root / "overrides.json"
            overrides.write_text(
                json.dumps(
                    {
                        "schema_version": "knowledge-definition-overrides-v1",
                        "overrides": [
                            {
                                "label": "知识点->词汇->构词法->转化法",
                                "replacement_definition": "词形不变且答案依赖转换；不标派生。",
                                "status": "active_for_experiment",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            migration = root / "migration.json"
            migration.write_text(
                json.dumps(
                    {"schema_version": "knowledge-taxonomy-migration-v1", "rules": []},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            results = root / "results.jsonl"
            results.write_text(
                json.dumps(
                    {
                        "verify_label": "知识点@词汇@构词法@转化法",
                        "question_id": "q1",
                        "llm_match": True,
                        "llm_should_be": "正确",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            p0 = root / "p0.json"
            p0.write_text(
                json.dumps(
                    {
                        "schema_version": "p0-terminal-label-policy-v1",
                        "labels": ["知识点->词汇->构词法->转化法"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            output_json = root / "profile.json"
            output_csv = root / "profile.csv"
            report = root / "report.json"
            script = (
                Path(__file__).resolve().parents[1]
                / "scripts"
                / "build_definition_ambiguity_profile.py"
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--teacher-csv",
                    str(teacher),
                    "--definition-overrides",
                    str(overrides),
                    "--taxonomy-migration",
                    str(migration),
                    "--mentor-results",
                    str(results),
                    "--p0-policy",
                    str(p0),
                    "--output-json",
                    str(output_json),
                    "--output-csv",
                    str(output_csv),
                    "--report",
                    str(report),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(output_json.read_text(encoding="utf-8"))
            report_payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(payload["summary"]["knowledge_labels"], 1)
            self.assertEqual(report_payload, payload["summary"])
            with output_csv.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["canonical_label"], "知识点->词汇->构词法->转化法")


if __name__ == "__main__":
    unittest.main()
