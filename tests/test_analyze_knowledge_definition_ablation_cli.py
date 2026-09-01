import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class AnalyzeKnowledgeDefinitionAblationCliTests(unittest.TestCase):
    def test_cli_writes_json_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "baseline.jsonl"
            override = root / "override.jsonl"
            baseline.write_text(
                json.dumps(
                    {
                        "task_id": "t1",
                        "status": "tree_candidate",
                        "candidate_label": "知识点->词汇->构词法->转化法",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            override.write_text(
                json.dumps(
                    {
                        "task_id": "t1",
                        "status": "tree_candidate",
                        "candidate_label": "知识点->词汇->构词法->派生法（词根词缀）",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            output = root / "summary.json"
            script = Path(__file__).resolve().parents[1] / "scripts" / "analyze_knowledge_definition_ablation.py"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--baseline",
                    str(baseline),
                    "--override",
                    str(override),
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["common_tasks"], 1)
            self.assertEqual(report["candidate_changes"], 1)


if __name__ == "__main__":
    unittest.main()
