import csv
import json
from pathlib import Path
import tempfile
import unittest

try:
    from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook
    from english_knowledge_tagger.knowledge_taxonomy_migration import (
        load_knowledge_taxonomy_migration,
    )
    from english_knowledge_tagger.silver_question_assembly import assemble_silver_questions
except ModuleNotFoundError:
    load_knowledge_rulebook = None
    load_knowledge_taxonomy_migration = None
    assemble_silver_questions = None


HEADERS = (
    "末级知识点",
    "打标解读（标绿的标签，新题不再打）",
    "大模型压缩+人工微调的释义",
)
LABEL_A = "知识点->词法->冠词->a/an的区别"
LABEL_B = "知识点->词法->冠词->the的用法"


def write_rulebook(path: Path) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        for label in (LABEL_A, LABEL_B):
            writer.writerow(
                {
                    "末级知识点": label,
                    "打标解读（标绿的标签，新题不再打）": label,
                    "大模型压缩+人工微调的释义": label,
                }
            )
    return path


def write_migration(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "knowledge-taxonomy-migration-v1",
                "rules": [
                    {
                        "rule_id": "legacy-morphology",
                        "source_prefix": "知识点->语法词法",
                        "target_prefix": "知识点->词法",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def silver_evidence(
    *, question_id: str, source_line: int, label: str, review_id: str
) -> dict[str, object]:
    return {
        "schema_version": "terminal-label-discriminator-evidence-v1",
        "review_id": review_id,
        "question_id": question_id,
        "parent_id": "100",
        "source_line": source_line,
        "is_sub_question": True,
        "legacy_label": label,
        "canonical_label": label,
        "llm_match": True,
        "status": "candidate",
        "model": "ds-v4-flash",
        "prompt_version": "direct-label-v1",
        "disposition": "silver_label_candidate",
    }


class SilverQuestionAssemblyTests(unittest.TestCase):
    def test_requires_positive_evidence_for_every_historical_knowledge_label(self):
        self.assertTrue(callable(assemble_silver_questions))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = write_jsonl(
                directory / "source.jsonl",
                [
                    {
                        "question_id": "101",
                        "parent_id": "100",
                        "is_sub_question": True,
                        "input": "当前小题题干：a book",
                        "output": "知识点@语法词法@冠词@a/an的区别;知识点@语法词法@冠词@the的用法",
                    },
                    {
                        "question_id": "102",
                        "parent_id": "100",
                        "is_sub_question": True,
                        "input": "当前小题题干：the book",
                        "output": "知识点@语法词法@冠词@the的用法",
                    },
                ],
            )
            evidence = write_jsonl(
                directory / "silver-evidence.jsonl",
                [
                    silver_evidence(question_id="101", source_line=1, label=LABEL_A, review_id="a-101"),
                    silver_evidence(question_id="102", source_line=2, label=LABEL_B, review_id="b-102"),
                ],
            )
            candidates = directory / "candidates.jsonl"
            holds = directory / "holds.jsonl"
            report = assemble_silver_questions(
                source_path=source,
                silver_evidence_path=evidence,
                rulebook=load_knowledge_rulebook(write_rulebook(directory / "rulebook.csv")),
                migration=load_knowledge_taxonomy_migration(write_migration(directory / "migration.json")),
                output_path=candidates,
                hold_output_path=holds,
            )
            candidate_rows = [json.loads(line) for line in candidates.read_text(encoding="utf-8").splitlines()]
            hold_rows = [json.loads(line) for line in holds.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(report["counts"]["silver_question_candidate"], 1)
        self.assertEqual([row["question_id"] for row in candidate_rows], ["102"])
        self.assertEqual(candidate_rows[0]["approved_evidence_review_ids"], {LABEL_B: ["b-102"]})
        self.assertEqual(hold_rows[0]["question_id"], "101")
        self.assertEqual(
            hold_rows[0]["hold_reason"], "missing_positive_evidence_for_historical_label"
        )
        self.assertEqual(hold_rows[0]["missing_positive_evidence_labels"], [LABEL_B])

    def test_never_releases_evidence_when_its_source_identity_does_not_match(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = write_jsonl(
                directory / "source.jsonl",
                [
                    {
                        "question_id": "101",
                        "parent_id": "100",
                        "is_sub_question": True,
                        "input": "当前小题题干：a book",
                        "output": "知识点@语法词法@冠词@a/an的区别",
                    }
                ],
            )
            evidence = write_jsonl(
                directory / "silver-evidence.jsonl",
                [silver_evidence(question_id="101", source_line=99, label=LABEL_A, review_id="a-101")],
            )
            candidates = directory / "candidates.jsonl"
            holds = directory / "holds.jsonl"
            assemble_silver_questions(
                source_path=source,
                silver_evidence_path=evidence,
                rulebook=load_knowledge_rulebook(write_rulebook(directory / "rulebook.csv")),
                migration=load_knowledge_taxonomy_migration(write_migration(directory / "migration.json")),
                output_path=candidates,
                hold_output_path=holds,
            )
            candidate_content = candidates.read_text(encoding="utf-8")
            hold_rows = [json.loads(line) for line in holds.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(candidate_content, "")
        self.assertEqual(hold_rows[0]["hold_reason"], "positive_evidence_source_identity_mismatch")


if __name__ == "__main__":
    unittest.main()
