import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class DynamicLeafAnalysisCliTests(unittest.TestCase):
    def test_coverage_and_candidate_verifier_and_final_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = Path(__file__).resolve().parents[1]
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
                for label, definition in (
                    ("知识点->词汇->构词法->转化法", "同形转化"),
                    ("知识点->词汇->构词法->派生法", "词缀派生"),
                ):
                    writer.writerow(
                        {
                            "末级知识点": label,
                            "打标解读（标绿的标签，新题不再打）": definition,
                            "大模型压缩+人工微调的释义": definition,
                        }
                    )
            ambiguity = root / "ambiguity.json"
            ambiguity.write_text(
                json.dumps(
                    {
                        "labels": [
                            {
                                "canonical_label": "知识点->词汇->构词法->转化法",
                                "confusion_neighbors": [
                                    {"canonical_label": "知识点->词汇->构词法->派生法", "count": 5}
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            corrections = root / "corrections.jsonl"
            corrections.write_text(
                json.dumps(
                    {
                        "schema_version": "teacher-subquestion-gold-correction-v1",
                        "question_id": "q1",
                        "historical_label": "知识点->词汇->构词法->转化法",
                        "gold_labels": ["知识点->词汇->构词法->派生法"],
                        "route_key": {"scope": "child"},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            coverage = root / "coverage.json"
            covered = subprocess.run(
                [
                    sys.executable,
                    str(project / "scripts" / "analyze_dynamic_leaf_coverage.py"),
                    "--teacher-csv",
                    str(teacher),
                    "--corrections",
                    str(corrections),
                    "--ambiguity-manifest",
                    str(ambiguity),
                    "--output",
                    str(coverage),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(covered.returncode, 0, covered.stderr)
            self.assertEqual(
                json.loads(coverage.read_text(encoding="utf-8"))["strategies"]["dynamic_top4"]["covered_records"],
                1,
            )

            tasks = root / "tasks.jsonl"
            task = {
                "schema_version": "dynamic-leaf-task-v1",
                "review_id": "dynamic:q1",
                "question_id": "q1",
                "parent_id": "q1",
                "question_text": "direct变为director",
                "route_key": {"scope": "parent"},
                "pseudo_gold_decision": "remove",
                "teacher_gold_labels": ["知识点->词汇->构词法->派生法"],
            }
            tasks.write_text(json.dumps(task, ensure_ascii=False) + "\n", encoding="utf-8")
            resolver = root / "resolver.jsonl"
            resolver.write_text(
                json.dumps(
                    {
                        "review_id": "dynamic:q1",
                        "status": "candidate",
                        "candidate_label": "知识点->词汇->构词法->派生法",
                        "call_count": 1,
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            verifier_packet = root / "verifier.packet.jsonl"
            built = subprocess.run(
                [
                    sys.executable,
                    str(project / "scripts" / "build_dynamic_candidate_verifier_packet.py"),
                    "--tasks",
                    str(tasks),
                    "--resolver-run",
                    f"r1={resolver}",
                    "--resolver-run",
                    f"r2={resolver}",
                    "--resolver-run",
                    f"r3={resolver}",
                    "--teacher-csv",
                    str(teacher),
                    "--output",
                    str(verifier_packet),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(built.returncode, 0, built.stderr)
            verifier_row = json.loads(verifier_packet.read_text(encoding="utf-8"))
            self.assertEqual(verifier_row["source_review_id"], "dynamic:q1")

            verifier = root / "verifier.jsonl"
            verifier.write_text(
                json.dumps(
                    {
                        "source_review_id": "dynamic:q1",
                        "decision": "keep",
                        "confidence": "high",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            analysis = root / "analysis.json"
            analyzed = subprocess.run(
                [
                    sys.executable,
                    str(project / "scripts" / "analyze_dynamic_leaf_experiment.py"),
                    "--tasks",
                    str(tasks),
                    "--resolver-run",
                    f"r1={resolver}",
                    "--resolver-run",
                    f"r2={resolver}",
                    "--resolver-run",
                    f"r3={resolver}",
                    "--verifier-run",
                    f"v1={verifier}",
                    "--verifier-run",
                    f"v2={verifier}",
                    "--verifier-run",
                    f"v3={verifier}",
                    "--root-baseline-mean-calls",
                    "5",
                    "--output",
                    str(analysis),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(analyzed.returncode, 0, analyzed.stderr)
            decision = json.loads(analysis.read_text(encoding="utf-8"))["decisions"][0]
            self.assertEqual(decision["disposition"], "stable_relabel_candidate")


if __name__ == "__main__":
    unittest.main()
