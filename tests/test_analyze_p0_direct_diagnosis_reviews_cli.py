import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "analyze_p0_direct_diagnosis_reviews.py"


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


class AnalyzeP0DirectDiagnosisReviewsCliTests(unittest.TestCase):
    def test_writes_analysis_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            review_id = "p0:test:true"
            common = {
                "schema_version": "p0-direct-diagnosis-blind-review-v1",
                "review_id": review_id,
                "legacy_label": "知识点@语法词法@动词@实义动词@及物动词",
                "active_taxonomy_label": "知识点->词法->动词->实义动词->及物动词",
            }
            true_path = _write_jsonl(directory / "true.jsonl", [common])
            false_path = _write_jsonl(directory / "false.jsonl", [])
            audit_path = _write_jsonl(
                directory / "audit.jsonl",
                [
                    {
                        "schema_version": "p0-direct-diagnosis-audit-v1",
                        "review_id": review_id,
                        "review_set": "true",
                        "selection_stratum": "direct_true_all",
                        "route_key": {
                            "scope": "parent",
                            "declared_type_structure": "单选题",
                            "declared_type_name": "选择题",
                        },
                        "suggestion_family": None,
                    }
                ],
            )
            results_path = _write_jsonl(
                directory / "reviews.jsonl",
                [{"review_id": review_id, "decision": "keep", "reason": "结构明确"}],
            )
            output_path = directory / "report.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--true-packet",
                    str(true_path),
                    "--false-packet",
                    str(false_path),
                    "--audit-index",
                    str(audit_path),
                    "--reviewer-results",
                    str(results_path),
                    "--output",
                    str(output_path),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(report["release_status"], "silver_candidate_true_set_only")
        self.assertEqual(report["reviewed_records"], 1)


if __name__ == "__main__":
    unittest.main()
