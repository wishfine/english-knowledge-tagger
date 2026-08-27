import json
from pathlib import Path
import tempfile
import unittest

try:
    from english_knowledge_tagger.silver_post_sweep_sample import sample_silver_post_sweep
except ModuleNotFoundError:
    sample_silver_post_sweep = None


LABEL = "知识点@词汇@词汇辨析@名词（短语）辨析"


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def silver(question_id: str) -> dict[str, object]:
    return {
        "schema_version": "terminal-label-discriminator-evidence-v1",
        "review_id": f"mentor-direct-v1:{question_id}:noun",
        "question_id": question_id,
        "parent_id": "100",
        "source_line": int(question_id),
        "is_sub_question": False,
        "legacy_label": LABEL,
        "canonical_label": "知识点->词汇->词汇辨析->名词（短语）辨析",
        "llm_match": True,
        "status": "candidate",
        "model": "ds-v4-flash",
        "prompt_version": "mentor-direct-v1",
        "disposition": "silver_label_candidate",
    }


class SilverPostSweepSampleTests(unittest.TestCase):
    def test_sampler_excludes_initial_calibration_questions_and_uses_stable_seeded_selection(self):
        self.assertTrue(callable(sample_silver_post_sweep))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            evidence = write_jsonl(
                directory / "silver.jsonl", [silver("101"), silver("102"), silver("103")]
            )
            initial = write_jsonl(
                directory / "initial.jsonl", [{"question_id": "101", "verify_label": LABEL}]
            )
            output = directory / "sample.jsonl"
            report = sample_silver_post_sweep(
                evidence,
                verify_label=LABEL,
                output_path=output,
                sample_size=2,
                seed="20260827",
                exclude_jsonl_path=initial,
            )
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(report["available_records"], 3)
        self.assertEqual(report["excluded_records"], 1)
        self.assertEqual(report["selected_records"], 2)
        self.assertEqual({row["question_id"] for row in rows}, {"102", "103"})
        self.assertNotIn("101", {row["question_id"] for row in rows})

    def test_sampler_rejects_non_silver_or_wrong_label_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            wrong = silver("101")
            wrong["disposition"] = "hold"
            evidence = write_jsonl(directory / "silver.jsonl", [wrong])
            with self.assertRaisesRegex(ValueError, "must be silver_label_candidate"):
                sample_silver_post_sweep(
                    evidence,
                    verify_label=LABEL,
                    output_path=directory / "sample.jsonl",
                    sample_size=60,
                    seed="20260827",
                )


if __name__ == "__main__":
    unittest.main()
