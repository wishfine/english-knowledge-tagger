import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


LABEL = "知识点@词汇@词汇辨析@名词（短语）辨析"
CANONICAL = "知识点->词汇->词汇辨析->名词（短语）辨析"


def _source_row(question_id: str) -> dict[str, object]:
    return {
        "question_id": question_id,
        "parent_id": question_id,
        "is_sub_question": False,
        "input": f"题型结构为：单选题\n题型名称为：选择题\n题目题干：Choose {question_id}.",
        "output": LABEL,
    }


def _create_snapshot(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE evidence (
            question_id TEXT, parent_id TEXT, is_sub_question INTEGER,
            canonical_label TEXT, legacy_label TEXT, status TEXT,
            llm_match INTEGER, confidence TEXT, input_precheck_status TEXT,
            llm_input_status TEXT, review_id TEXT, source_path TEXT
        )
        """
    )
    for question_id in ("q1", "q2", "q3"):
        conn.execute(
            "INSERT INTO evidence VALUES (?, ?, 0, ?, ?, 'candidate', 1, 'high', NULL, NULL, ?, 'run')",
            (question_id, question_id, CANONICAL, LABEL, f"review:{question_id}"),
        )
    conn.commit()
    conn.close()


class FinalPostSweepSamplerTests(unittest.TestCase):
    def test_excludes_initial_review_and_emits_blind_question_packet(self):
        from english_knowledge_tagger.final_post_sweep_sampler import build_final_post_sweep_packets

        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            snapshot = directory / "snapshot.sqlite3"
            _create_snapshot(snapshot)
            source = directory / "source.jsonl"
            source.write_text(
                "\n".join(json.dumps(_source_row(q), ensure_ascii=False) for q in ("q1", "q2", "q3")) + "\n",
                encoding="utf-8",
            )
            exclude = directory / "calibration.jsonl"
            exclude.write_text(
                json.dumps({"verify_label": LABEL, "question_id": "q1"}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            output = directory / "post-sweep"

            report = build_final_post_sweep_packets(
                snapshot_db=snapshot,
                source_path=source,
                output_dir=output,
                exclude_jsonl_path=exclude,
                sample_size=2,
                seed="test-seed",
                excluded_labels=(),
            )

            packet_paths = list((output / "packets").glob("*.review.jsonl"))
            packet_rows = [json.loads(line) for line in packet_paths[0].read_text().splitlines()]

        self.assertEqual(report["labels"], 1)
        self.assertEqual(report["total_selected_records"], 2)
        self.assertEqual(report["total_emitted_records"], 2)
        self.assertNotIn("q1", {row["question_id"] for row in packet_rows})
        self.assertTrue(all("题型结构为：" not in row["question_text"] for row in packet_rows))
        self.assertTrue(all("output" not in row and "input" not in row for row in packet_rows))

    def test_cli_writes_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            snapshot = directory / "snapshot.sqlite3"
            _create_snapshot(snapshot)
            source = directory / "source.jsonl"
            source.write_text(
                json.dumps(_source_row("q1"), ensure_ascii=False) + "\n", encoding="utf-8"
            )
            output = directory / "post-sweep"
            script = Path(__file__).resolve().parents[1] / "scripts" / "sample_final_post_sweep.py"
            result = __import__("subprocess").run(
                [
                    sys.executable,
                    str(script),
                    "--snapshot-db", str(snapshot),
                    "--source", str(source),
                    "--output-dir", str(output),
                    "--sample-size", "1",
                    "--seed", "cli-test",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((output / "report.json").is_file())


if __name__ == "__main__":
    unittest.main()
