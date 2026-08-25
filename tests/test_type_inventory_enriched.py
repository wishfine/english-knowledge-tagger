import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from english_knowledge_tagger.type_inventory_enriched import inventory_sft_jsonl_enriched


def write_jsonl(directory: Path, rows: list[dict[str, object]]) -> Path:
    path = directory / "records.jsonl"
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


class EnrichedTypeInventoryTests(unittest.TestCase):
    def test_inventory_reports_type_cardinality_combinations_and_stratified_samples(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            progress_updates = []
            source = write_jsonl(
                Path(temp_dir),
                [
                    {
                        "question_id": "q-1",
                        "is_sub_question": False,
                        "input": "题型结构为：补全题\n题型名称为：补全对话",
                        "output": "题型@特殊题型@补全对话;知识点@交际用语",
                    },
                    {
                        "question_id": "q-2",
                        "is_sub_question": False,
                        "input": "题型结构为：补全题\n题型名称为：补全对话",
                        "output": "题型@特殊题型@补全对话;题型@特殊题型@情景运用",
                    },
                    {
                        "question_id": "q-3",
                        "is_sub_question": False,
                        "input": "题型结构为：补全题\n题型名称为：补全对话",
                        "output": "知识点@交际用语",
                    },
                    {
                        "question_id": "q-4",
                        "is_sub_question": True,
                        "input": "题型结构为：复合题\n题型名称为：阅读理解",
                        "output": "题型@阅读理解@阅读选择@细节理解",
                    },
                ],
            )

            report = inventory_sft_jsonl_enriched(
                source,
                sample_per_label=1,
                sample_unlabeled=1,
                progress_every=2,
                progress_callback=progress_updates.append,
            )
            source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()

        self.assertEqual(report["schema_version"], "type-inventory-v2")
        self.assertEqual(report["valid_records"], 4)
        self.assertEqual(progress_updates, [2, 4])
        self.assertEqual(report["scope_counts"], {"parent": 3, "child": 1, "unknown": 0})
        self.assertEqual(report["source_sha256"], source_sha256)

        parent = next(row for row in report["rows"] if row["scope"] == "parent")
        self.assertEqual(parent["type_label_count_distribution"], {"0": 1, "1": 1, "2": 1})
        self.assertEqual(parent["unlabeled_record_count"], 1)
        self.assertEqual(
            parent["historical_type_labels"],
            {"题型@特殊题型@情景运用": 1, "题型@特殊题型@补全对话": 2},
        )
        self.assertEqual(
            parent["type_label_combination_counts"],
            [
                {"labels": [], "record_count": 1},
                {"labels": ["题型@特殊题型@情景运用", "题型@特殊题型@补全对话"], "record_count": 1},
                {"labels": ["题型@特殊题型@补全对话"], "record_count": 1},
            ],
        )
        self.assertEqual(
            parent["samples_by_historical_label"],
            {"题型@特殊题型@情景运用": ["q-2"], "题型@特殊题型@补全对话": ["q-1"]},
        )
        self.assertEqual(parent["unlabeled_sample_question_ids"], ["q-3"])

    def test_cli_writes_new_outputs_and_refuses_to_overwrite_them(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = write_jsonl(
                directory,
                [
                    {
                        "question_id": "q-1",
                        "is_sub_question": False,
                        "input": "题型结构为：补全题\n题型名称为：补全对话",
                        "output": "题型@特殊题型@补全对话",
                    }
                ],
            )
            output_json = directory / "enriched.json"
            output_csv = directory / "enriched.policy.csv"
            script = Path(__file__).resolve().parents[1] / "scripts" / "inventory_question_types_enriched.py"
            command = [
                sys.executable,
                str(script),
                "--input",
                str(source),
                "--output-json",
                str(output_json),
                "--output-csv",
                str(output_csv),
                "--sample-per-label",
                "2",
                "--sample-unlabeled",
                "2",
            ]

            completed = subprocess.run(command, check=False, capture_output=True, text=True)
            repeated = subprocess.run(command, check=False, capture_output=True, text=True)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertIn("refusing to overwrite", repeated.stderr)
            self.assertEqual(json.loads(output_json.read_text(encoding="utf-8"))["schema_version"], "type-inventory-v2")
            with output_csv.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["type_policy_status"], "unmapped")
            self.assertIn("type_label_count_distribution", rows[0])
            self.assertIn("policy_kind", rows[0])


if __name__ == "__main__":
    unittest.main()
