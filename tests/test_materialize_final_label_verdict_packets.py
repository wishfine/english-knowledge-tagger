import json
from pathlib import Path
import tempfile
import unittest

from english_knowledge_tagger.materialize_final_label_verdict_packets import (
    materialize_final_label_verdict_packets,
)


PREDICATE = "知识点@语法句法@句子成分@谓语"
SUBJECT = "知识点@语法句法@句子成分@主语"


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


class MaterializeFinalLabelVerdictPacketsTests(unittest.TestCase):
    def test_joins_all_verdicts_to_v3_and_routes_labels(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            packets = root / "packets"
            evidence = root / "evidence"
            processed = root / "processed"
            issue = root / "issue"
            packets.mkdir()
            evidence.mkdir()
            packet_pred = packets / "002-predicate.final.packet.jsonl"
            packet_sub = packets / "001-subject.final.packet.jsonl"
            _write(packet_pred, [{"verify_label": PREDICATE}])
            _write(packet_sub, [{"verify_label": SUBJECT}])
            _write(evidence / "002-predicate.evidence.jsonl", [
                {"review_id": "p1", "question_id": "q1", "parent_id": "p1", "is_sub_question": False,
                 "legacy_label": PREDICATE, "canonical_label": "知识点->句法->句子成分->谓语",
                 "status": "candidate", "llm_match": True, "confidence": "high", "reason": "keep"},
            ])
            _write(evidence / "001-subject.evidence.jsonl", [
                {"review_id": "s1", "question_id": "q2", "parent_id": "p2", "is_sub_question": False,
                 "legacy_label": SUBJECT, "canonical_label": "知识点->句法->句子成分->主语",
                 "status": "candidate", "llm_match": False, "confidence": "medium", "reason": "remove"},
            ])
            source = root / "v3.jsonl"
            _write(source, [
                {"question_id": "q1", "parent_id": "p1", "is_sub_question": False,
                 "input": "v3 predicate", "output": PREDICATE},
                {"question_id": "q2", "parent_id": "p2", "is_sub_question": False,
                 "input": "v3 subject", "output": SUBJECT},
            ])
            report_path = root / "report.json"
            report = materialize_final_label_verdict_packets(
                packet_dir=packets,
                evidence_dir=evidence,
                source_path=source,
                processed_dir=processed,
                issue_dir=issue,
                processed_labels=(PREDICATE,),
                issue_labels=(SUBJECT,),
                report_path=report_path,
            )

            pred_file = next(processed.glob("劣质-*.jsonl"))
            sub_file = next(issue.glob("劣质-*.jsonl"))
            pred = json.loads(pred_file.read_text(encoding="utf-8").strip())
            sub = json.loads(sub_file.read_text(encoding="utf-8").strip())

        self.assertEqual(report["total_evidence_records"], 2)
        self.assertEqual(report["total_joined_records"], 2)
        self.assertEqual(pred["llm_match"], True)
        self.assertEqual(pred["source_version"], "v3")
        self.assertEqual(pred["ds_source_version"], "v2")
        self.assertEqual(pred["source_record"]["input"], "v3 predicate")
        self.assertEqual(sub["llm_match"], False)
        self.assertTrue(pred_file.name.startswith("劣质-002-"))
        self.assertTrue(sub_file.name.startswith("劣质-001-"))


if __name__ == "__main__":
    unittest.main()
