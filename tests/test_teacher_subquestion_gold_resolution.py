import json
from pathlib import Path
import tempfile
import unittest

try:
    from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook
    from english_knowledge_tagger.knowledge_taxonomy_migration import (
        load_knowledge_taxonomy_migration,
    )
    from english_knowledge_tagger.teacher_subquestion_gold_resolution import (
        resolve_teacher_subquestion_gold,
    )
except ModuleNotFoundError:
    load_knowledge_rulebook = None
    load_knowledge_taxonomy_migration = None
    resolve_teacher_subquestion_gold = None

from test_teacher_subquestion_gold_import import (  # reuse compact versioned fixtures
    write_migration,
    write_teacher_csv,
)


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


class TeacherSubquestionGoldResolutionTests(unittest.TestCase):
    def test_resolver_uses_parent_plus_small_question_index_and_emits_only_true_corrections(self):
        self.assertTrue(callable(resolve_teacher_subquestion_gold))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            imported_gold = write_jsonl(
                directory / "imported-gold.jsonl",
                [
                    {
                        "parent_question_id": "100",
                        "subquestion_index": 1,
                        "gold_labels": ["知识点->词法->冠词->the的用法"],
                        "taxonomy_resolved": True,
                    },
                    {
                        "parent_question_id": "100",
                        "subquestion_index": 2,
                        "gold_labels": ["知识点->词法->冠词->a/an的区别"],
                        "taxonomy_resolved": True,
                    },
                ],
            )
            source = write_jsonl(
                directory / "source.jsonl",
                [
                    {
                        "question_id": "102",
                        "parent_id": "100",
                        "is_sub_question": True,
                        "input": "题型结构为：完形填空\n题型名称为：语法选择\n当前小题题干：an umbrella",
                        "output": "知识点@语法词法@冠词@a/an的区别",
                    },
                    {
                        "question_id": "101",
                        "parent_id": "100",
                        "is_sub_question": True,
                        "input": "题型结构为：完形填空\n题型名称为：语法选择\n当前小题题干：the book",
                        "output": "知识点@语法词法@冠词@a/an的区别",
                    },
                ],
            )
            resolved = directory / "resolved.jsonl"
            corrections = directory / "corrections.jsonl"
            rulebook = load_knowledge_rulebook(write_teacher_csv(directory / "rulebook.csv"))
            report = resolve_teacher_subquestion_gold(
                imported_gold,
                source_path=source,
                rulebook=rulebook,
                migration=load_knowledge_taxonomy_migration(write_migration(directory / "migration.json")),
                output_path=resolved,
                corrections_output_path=corrections,
            )
            resolved_rows = [json.loads(line) for line in resolved.read_text(encoding="utf-8").splitlines()]
            correction_rows = [json.loads(line) for line in corrections.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(report["approved_gold_records"], 2)
        self.assertEqual(report["correction_records"], 1)
        first, second = resolved_rows
        self.assertEqual(first["question_id"], "101")
        self.assertEqual(first["child_rank"], 1)
        self.assertEqual(first["historical_labels"], ["知识点->词法->冠词->a/an的区别"])
        self.assertEqual(first["spurious_historical_labels"], ["知识点->词法->冠词->a/an的区别"])
        self.assertEqual(first["missing_gold_labels"], ["知识点->词法->冠词->the的用法"])
        self.assertEqual(second["question_id"], "102")
        self.assertEqual(second["spurious_historical_labels"], [])
        self.assertEqual(correction_rows[0]["historical_label"], "知识点->词法->冠词->a/an的区别")
        self.assertEqual(correction_rows[0]["gold_labels"], ["知识点->词法->冠词->the的用法"])
        self.assertEqual(correction_rows[0]["adjudication_status"], "approved")


if __name__ == "__main__":
    unittest.main()
