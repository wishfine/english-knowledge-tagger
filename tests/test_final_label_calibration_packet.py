import json
from pathlib import Path
import tempfile
import unittest


try:
    from english_knowledge_tagger.final_label_calibration_packet import (
        build_final_label_calibration_packet,
    )
except ImportError:
    build_final_label_calibration_packet = None


LABEL = "知识点@词汇@词汇辨析@名词（短语）辨析"
OTHER_LABEL = "知识点@词汇@固定搭配/句型"


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def final_packet_row(question_id: str, *, label: str = LABEL) -> dict[str, object]:
    return {
        "schema_version": "final-label-discriminator-packet-v1",
        "review_id": f"final-label-discriminator-v1:{question_id}:{label}",
        "source_line": int(question_id.removeprefix("q")),
        "question_id": question_id,
        "parent_id": question_id,
        "is_sub_question": False,
        "route_key": {
            "scope": "parent",
            "declared_type_structure": "单选题",
            "declared_type_name": "选择题",
        },
        "verify_label": label,
        "question_text": f"题目题干：{question_id}",
    }


class FinalLabelCalibrationPacketTests(unittest.TestCase):
    def test_selects_existing_human_reviews_that_are_route_eligible(self):
        self.assertTrue(callable(build_final_label_calibration_packet))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            final_packet = write_jsonl(
                directory / "final.packet.jsonl",
                [final_packet_row("q1"), final_packet_row("q2"), final_packet_row("q4", label=OTHER_LABEL)],
            )
            review_sample = write_jsonl(
                directory / "review-sample.jsonl",
                [
                    {
                        "verify_label": LABEL,
                        "question_id": "q2",
                        "review_id": "manual-true-2",
                        "review_stratum": "llm_says_historical_label_correct",
                    },
                    {
                        "verify_label": LABEL,
                        "question_id": "q3",
                        "review_id": "manual-false-3",
                        "review_stratum": "llm_says_historical_label_incorrect",
                    },
                    {
                        "verify_label": LABEL,
                        "question_id": "q1",
                        "review_id": "manual-true-1",
                        "review_stratum": "llm_says_historical_label_correct",
                    },
                    {"verify_label": OTHER_LABEL, "question_id": "q4", "review_id": "other-label"},
                ],
            )
            output = directory / "calibration.packet.jsonl"

            report = build_final_label_calibration_packet(
                final_packet,
                review_sample_path=review_sample,
                verify_label=LABEL,
                output_path=output,
            )
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        self.assertEqual([row["question_id"] for row in rows], ["q2", "q1"])
        self.assertEqual(rows[0]["calibration_source_review_id"], "manual-true-2")
        self.assertEqual(rows[0]["calibration_review_stratum"], "llm_says_historical_label_correct")
        self.assertEqual(report["review_sample_records_for_label"], 3)
        self.assertEqual(report["eligible_calibration_records"], 2)
        self.assertEqual(report["missing_from_final_packet_question_ids"], ["q3"])


if __name__ == "__main__":
    unittest.main()
