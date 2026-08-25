import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

try:
    from english_knowledge_tagger.type_inventory import inventory_sft_jsonl
except ModuleNotFoundError:
    inventory_sft_jsonl = None


def write_jsonl(directory: Path, rows: list[dict[str, object]]) -> Path:
    path = directory / "records.jsonl"
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


class TypeInventoryTests(unittest.TestCase):
    def test_inventory_separates_parent_and_child_with_declared_type_and_label_state(self):
        self.assertTrue(callable(inventory_sft_jsonl), "inventory_sft_jsonl must be implemented")
        with tempfile.TemporaryDirectory() as temp_dir:
            source = write_jsonl(
                Path(temp_dir),
                [
                    {
                        "question_id": "parent-1",
                        "is_sub_question": False,
                        "input": "题型结构为：阅读理解\n题型名称为：阅读理解\n题目题干：...",
                        "output": "题型@阅读理解@阅读选择;知识点@语篇体裁@记叙文",
                    },
                    {
                        "question_id": "child-1",
                        "is_sub_question": True,
                        "input": "题型结构为：阅读理解\n题型名称为：阅读理解\n当前小题题干：...",
                        "output": "题型@阅读理解@阅读选择@主旨",
                    },
                    {
                        "question_id": "child-2",
                        "is_sub_question": True,
                        "input": "题型结构为：填空题\n题型名称为：语法填空\n当前小题题干：...",
                        "output": "题型@填空题型@完成句子;知识点@语法词法@时态@一般过去时",
                    },
                ],
            )

            report = inventory_sft_jsonl(source, sample_limit=2)

        rows = {
            (row["scope"], row["declared_type_structure"], row["declared_type_name"]): row
            for row in report["rows"]
        }
        reading_child = rows[("child", "阅读理解", "阅读理解")]
        grammar_child = rows[("child", "填空题", "语法填空")]
        reading_parent = rows[("parent", "阅读理解", "阅读理解")]

        self.assertEqual(reading_child["record_count"], 1)
        self.assertEqual(reading_child["knowledge_label_count_distribution"], {"0": 1})
        self.assertEqual(reading_child["historical_type_labels"], {"题型@阅读理解@阅读选择@主旨": 1})
        self.assertEqual(grammar_child["knowledge_label_count_distribution"], {"1": 1})
        self.assertEqual(reading_parent["knowledge_label_count_distribution"], {"1": 1})
        self.assertEqual(report["scope_counts"], {"parent": 1, "child": 2, "unknown": 0})

    def test_inventory_cli_writes_json_and_mapping_csv(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = write_jsonl(
                directory,
                [
                    {
                        "question_id": "child-1",
                        "is_sub_question": True,
                        "input": "题型结构为：填空题\n题型名称为：语法填空\n当前小题题干：...",
                        "output": "题型@填空题型@完成句子;知识点@语法词法@时态@一般过去时",
                    }
                ],
            )
            output_json = directory / "inventory.json"
            output_csv = directory / "policy_mapping.csv"
            script = Path(__file__).resolve().parents[1] / "scripts" / "inventory_question_types.py"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--input",
                    str(source),
                    "--output-json",
                    str(output_json),
                    "--output-csv",
                    str(output_csv),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(output_json.read_text(encoding="utf-8"))["rows"][0]["scope"], "child")
            self.assertIn("policy_status", output_csv.read_text(encoding="utf-8").splitlines()[0])
