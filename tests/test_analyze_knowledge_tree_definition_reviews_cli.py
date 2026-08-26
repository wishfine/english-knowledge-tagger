import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class AnalyzeKnowledgeTreeDefinitionReviewsCliTests(unittest.TestCase):
    def test_cli_writes_mapping_based_review_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            mapping = directory / "mapping.jsonl"
            reviews = directory / "reviews.jsonl"
            output = directory / "report.json"
            mapping.write_text(
                json.dumps(
                    {
                        "review_id": "r-1",
                        "option_a_mode": "none",
                        "option_a_label": "知识点->词法->介词->时间介词",
                        "option_b_mode": "compressed",
                        "option_b_label": "知识点->词法->介词->其他介词",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            reviews.write_text(
                json.dumps({"review_id": "r-1", "review_decision": "B"}, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
            )
            script = (
                Path(__file__).resolve().parents[1]
                / "scripts"
                / "analyze_knowledge_tree_definition_reviews.py"
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--mapping",
                    str(mapping),
                    "--reviews",
                    str(reviews),
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["resolved_reviews"], 1)
            self.assertEqual(report["by_mode"][0]["mode"], "compressed")
            self.assertEqual(report["by_mode"][0]["correct_option_assignments"], 1)


if __name__ == "__main__":
    unittest.main()
