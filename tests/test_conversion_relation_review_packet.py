import json
from pathlib import Path
import tempfile
import unittest


try:
    from english_knowledge_tagger.conversion_relation_review_packet import build_conversion_relation_review_packet
except ImportError:
    build_conversion_relation_review_packet = None


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


class ConversionRelationReviewPacketTests(unittest.TestCase):
    def test_keeps_all_conversion_and_stratifies_other_relations(self):
        self.assertTrue(callable(build_conversion_relation_review_packet))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            packet, evidence, output = directory / "packet.jsonl", directory / "evidence.jsonl", directory / "review.jsonl"
            rows = []
            verdicts = []
            for index, relation in enumerate(("conversion", "conversion", "derivation", "derivation", "inflection", "lexical_or_other", "insufficient"), 1):
                qid = f"q-{index}"
                rows.append({"task_id": f"task-{index}", "question_id": qid, "parent_id": f"p-{index}", "route_key": {"scope": "parent", "declared_type_structure": "单选题", "declared_type_name": "选择题"}, "question_context": f"题干：{qid}"})
                verdicts.append({"task_id": f"task-{index}", "question_id": qid, "relation": relation, "confidence": "high", "evidence": f"e-{index}"})
            write_jsonl(packet, rows)
            write_jsonl(evidence, verdicts)

            report = build_conversion_relation_review_packet(packet, evidence_path=evidence, output_path=output, non_conversion_quota=1, seed="test")
            reviewed = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(report["selected_by_relation"], {"conversion": 2, "derivation": 1, "inflection": 1, "lexical_or_other": 1, "insufficient": 1})
        self.assertEqual(len(reviewed), 6)
        self.assertNotIn("historical", json.dumps(reviewed, ensure_ascii=False))
        self.assertEqual({row["model_relation"] for row in reviewed}, {"conversion", "derivation", "inflection", "lexical_or_other", "insufficient"})

