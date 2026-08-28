import json
from pathlib import Path
import tempfile
import unittest


try:
    from english_knowledge_tagger.candidate_final_calibration_batch import (
        build_candidate_final_calibration_batch,
    )
except ImportError:
    build_candidate_final_calibration_batch = None


LABEL_A = "知识点@词汇@固定搭配/句型"
LABEL_B = "知识点@词法@代词@反身代词"
OUTSIDE_LABEL = "知识点@词法@冠词@定冠词"


def write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8"
    )
    return path


def final_packet_row(question_id: str, *, label: str) -> dict[str, object]:
    return {
        "schema_version": "final-label-discriminator-packet-v1",
        "review_id": f"final-label-discriminator-v1:{question_id}:{label}",
        "question_id": question_id,
        "parent_id": question_id,
        "source_line": int(question_id.removeprefix("q")),
        "is_sub_question": False,
        "route_key": {
            "scope": "parent",
            "declared_type_structure": "单选题",
            "declared_type_name": "选择题",
        },
        "verify_label": label,
        "question_text": f"题目题干：{question_id}",
        "source_packet_path": "packet",
        "source_path": "source",
        "label_definitions_path": "definitions",
        "label_definitions_sha256": "hash",
    }


class CandidateFinalCalibrationBatchTests(unittest.TestCase):
    def test_batch_joins_review_identities_and_reports_missing_packet_questions(self):
        self.assertTrue(callable(build_candidate_final_calibration_batch))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            packet_dir = directory / "packet-batch"
            packet_dir.mkdir()
            packet_a = write_jsonl(
                packet_dir / "a.final.packet.jsonl", [final_packet_row("q1", label=LABEL_A)]
            )
            packet_b = write_jsonl(
                packet_dir / "b.final.packet.jsonl", [final_packet_row("q2", label=LABEL_B)]
            )
            index = write_json(
                packet_dir / "batch.index.json",
                {
                    "schema_version": "candidate-final-packet-batch-v1",
                    "labels": {
                        LABEL_A: {
                            "canonical_label": "知识点->词汇->固定搭配/句型",
                            "packet_relative_path": packet_a.name,
                        },
                        LABEL_B: {
                            "canonical_label": "知识点->词法->代词->反身代词",
                            "packet_relative_path": packet_b.name,
                        },
                    },
                },
            )
            review_sample = write_jsonl(
                directory / "reviews.jsonl",
                [
                    {
                        "verify_label": LABEL_A,
                        "question_id": "q1",
                        "review_id": "manual-a-true",
                        "review_stratum": "historical_match_true",
                        "manual_verdict": "不得进入校准 packet",
                    },
                    {
                        "verify_label": LABEL_A,
                        "question_id": "q3",
                        "review_id": "manual-a-missing",
                        "review_stratum": "historical_match_false",
                    },
                    {
                        "verify_label": LABEL_B,
                        "question_id": "q2",
                        "review_id": "manual-b-true",
                        "review_stratum": "historical_match_true",
                    },
                    {
                        "verify_label": OUTSIDE_LABEL,
                        "question_id": "q4",
                        "review_id": "outside",
                    },
                ],
            )

            report = build_candidate_final_calibration_batch(
                packet_batch_index_path=index,
                review_sample_path=review_sample,
                output_dir=directory / "calibration-batch",
            )
            calibration_index = json.loads(
                (directory / "calibration-batch" / "calibration.index.json").read_text(
                    encoding="utf-8"
                )
            )
            packet_rows = [
                json.loads(line)
                for line in (
                    directory
                    / "calibration-batch"
                    / calibration_index["labels"][LABEL_A]["packet_relative_path"]
                )
                .read_text(encoding="utf-8")
                .splitlines()
            ]

        label_a = calibration_index["labels"][LABEL_A]
        self.assertEqual(report["candidate_labels"], 2)
        self.assertEqual(report["review_records_outside_packet_batch"], 1)
        self.assertEqual(label_a["review_sample_records_for_label"], 2)
        self.assertEqual(label_a["eligible_calibration_records"], 1)
        self.assertEqual(label_a["missing_from_final_packet_question_ids"], ["q3"])
        self.assertEqual(label_a["eligible_by_review_stratum"], {"historical_match_true": 1})
        self.assertEqual(label_a["missing_by_review_stratum"], {"historical_match_false": 1})
        self.assertEqual(packet_rows[0]["calibration_source_review_id"], "manual-a-true")
        self.assertNotIn("manual_verdict", packet_rows[0])
        self.assertNotIn("input", packet_rows[0])
        self.assertNotIn("output", packet_rows[0])


if __name__ == "__main__":
    unittest.main()
