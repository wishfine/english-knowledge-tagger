import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


LABEL_A = "知识点@词汇@固定搭配/句型"
LABEL_B = "知识点@语法词法@代词@反身代词"
CANONICAL_A = "知识点->词汇->固定搭配/句型"
CANONICAL_B = "知识点->语法词法->代词->反身代词"


def _snapshot(path: Path, rows: list[dict[str, object]]) -> Path:
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE evidence (
            question_id TEXT, parent_id TEXT, is_sub_question INTEGER,
            canonical_label TEXT, legacy_label TEXT, status TEXT,
            llm_match INTEGER, confidence TEXT, input_precheck_status TEXT,
            llm_input_status TEXT, review_id TEXT, source_path TEXT
        )"""
    )
    connection.executemany(
        "INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                row["question_id"], row["parent_id"], int(row["is_sub_question"]),
                row["canonical_label"], row["legacy_label"], row.get("status", "candidate"),
                None if row.get("llm_match") is None else int(row["llm_match"]),
                row.get("confidence"), row.get("input_precheck_status"),
                row.get("llm_input_status"), row["review_id"], "synthetic",
            )
            for row in rows
        ],
    )
    connection.commit()
    connection.close()
    return path


class MaterializeProcessedLabelPacketsTests(unittest.TestCase):
    def test_writes_v3_source_and_positive_evidence_per_label(self):
        from english_knowledge_tagger.materialize_processed_label_packets import (
            materialize_processed_label_packets,
        )
        from english_knowledge_tagger.knowledge_taxonomy_migration import KnowledgeTaxonomyMigration

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "v3.jsonl"
            source.write_text(
                json.dumps({
                    "question_id": "q1", "parent_id": "p1", "is_sub_question": False,
                    "input": "v3题干", "output": f"{LABEL_A};{LABEL_B};题型@单选",
                }, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            snapshot = _snapshot(root / "snapshot.sqlite3", [
                {"question_id": "q1", "parent_id": "p1", "is_sub_question": False,
                 "canonical_label": CANONICAL_A, "legacy_label": LABEL_A,
                 "review_id": "r-a", "llm_match": True, "input_precheck_status": "complete"},
                {"question_id": "q1", "parent_id": "p1", "is_sub_question": False,
                 "canonical_label": CANONICAL_B, "legacy_label": LABEL_B,
                 "review_id": "r-b", "llm_match": True, "input_precheck_status": "complete"},
            ])
            output = root / "processed"
            report = materialize_processed_label_packets(
                snapshot_db=snapshot,
                source_path=source,
                output_dir=output,
                migration=KnowledgeTaxonomyMigration(aliases=()),
                excluded_labels=(),
                expected_label_count=2,
            )
            index = json.loads((output / "label_index.json").read_text(encoding="utf-8"))
            files = [output / item["filename"] for item in index["labels"].values()]
            rows = [json.loads(path.read_text(encoding="utf-8").strip()) for path in files]
            filenames = {label: item["filename"] for label, item in index["labels"].items()}

        self.assertEqual(report["label_count"], 2)
        self.assertEqual(report["output_records"], 2)
        self.assertEqual({row["verify_label"] for row in rows}, {LABEL_A, LABEL_B})
        self.assertEqual({row["source_record"]["input"] for row in rows}, {"v3题干"})
        self.assertTrue(all(row["evidence"]["llm_match"] is True for row in rows))
        self.assertIn("知识点@词汇@固定搭配／句型", filenames[CANONICAL_A])

    def test_excludes_false_and_incomplete_evidence_from_processed_packets(self):
        from english_knowledge_tagger.materialize_processed_label_packets import (
            materialize_processed_label_packets,
        )
        from english_knowledge_tagger.knowledge_taxonomy_migration import KnowledgeTaxonomyMigration

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "v3.jsonl"
            source.write_text(
                json.dumps({
                    "question_id": "q1", "parent_id": "p1", "is_sub_question": False,
                    "input": "v3题干", "output": f"{LABEL_A};{LABEL_B}",
                }, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            snapshot = _snapshot(root / "snapshot.sqlite3", [
                {"question_id": "q1", "parent_id": "p1", "is_sub_question": False,
                 "canonical_label": CANONICAL_A, "legacy_label": LABEL_A,
                 "review_id": "r-a", "llm_match": False, "input_precheck_status": "complete"},
                {"question_id": "q1", "parent_id": "p1", "is_sub_question": False,
                 "canonical_label": CANONICAL_B, "legacy_label": LABEL_B,
                 "review_id": "r-b", "llm_match": True, "input_precheck_status": "insufficient"},
            ])
            output = root / "processed"
            report = materialize_processed_label_packets(
                snapshot_db=snapshot,
                source_path=source,
                output_dir=output,
                migration=KnowledgeTaxonomyMigration(aliases=()),
                excluded_labels=(),
                expected_label_count=2,
            )

        self.assertEqual(report["label_count"], 2)
        self.assertEqual(report["output_records"], 0)
        self.assertEqual(report["eligible_positive_evidence"], 0)


if __name__ == "__main__":
    unittest.main()
