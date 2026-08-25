import csv
import json
from pathlib import Path
import tempfile
import unittest

try:
    from english_knowledge_tagger.knowledge_candidate_policy import (
        load_knowledge_candidate_policy,
    )
    from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook
    from english_knowledge_tagger.knowledge_taxonomy_migration import (
        load_knowledge_taxonomy_migration,
    )
    from english_knowledge_tagger.knowledge_validation_packet import build_knowledge_validation_packet
except ModuleNotFoundError:
    load_knowledge_candidate_policy = None
    load_knowledge_rulebook = None
    load_knowledge_taxonomy_migration = None
    build_knowledge_validation_packet = None


HEADERS = (
    "末级知识点",
    "打标解读（标绿的标签，新题不再打）",
    "大模型压缩+人工微调的释义",
)


def write_teacher_csv(path: Path) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(
            [
                {
                    "末级知识点": "知识点->词法->冠词->a/an的区别",
                    "打标解读（标绿的标签，新题不再打）": "原始释义：根据读音判断 a 或 an。",
                    "大模型压缩+人工微调的释义": "按发音选择 a/an。",
                },
                {
                    "末级知识点": "知识点->词法->冠词->the的用法",
                    "打标解读（标绿的标签，新题不再打）": "原始释义：判断定冠词 the 的使用。",
                    "大模型压缩+人工微调的释义": "判断是否使用 the。",
                },
                {
                    "末级知识点": "知识点->词法->动词->时态->一般现在时",
                    "打标解读（标绿的标签，新题不再打）": "原始释义：判断一般现在时。",
                    "大模型压缩+人工微调的释义": "句中 every day 表示一般现在时。",
                },
                {
                    "末级知识点": "知识点->词汇->固定搭配/句型",
                    "打标解读（标绿的标签，新题不再打）": "原始释义：判断固定搭配。",
                    "大模型压缩+人工微调的释义": "判断固定搭配。",
                },
                {
                    "末级知识点": "知识点->词汇->近/反义词->同/近义词",
                    "打标解读（标绿的标签，新题不再打）": "原始释义：判断同义词。",
                    "大模型压缩+人工微调的释义": "判断同义词。",
                },
            ]
        )
    return path


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def write_candidate_policy(path: Path, rules: list[dict[str, object]]) -> Path:
    path.write_text(
        json.dumps(
            {"schema_version": "knowledge-candidate-policy-v1", "rules": rules},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def write_migration(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "knowledge-taxonomy-migration-v1",
                "rules": [
                    {
                        "rule_id": "legacy-grammar-wording-to-morphology",
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


GRAMMAR_RULE = {
    "scope": "child",
    "declared_type_structure": "复合题",
    "declared_type_name": "语法选择",
    "allowed_knowledge_prefixes": ["知识点->词法", "知识点->句法"],
    "max_retrieved_candidates": 12,
    "max_sibling_candidates": 8,
    "max_output_labels": 3,
}


class KnowledgeValidationPacketTests(unittest.TestCase):
    def test_packet_unions_type_allowed_retrieval_with_target_siblings_without_parent_labels(self):
        self.assertTrue(
            callable(load_knowledge_candidate_policy),
            "load_knowledge_candidate_policy must be implemented",
        )
        self.assertTrue(callable(load_knowledge_rulebook), "load_knowledge_rulebook must be implemented")
        self.assertTrue(
            callable(build_knowledge_validation_packet),
            "build_knowledge_validation_packet must be implemented",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = write_jsonl(
                directory / "source.jsonl",
                [
                    {
                        "question_id": "child-1",
                        "parent_id": "parent-1",
                        "is_sub_question": True,
                        "input": "题干：It is ___ umbrella every day.\n答案：an\n解析：考查 a/an 的区别。",
                        "output": "知识点@词法@冠词@a/an的区别",
                    }
                ],
            )
            review_packet = write_jsonl(
                directory / "review.jsonl",
                [
                    {
                        "source_line": 1,
                        "question_id": "child-1",
                        "route_key": {
                            "scope": "child",
                            "declared_type_structure": "复合题",
                            "declared_type_name": "语法选择",
                        },
                    }
                ],
            )
            rulebook = load_knowledge_rulebook(write_teacher_csv(directory / "teacher.csv"))
            output = directory / "validation.jsonl"

            report = build_knowledge_validation_packet(
                source,
                review_packet_path=review_packet,
                rulebook=rulebook,
                candidate_policy=load_knowledge_candidate_policy(
                    write_candidate_policy(directory / "candidate-policy.json", [GRAMMAR_RULE])
                ),
                output_path=output,
            )
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(report["known_validation_items"], 1)
        self.assertEqual(rows[0]["legacy_label"], "知识点->词法->冠词->a/an的区别")
        self.assertIn("原始释义", rows[0]["target_definition"])
        self.assertEqual(
            rows[0]["candidate_pool"]["allowed_prefixes"],
            ["知识点->词法", "知识点->句法"],
        )
        self.assertEqual(
            rows[0]["alternative_labels"][0],
            {
                "label": "知识点->词法->冠词->the的用法",
                "definition": "判断是否使用 the。",
                "source": "sibling",
            },
        )
        self.assertIn(
            "知识点->词法->动词->时态->一般现在时",
            [item["label"] for item in rows[0]["alternative_labels"]],
        )
        self.assertEqual(rows[0]["taxonomy_status"], "known")

    def test_packet_records_unmapped_legacy_labels_without_model_definitions(self):
        self.assertTrue(
            callable(load_knowledge_candidate_policy),
            "load_knowledge_candidate_policy must be implemented",
        )
        self.assertTrue(callable(load_knowledge_rulebook), "load_knowledge_rulebook must be implemented")
        self.assertTrue(
            callable(build_knowledge_validation_packet),
            "build_knowledge_validation_packet must be implemented",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = write_jsonl(
                directory / "source.jsonl",
                [
                    {
                        "question_id": "child-1",
                        "input": "题干：...\n答案：A\n解析：...",
                        "output": "知识点@不存在的分类@不存在的标签",
                    }
                ],
            )
            review_packet = write_jsonl(
                directory / "review.jsonl",
                [{"source_line": 1, "question_id": "child-1"}],
            )
            output = directory / "validation.jsonl"

            report = build_knowledge_validation_packet(
                source,
                review_packet_path=review_packet,
                rulebook=load_knowledge_rulebook(write_teacher_csv(directory / "teacher.csv")),
                candidate_policy=load_knowledge_candidate_policy(
                    write_candidate_policy(directory / "candidate-policy.json", [])
                ),
                output_path=output,
            )
            row = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(report["unmapped_legacy_labels"], 1)
        self.assertEqual(row["taxonomy_status"], "unmapped_legacy_label")
        self.assertEqual(row["target_definition"], "")
        self.assertEqual(row["alternative_labels"], [])

    def test_packet_maps_legacy_taxonomy_before_validation_and_filters_outside_siblings(self):
        self.assertTrue(
            callable(load_knowledge_taxonomy_migration),
            "load_knowledge_taxonomy_migration must be implemented",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = write_jsonl(
                directory / "source.jsonl",
                [
                    {
                        "question_id": "child-1",
                        "is_sub_question": True,
                        "input": "题干：It is ___ umbrella. 答案：an。解析：考查 a/an。",
                        "output": "知识点@语法词法@冠词@a/an的区别",
                    },
                    {
                        "question_id": "child-2",
                        "is_sub_question": True,
                        "input": "题干：He goes to school every day. 答案：goes。解析：一般现在时。",
                        "output": "知识点@词汇@固定搭配/句型",
                    },
                ],
            )
            review_packet = write_jsonl(
                directory / "review.jsonl",
                [
                    {
                        "source_line": line_number,
                        "route_key": {
                            "scope": "child",
                            "declared_type_structure": "复合题",
                            "declared_type_name": "语法选择",
                        },
                    }
                    for line_number in (1, 2)
                ],
            )
            rulebook = load_knowledge_rulebook(write_teacher_csv(directory / "teacher.csv"))
            packet = directory / "packet.jsonl"
            build_knowledge_validation_packet(
                source,
                review_packet_path=review_packet,
                rulebook=rulebook,
                candidate_policy=load_knowledge_candidate_policy(
                    write_candidate_policy(directory / "candidate-policy.json", [GRAMMAR_RULE])
                ),
                taxonomy_migration=load_knowledge_taxonomy_migration(
                    write_migration(directory / "migration.json")
                ),
                output_path=packet,
            )
            rows = [json.loads(line) for line in packet.read_text(encoding="utf-8").splitlines()]

        mapped = next(row for row in rows if row["question_id"] == "child-1")
        outside = next(row for row in rows if row["question_id"] == "child-2")
        self.assertEqual(mapped["legacy_label"], "知识点->语法词法->冠词->a/an的区别")
        self.assertEqual(mapped["canonical_label"], "知识点->词法->冠词->a/an的区别")
        self.assertEqual(mapped["taxonomy_mapping"], {
            "status": "prefix_alias",
            "rule_id": "legacy-grammar-wording-to-morphology",
        })
        self.assertTrue(mapped["target_is_type_allowed"])
        self.assertFalse(outside["target_is_type_allowed"])
        self.assertTrue(
            all(
                alternative["label"].startswith(("知识点->词法", "知识点->句法"))
                for alternative in outside["alternative_labels"]
            )
        )

    def test_packet_strips_source_declared_type_metadata_from_model_context(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = write_jsonl(
                directory / "source.jsonl",
                [
                    {
                        "question_id": "child-1",
                        "is_sub_question": True,
                        "input": (
                            "题型结构为：复合题\n题型名称为：语法选择\n"
                            "当前小题题干：It is ___ umbrella.\n答案：an\n解析：考查 a/an。"
                        ),
                        "output": "知识点@词法@冠词@a/an的区别",
                    }
                ],
            )
            review_packet = write_jsonl(
                directory / "review.jsonl",
                [
                    {
                        "source_line": 1,
                        "route_key": {
                            "scope": "child",
                            "declared_type_structure": "复合题",
                            "declared_type_name": "语法选择",
                        },
                    }
                ],
            )
            output = directory / "packet.jsonl"
            build_knowledge_validation_packet(
                source,
                review_packet_path=review_packet,
                rulebook=load_knowledge_rulebook(write_teacher_csv(directory / "teacher.csv")),
                candidate_policy=load_knowledge_candidate_policy(
                    write_candidate_policy(directory / "candidate-policy.json", [GRAMMAR_RULE])
                ),
                output_path=output,
            )
            row = json.loads(output.read_text(encoding="utf-8"))

        self.assertNotIn("题型结构为：", row["question_context"])
        self.assertNotIn("题型名称为：", row["question_context"])
        self.assertIn("It is ___ umbrella", row["question_context"])
        self.assertIn("解析：考查 a/an", row["question_context"])


if __name__ == "__main__":
    unittest.main()
