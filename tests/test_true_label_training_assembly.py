import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


LABEL_A = "知识点@词汇@固定搭配/句型"
LABEL_B = "知识点@语法词法@代词@反身代词"
LABEL_BAD = "知识点@词汇@近/反义词@同/近义词"
CANONICAL_A = "知识点->词汇->固定搭配/句型"
CANONICAL_B = "知识点->语法词法->代词->反身代词"
CANONICAL_BAD = "知识点->词汇->近/反义词->同/近义词"


def _rulebook(path: Path) -> Path:
    path.write_text(
        "末级知识点,打标解读（标绿的标签，新题不再打）,大模型压缩+人工微调的释义\n"
        f"{CANONICAL_A},固定搭配,固定搭配\n"
        f"{CANONICAL_B},反身代词,反身代词\n"
        f"{CANONICAL_BAD},同近义词,同近义词\n",
        encoding="utf-8",
    )
    return path


def _migration(path: Path) -> Path:
    path.write_text(
        json.dumps({"schema_version": "knowledge-taxonomy-migration-v1", "rules": []}),
        encoding="utf-8",
    )
    return path


def _source_row(question_id: str, output: str) -> dict[str, object]:
    return {
        "question_id": question_id,
        "parent_id": question_id,
        "is_sub_question": False,
        "input": "v3题干：题目内容",
        "output": output,
    }


def _make_snapshot(path: Path, rows: list[dict[str, object]]) -> Path:
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
                row["question_id"],
                row["parent_id"],
                int(row["is_sub_question"]),
                row["canonical_label"],
                row["legacy_label"],
                row.get("status", "candidate"),
                None if row.get("llm_match") is None else int(row["llm_match"]),
                row.get("confidence"),
                row.get("input_precheck_status"),
                row.get("llm_input_status"),
                row["review_id"],
                "synthetic",
            )
            for row in rows
        ],
    )
    connection.commit()
    connection.close()
    return path


class TrueLabelTrainingAssemblyTests(unittest.TestCase):
    def test_merges_positive_labels_uses_v3_source_and_removes_excluded_label(self):
        from english_knowledge_tagger.true_label_training_assembly import (
            build_true_label_training_data,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "v3.jsonl"
            source.write_text(
                json.dumps(
                    _source_row("q1", f"{LABEL_A};{LABEL_B};{LABEL_BAD};题型@单选"),
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            snapshot = _make_snapshot(
                root / "snapshot.sqlite3",
                [
                    {"question_id": "q1", "parent_id": "q1", "is_sub_question": False, "canonical_label": CANONICAL_A, "legacy_label": LABEL_A, "review_id": "r-a", "llm_match": True},
                    {"question_id": "q1", "parent_id": "q1", "is_sub_question": False, "canonical_label": CANONICAL_B, "legacy_label": LABEL_B, "review_id": "r-b", "llm_match": True},
                    {"question_id": "q1", "parent_id": "q1", "is_sub_question": False, "canonical_label": CANONICAL_BAD, "legacy_label": LABEL_BAD, "review_id": "r-bad", "llm_match": True},
                ],
            )
            output = root / "train.jsonl"
            provenance = root / "provenance.jsonl"
            holds = root / "holds.jsonl"
            report = build_true_label_training_data(
                snapshot_db=snapshot,
                source_path=source,
                teacher_csv=_rulebook(root / "teacher.csv"),
                taxonomy_migration=_migration(root / "migration.json"),
                output_path=output,
                provenance_path=provenance,
                hold_output_path=holds,
                excluded_labels=(LABEL_BAD,),
            )
            row = json.loads(output.read_text(encoding="utf-8").strip())
            provenance_row = json.loads(provenance.read_text(encoding="utf-8").strip())
            holds_text = holds.read_text(encoding="utf-8")

        self.assertEqual(report["train_records"], 1)
        self.assertEqual(row["input"], "v3题干：题目内容")
        self.assertEqual(row["output"], f"{LABEL_A};{LABEL_B};题型@单选")
        self.assertNotIn(LABEL_BAD, row["output"])
        self.assertEqual(provenance_row["positive_labels"], [CANONICAL_A, CANONICAL_B])
        self.assertEqual(holds_text, "")

    def test_partial_positive_history_is_held_instead_of_partial_training_labels(self):
        from english_knowledge_tagger.true_label_training_assembly import (
            build_true_label_training_data,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "v3.jsonl"
            source.write_text(
                json.dumps(_source_row("q1", f"{LABEL_A};{LABEL_B}"), ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            snapshot = _make_snapshot(
                root / "snapshot.sqlite3",
                [
                    {"question_id": "q1", "parent_id": "q1", "is_sub_question": False, "canonical_label": CANONICAL_A, "legacy_label": LABEL_A, "review_id": "r-a", "llm_match": True},
                    {"question_id": "q1", "parent_id": "q1", "is_sub_question": False, "canonical_label": CANONICAL_B, "legacy_label": LABEL_B, "review_id": "r-b", "llm_match": False},
                ],
            )
            output = root / "train.jsonl"
            provenance = root / "provenance.jsonl"
            holds = root / "holds.jsonl"
            report = build_true_label_training_data(
                snapshot_db=snapshot,
                source_path=source,
                teacher_csv=_rulebook(root / "teacher.csv"),
                taxonomy_migration=_migration(root / "migration.json"),
                output_path=output,
                provenance_path=provenance,
                hold_output_path=holds,
                excluded_labels=(),
            )
            hold_row = json.loads(holds.read_text(encoding="utf-8").strip())
            output_text = output.read_text(encoding="utf-8")

        self.assertEqual(report["train_records"], 0)
        self.assertEqual(hold_row["hold_reason"], "label_evidence_not_positive")
        self.assertEqual(hold_row["not_positive_labels"], [CANONICAL_B])
        self.assertEqual(output_text, "")

    def test_incomplete_positive_input_is_held(self):
        from english_knowledge_tagger.true_label_training_assembly import (
            build_true_label_training_data,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "v3.jsonl"
            source.write_text(json.dumps(_source_row("q1", LABEL_A), ensure_ascii=False) + "\n", encoding="utf-8")
            snapshot = _make_snapshot(
                root / "snapshot.sqlite3",
                [{"question_id": "q1", "parent_id": "q1", "is_sub_question": False, "canonical_label": CANONICAL_A, "legacy_label": LABEL_A, "review_id": "r-a", "llm_match": True, "input_precheck_status": "insufficient"}],
            )
            output = root / "train.jsonl"
            provenance = root / "provenance.jsonl"
            holds = root / "holds.jsonl"
            report = build_true_label_training_data(
                snapshot_db=snapshot,
                source_path=source,
                teacher_csv=_rulebook(root / "teacher.csv"),
                taxonomy_migration=_migration(root / "migration.json"),
                output_path=output,
                provenance_path=provenance,
                hold_output_path=holds,
                excluded_labels=(),
            )
            hold_row = json.loads(holds.read_text(encoding="utf-8").strip())

        self.assertEqual(report["train_records"], 0)
        self.assertEqual(hold_row["hold_reason"], "input_insufficient")


if __name__ == "__main__":
    unittest.main()
