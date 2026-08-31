import json
from pathlib import Path
import tempfile
import unittest

from english_knowledge_tagger.root_tree_tasks import build_root_tree_tasks


class RootTreeTasksTests(unittest.TestCase):
    def test_only_atomic_gate_outcomes_become_whole_taxonomy_tasks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            packet, evidence, output = directory / "packet.jsonl", directory / "gate.jsonl", directory / "tree.jsonl"
            packet.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in [
                {"task_id":"a", "source_line":1, "question_id":"q1", "parent_id":"p1", "route_key":{}, "question_context":"题干：x"},
                {"task_id":"b", "source_line":2, "question_id":"q2", "parent_id":"p2", "route_key":{}, "question_context":"题干：y"},
            ]) + "\n", encoding="utf-8")
            evidence.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in [
                {"task_id":"a", "task_shape":"atomic_knowledge", "evidence":"one"},
                {"task_id":"b", "task_shape":"lexical_or_other", "evidence":"two"},
            ]) + "\n", encoding="utf-8")
            report = build_root_tree_tasks(packet, evidence, output_path=output)
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(report["tree_tasks"], 1)
        self.assertEqual(rows[0]["allowed_knowledge_prefixes"], ["知识点"])
        self.assertEqual(rows[0]["question_id"], "q1")

