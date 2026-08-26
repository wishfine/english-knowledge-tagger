import csv
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

try:
    from english_knowledge_tagger.teacher_subquestion_gold_import import (
        import_teacher_subquestion_gold,
    )
    from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook
    from english_knowledge_tagger.knowledge_taxonomy_migration import (
        load_knowledge_taxonomy_migration,
    )
except ModuleNotFoundError:
    import_teacher_subquestion_gold = None
    load_knowledge_rulebook = None
    load_knowledge_taxonomy_migration = None


HEADERS = (
    "末级知识点",
    "打标解读（标绿的标签，新题不再打）",
    "大模型压缩+人工微调的释义",
)


def write_xlsx(path: Path) -> Path:
    workbook = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<workbook xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\">
  <sheets><sheet name=\"小题知识点\" sheetId=\"1\" r:id=\"rId1\"/></sheets>
</workbook>"""
    rels = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">
  <Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/sheet1.xml\"/>
</Relationships>"""

    def cell(reference: str, value: str) -> str:
        escaped = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f'<c r="{reference}" t="inlineStr"><is><t xml:space="preserve">{escaped}</t></is></c>'

    sheet = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"><sheetData>
  <row r=\"1\">%s%s</row>
  <row r=\"2\">%s%s</row>
  <row r=\"3\">%s%s</row>
</sheetData></worksheet>""" % (
        cell("A1", "题目ID"),
        cell("G1", "小题知识点标签（每个小题单独一行）"),
        cell("A2", "parent-1"),
        cell(
            "G2",
            "(1) 知识点@语法词法@冠词@a/an的区别\n"
            "(2) 知识点@词汇@固定搭配/句型;知识点@语法词法@冠词@the的用法",
        ),
        cell("A3", "parent-2"),
        cell("G3", "这是道大题，单选题"),
    )
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return path


def write_teacher_csv(path: Path) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(
            [
                {
                    "末级知识点": "知识点->词法->冠词->a/an的区别",
                    "打标解读（标绿的标签，新题不再打）": "a/an",
                    "大模型压缩+人工微调的释义": "a/an",
                },
                {
                    "末级知识点": "知识点->词法->冠词->the的用法",
                    "打标解读（标绿的标签，新题不再打）": "the",
                    "大模型压缩+人工微调的释义": "the",
                },
                {
                    "末级知识点": "知识点->词汇->固定搭配/句型",
                    "打标解读（标绿的标签，新题不再打）": "搭配",
                    "大模型压缩+人工微调的释义": "搭配",
                },
            ]
        )
    return path


def write_migration(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "knowledge-taxonomy-migration-v1",
                "rules": [
                    {
                        "rule_id": "legacy-word-to-current-word",
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


class TeacherSubquestionGoldImportTests(unittest.TestCase):
    def test_importer_parses_numbered_small_questions_and_migrates_teacher_gold_labels(self):
        self.assertTrue(callable(import_teacher_subquestion_gold))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            output = directory / "gold.jsonl"
            report = import_teacher_subquestion_gold(
                write_xlsx(directory / "teacher.xlsx"),
                rulebook=load_knowledge_rulebook(write_teacher_csv(directory / "rulebook.csv")),
                migration=load_knowledge_taxonomy_migration(write_migration(directory / "migration.json")),
                output_path=output,
            )
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(report["subquestion_gold_sets"], 2)
        self.assertEqual(report["non_small_question_rows"], 1)
        self.assertEqual(rows[0]["parent_question_id"], "parent-1")
        self.assertEqual(rows[0]["subquestion_index"], 1)
        self.assertEqual(rows[0]["gold_labels"], ["知识点->词法->冠词->a/an的区别"])
        self.assertEqual(rows[0]["taxonomy_mappings"][0]["status"], "prefix_alias")
        self.assertEqual(
            rows[1]["gold_labels"],
            ["知识点->词汇->固定搭配/句型", "知识点->词法->冠词->the的用法"],
        )


if __name__ == "__main__":
    unittest.main()
