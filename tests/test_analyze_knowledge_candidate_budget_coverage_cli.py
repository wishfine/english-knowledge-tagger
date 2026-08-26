import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


HISTORICAL = "知识点->词法->介词->其他介词"
SIBLING = "知识点->词法->介词->时间介词"


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def packet_row(*, alternatives: list[dict[str, str]]) -> dict[str, object]:
    return {
        "review_id": "kp-validation:q-1:other-preposition",
        "source_line": 18,
        "question_id": "q-1",
        "parent_id": "p-1",
        "canonical_label": HISTORICAL,
        "legacy_label": "知识点@词法@介词@其他介词",
        "target_definition": "旧标签释义",
        "alternative_labels": alternatives,
    }


class AnalyzeKnowledgeCandidateBudgetCoverageCliTests(unittest.TestCase):
    def test_cli_writes_non_mutating_multi_packet_coverage_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            k4 = directory / "k4.jsonl"
            k12 = directory / "k12.jsonl"
            gold = directory / "gold.jsonl"
            output = directory / "report.json"
            write_jsonl(k4, [packet_row(alternatives=[])])
            write_jsonl(
                k12,
                [
                    packet_row(
                        alternatives=[
                            {"label": SIBLING, "source": "sibling", "definition": "时间介词"}
                        ]
                    )
                ],
            )
            write_jsonl(
                gold,
                [
                    {
                        "source_line": 18,
                        "question_id": "q-1",
                        "parent_id": "p-1",
                        "historical_label": HISTORICAL,
                        "gold_labels": [SIBLING],
                        "adjudication_status": "approved",
                    }
                ],
            )
            script = (
                Path(__file__).resolve().parents[1]
                / "scripts"
                / "analyze_knowledge_candidate_budget_coverage.py"
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--packet",
                    f"k4={k4}",
                    "--packet",
                    f"k12={k12}",
                    "--gold",
                    str(gold),
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["matched_packet_rows"], 1)
            self.assertEqual(
                report["packets"]["k12"]["primary_correction_label_coverage"]["counts"]["sibling"],
                1,
            )
            self.assertEqual(k4.read_text(encoding="utf-8").count("review_id"), 1)
            self.assertEqual(k12.read_text(encoding="utf-8").count("review_id"), 1)


if __name__ == "__main__":
    unittest.main()
