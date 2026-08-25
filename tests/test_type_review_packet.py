import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

try:
    from english_knowledge_tagger.type_review_packet import build_type_review_packet
except ModuleNotFoundError:
    build_type_review_packet = None


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


class TypeReviewPacketTests(unittest.TestCase):
    def test_packet_stratifies_by_exact_route_and_hides_legacy_labels_by_default(self):
        self.assertTrue(callable(build_type_review_packet), "build_type_review_packet must be implemented")
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = write_jsonl(
                directory / "source.jsonl",
                [
                    {
                        "question_id": "parent-1",
                        "parent_id": "parent-1",
                        "is_sub_question": False,
                        "input": "题型结构为：复合题\n题型名称为：阅读理解\n题目题干：parent",
                        "output": "题型@阅读理解@阅读选择@细节理解",
                    },
                    {
                        "question_id": "child-1",
                        "parent_id": "parent-1",
                        "is_sub_question": True,
                        "input": "题型结构为：复合题\n题型名称为：阅读理解\n当前小题题干：child",
                        "output": "题型@阅读理解@阅读选择@细节理解",
                    },
                    {
                        "question_id": "child-2",
                        "parent_id": "parent-1",
                        "is_sub_question": True,
                        "input": "题型结构为：复合题\n题型名称为：阅读理解\n当前小题题干：other",
                        "output": "题型@阅读理解@阅读选择@主旨大意@篇章主旨",
                    },
                ],
            )
            output = directory / "packet.jsonl"

            report = build_type_review_packet(source, output_path=output, per_route=1)
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(report["records"], 2)
        self.assertEqual({row["route_key"]["scope"] for row in rows}, {"parent", "child"})
        self.assertNotIn("legacy_type_labels", rows[0])
        self.assertIn("question_context", rows[0])
        self.assertEqual(report["route_counts"], {"child|复合题|阅读理解": 2, "parent|复合题|阅读理解": 1})

    def test_packet_can_include_legacy_type_evidence_when_explicitly_requested(self):
        self.assertTrue(callable(build_type_review_packet), "build_type_review_packet must be implemented")
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = write_jsonl(
                directory / "source.jsonl",
                [
                    {
                        "question_id": "child-1",
                        "parent_id": "parent-1",
                        "is_sub_question": True,
                        "input": "题型结构为：复合题\n题型名称为：阅读理解\n当前小题题干：child",
                        "output": "题型@阅读理解@阅读选择@细节理解",
                    }
                ],
            )
            output = directory / "packet.jsonl"

            build_type_review_packet(
                source,
                output_path=output,
                per_route=1,
                include_legacy_labels=True,
            )
            row = json.loads(output.read_text(encoding="utf-8").splitlines()[0])

        self.assertEqual(row["legacy_type_labels"], ["题型->阅读理解->阅读选择->细节理解"])

    def test_packet_cli_writes_a_blind_packet_and_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = write_jsonl(
                directory / "source.jsonl",
                [
                    {
                        "question_id": "child-1",
                        "parent_id": "parent-1",
                        "is_sub_question": True,
                        "input": "题型结构为：复合题\n题型名称为：阅读理解\n当前小题题干：child",
                        "output": "题型@阅读理解@阅读选择@细节理解",
                    }
                ],
            )
            output = directory / "packet.jsonl"
            report = directory / "report.json"
            script = Path(__file__).resolve().parents[1] / "scripts" / "sample_type_review_packet.py"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--report",
                    str(report),
                    "--per-route",
                    "1",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["records"], 1)
            row = json.loads(output.read_text(encoding="utf-8").splitlines()[0])
            self.assertNotIn("legacy_type_labels", row)


if __name__ == "__main__":
    unittest.main()
