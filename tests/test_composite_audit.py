import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

try:
    from english_knowledge_tagger.composite_audit import audit_jsonl
except ModuleNotFoundError:
    audit_jsonl = None


def write_jsonl(directory: Path, rows: list[dict[str, object]]) -> Path:
    path = directory / "records.jsonl"
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


class CompositeAuditTests(unittest.TestCase):
    def test_audit_reports_parent_child_label_relations_and_discourse_removal(self):
        self.assertTrue(callable(audit_jsonl), "audit_jsonl must be implemented")
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = write_jsonl(
                directory,
                [
                    {
                        "question_id": "p-1",
                        "parent_id": "p-1",
                        "solve_func_ids": ["genre", "kp-1"],
                        "question_type_ids": ["reading"],
                    },
                    {
                        "question_id": "p-2",
                        "parent_id": "p-2",
                        "solve_func_ids": ["kp-3"],
                        "question_type_ids": ["grammar"],
                    },
                    {
                        "question_id": "c-1",
                        "parent_id": "p-1",
                        "solve_func_ids": ["genre", "kp-1"],
                        "question_type_ids": ["reading"],
                    },
                    {
                        "question_id": "c-2",
                        "parent_id": "p-1",
                        "solve_func_ids": ["genre"],
                        "question_type_ids": ["reading-question"],
                    },
                    {
                        "question_id": "c-3",
                        "parent_id": "p-1",
                        "solve_func_ids": ["kp-2"],
                        "question_type_ids": ["grammar"],
                    },
                ],
            )

            report = audit_jsonl(
                source,
                index_path=directory / "audit.sqlite3",
                discourse_knowledge_ids={"genre"},
            )

        self.assertEqual(report["records"], {"valid": 5, "parents": 2, "children": 3, "missing_ids": 0})
        self.assertEqual(
            report["parent_groups"],
            {
                "parents_with_children": 1,
                "parents_without_children": 1,
                "orphan_children": 0,
                "child_count_distribution": {"3": 1},
                "child_count_summary": {
                    "mean": 3.0,
                    "stddev": 0.0,
                    "median": 3.0,
                    "min": 3,
                    "max": 3,
                    "p25": 3.0,
                    "p50": 3.0,
                    "p75": 3.0,
                    "p90": 3.0,
                    "p95": 3.0,
                    "p99": 3.0,
                },
            },
        )
        self.assertEqual(
            report["knowledge_parent_child"],
            {
                "equal": 1,
                "child_empty": 0,
                "subset_not_equal": 1,
                "child_contains_parent_external": 1,
                "parent_missing": 0,
            },
        )
        self.assertEqual(
            report["after_discourse_removal"],
            {"children_with_non_discourse_knowledge": 2, "children_with_only_discourse_knowledge": 1},
        )
        self.assertEqual(report["label_cardinality"]["knowledge"]["child"], {"1": 2, "2": 1})

    def test_audit_reports_orphan_children_separately_from_label_mismatch(self):
        self.assertTrue(callable(audit_jsonl), "audit_jsonl must be implemented")
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = write_jsonl(
                directory,
                [
                    {
                        "question_id": "child-orphan",
                        "parent_id": "missing-parent",
                        "solve_func_ids": [1],
                        "question_type_ids": [],
                    },
                    {"question_id": "", "parent_id": "", "solve_func_ids": [], "question_type_ids": []},
                ],
            )

            report = audit_jsonl(source, index_path=directory / "audit.sqlite3")

        self.assertEqual(report["records"], {"valid": 2, "parents": 0, "children": 1, "missing_ids": 1})
        self.assertEqual(report["parent_groups"]["orphan_children"], 1)
        self.assertEqual(report["knowledge_parent_child"]["parent_missing"], 1)

    def test_audit_cli_writes_report_and_persistent_index(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = write_jsonl(
                directory,
                [
                    {
                        "question_id": "p-1",
                        "parent_id": "p-1",
                        "solve_func_ids": [1],
                        "question_type_ids": [2],
                    }
                ],
            )
            report_path = directory / "report.json"
            index_path = directory / "audit.sqlite3"
            script = Path(__file__).resolve().parents[1] / "scripts" / "audit_composites.py"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--input",
                    str(source),
                    "--output",
                    str(report_path),
                    "--index",
                    str(index_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(index_path.is_file())
            self.assertEqual(json.loads(report_path.read_text(encoding="utf-8"))["records"]["parents"], 1)
