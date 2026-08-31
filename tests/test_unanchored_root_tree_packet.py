import json
from pathlib import Path
import tempfile
import unittest

from english_knowledge_tagger.unanchored_root_tree_packet import build_unanchored_root_tree_packet


class UnanchoredRootTreePacketTests(unittest.TestCase):
    def test_all_rows_enter_root_tree_without_historical_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source, output = directory / "packet.jsonl", directory / "tree.jsonl"
            source.write_text(json.dumps({
                "schema_version": "conversion-relation-packet-v1",
                "task_id": "conversion-relation:q1", "source_line": 1,
                "question_id": "q1", "parent_id": "p1", "route_key": {},
                "question_context": "题干：water 作动词。", "llm_match": True,
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            report = build_unanchored_root_tree_packet(source, output_path=output)
            row = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report["tree_tasks"], 1)
        self.assertEqual(row["allowed_knowledge_prefixes"], ["知识点"])
        self.assertEqual(row["question_id"], "q1")
        self.assertNotIn("llm_match", row)
        self.assertNotIn("知识点@词汇@构词法@转化法", json.dumps(row, ensure_ascii=False))

