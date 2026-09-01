import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from english_knowledge_tagger.parent_context_repair import (
    build_raw_index,
    enrich_enhanced_source,
    insert_parent_context,
    render_parent_context,
)


class ParentContextRepairTests(unittest.TestCase):
    def test_insert_parent_context_preserves_type_and_audio_headers(self):
        rendered = insert_parent_context(
            "题型结构为：听力题\n题型名称为：听力单选\n"
            "本题题干中包含音频内容，音频片段时长16秒，\n"
            "当前小题题干：What did he do?",
            "父题上下文：\n大题材料：\nListen to the dialogue.",
        )

        self.assertLess(rendered.index("题型结构为："), rendered.index("父题上下文："))
        self.assertLess(rendered.index("父题上下文："), rendered.index("当前小题题干："))
        self.assertIn("音频片段时长16秒", rendered)

    def test_render_parent_context_uses_text_only(self):
        rendered = render_parent_context(
            {
                "stem": "Read the passage.",
                "options": "",
                "knowledge_points": ["知识点@不应复制"],
                "analysis": "不应进入上下文",
                "answer": "A",
            }
        )

        self.assertIn("Read the passage.", rendered)
        self.assertIn("父题上下文", rendered)
        self.assertNotIn("知识点@不应复制", rendered)
        self.assertNotIn("不应进入上下文", rendered)

    def test_nested_child_is_indexed_and_unique_parent_context_is_added(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw.jsonl"
            enhanced = root / "enhanced.jsonl"
            index = root / "index.sqlite3"
            output = root / "repaired.jsonl"
            audit = root / "audit.jsonl"
            report = root / "report.json"
            manifest = root / "manifest.json"

            raw.write_text(
                json.dumps(
                    {
                        "question_id": "p1",
                        "parent_id": "p1",
                        "stem": "A parent passage.",
                        "options": "",
                        "analysis": "",
                        "answer": "",
                        "knowledge_points": ["知识点@父题标签"],
                        "question_types": [],
                        "sub_questions": [
                            {
                                "question_id": "c1",
                                "parent_id": "p1",
                                "stem": "What is the answer?",
                                "options": "A. one\nB. two",
                                "analysis": "Choose A.",
                                "answer": "A",
                                "knowledge_points": ["知识点@子题标签"],
                                "question_types": [],
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            enhanced.write_text(
                json.dumps(
                    {
                        "input": (
                            "题型结构为：填空题\n"
                            "题型名称为：完成句子\n"
                            "题目题干：What is the answer?"
                        ),
                        "output": "题型@阅读理解@阅读选择",
                        "question_id": "c1",
                        "parent_id": "p1",
                        "is_sub_question": True,
                        "contain_audio": False,
                        "whole_image": False,
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            build_report = build_raw_index(raw, index)
            self.assertEqual(build_report["nested_child_records"], 1)

            repair_report = enrich_enhanced_source(
                enhanced,
                index,
                output,
                audit,
                report,
                manifest,
                source_sha256="enhanced-sha",
                raw_sha256="raw-sha",
            )

            repaired = json.loads(output.read_text(encoding="utf-8"))
            audit_row = json.loads(audit.read_text(encoding="utf-8"))
            self.assertEqual(repair_report["status_counts"], {"added": 1})
            self.assertEqual(repair_report["source_sha256"], "enhanced-sha")
            self.assertEqual(repair_report["raw_sha256"], "raw-sha")
            self.assertEqual(repair_report["index_schema_version"], "parent-context-index-v1")
            self.assertIn("A parent passage.", repaired["input"])
            self.assertTrue(repaired["input"].startswith("题型结构为：填空题\n题型名称为：完成句子\n"))
            self.assertLess(
                repaired["input"].index("父题上下文："),
                repaired["input"].index("题目题干：What is the answer?"),
            )
            self.assertEqual(repaired["output"], "题型@阅读理解@阅读选择")
            self.assertFalse(repaired["contain_audio"])
            self.assertEqual(audit_row["status"], "added")
            self.assertEqual(audit_row["raw_child_source_line"], 1)
            self.assertEqual(audit_row["parent_source_line"], 1)

            manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(manifest_payload["source_sha256"], "enhanced-sha")
            self.assertEqual(manifest_payload["raw_sha256"], "raw-sha")

    def test_conflicting_parent_context_is_held_and_existing_context_is_not_duplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw.jsonl"
            enhanced = root / "enhanced.jsonl"
            index = root / "index.sqlite3"
            output = root / "repaired.jsonl"
            audit = root / "audit.jsonl"
            report = root / "report.json"
            manifest = root / "manifest.json"

            raw.write_text(
                "\n".join(
                    json.dumps(
                        {
                            "question_id": parent_id,
                            "parent_id": parent_id,
                            "stem": stem,
                            "sub_questions": (
                                [
                                    {
                                        "question_id": child_id,
                                        "parent_id": parent_id,
                                        "stem": "Child",
                                        "options": "",
                                        "analysis": "",
                                        "answer": "A",
                                    }
                                ]
                                if (parent_id, stem, child_id) in {
                                    ("p1", "first", "c1"),
                                    ("p2", "second", "c1"),
                                }
                                else []
                            ),
                        },
                        ensure_ascii=False,
                    )
                    for parent_id, stem, child_id in (
                        ("p1", "first", "c1"),
                        ("p1", "second", ""),
                        ("p2", "second", "c1"),
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            enhanced.write_text(
                "\n".join(
                    json.dumps(row, ensure_ascii=False)
                    for row in (
                        {
                            "input": "已有 first",
                            "output": "知识点@keep",
                            "question_id": "c1",
                            "parent_id": "p1",
                            "is_sub_question": True,
                        },
                        {
                            "input": "已有父题上下文：\n大题材料：\nsecond",
                            "output": "知识点@keep2",
                            "question_id": "c1",
                            "parent_id": "p2",
                            "is_sub_question": True,
                        },
                        {
                            "input": "缺失父题",
                            "output": "知识点@hold",
                            "question_id": "c2",
                            "parent_id": "p9",
                            "is_sub_question": True,
                        },
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            build_raw_index(raw, index)
            result = enrich_enhanced_source(
                enhanced,
                index,
                output,
                audit,
                report,
                manifest,
                source_sha256="enhanced-sha",
                raw_sha256="raw-sha",
            )

            self.assertEqual(
                result["status_counts"],
                {"already_present": 1, "ambiguous_parent": 1, "missing_child_match": 1},
            )
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows[0]["input"], "已有 first")
            self.assertIn("已有父题上下文", rows[1]["input"])
            self.assertEqual(rows[2]["input"], "缺失父题")


if __name__ == "__main__":
    unittest.main()
