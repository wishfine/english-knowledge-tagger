import json
from pathlib import Path
import tempfile
import unittest


try:
    from english_knowledge_tagger.conversion_relation_packet import build_conversion_relation_packet
except ImportError:
    build_conversion_relation_packet = None


class ConversionRelationPacketTests(unittest.TestCase):
    def test_builds_clean_context_and_retains_audit_identity(self):
        self.assertTrue(callable(build_conversion_relation_packet))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = directory / "materialized.jsonl"
            output = directory / "packet.jsonl"
            source.write_text(json.dumps({
                "question_id": "q-1", "parent_id": "p-1", "is_sub_question": False,
                "input": "题型结构为：单选题\n题型名称为：选择题\n题目题干：direct 变为 director。\n题目答案：director",
                "llm_match": True,
            }, ensure_ascii=False) + "\n", encoding="utf-8")

            report = build_conversion_relation_packet(source, output_path=output)
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(report["packet_records"], 1)
        self.assertEqual(rows[0]["question_id"], "q-1")
        self.assertEqual(rows[0]["route_key"], {
            "scope": "parent", "declared_type_structure": "单选题", "declared_type_name": "选择题",
        })
        self.assertIn("direct 变为 director", rows[0]["question_context"])
        self.assertNotIn("题型结构为：", rows[0]["question_context"])
        self.assertNotIn("llm_match", rows[0])

