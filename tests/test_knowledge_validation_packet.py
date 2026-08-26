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

ALL_DIRECT_SIBLING_GRAMMAR_RULE = {
    "scope": "child",
    "declared_type_structure": "复合题",
    "declared_type_name": "语法选择",
    "allowed_knowledge_prefixes": ["知识点->词法", "知识点->句法"],
    "max_retrieved_candidates": 12,
    "sibling_selection": "all_direct_leaves",
    "max_output_labels": 3,
}


def write_wide_sibling_teacher_csv(path: Path) -> tuple[Path, list[str]]:
    target = "知识点->词法->被动语态->目标形式"
    sibling_paths = [f"知识点->词法->被动语态->形式{index}" for index in range(1, 10)]
    rows = [
        {
            "末级知识点": target,
            "打标解读（标绿的标签，新题不再打）": "目标标签。",
            "大模型压缩+人工微调的释义": "目标标签。",
        },
        *[
            {
                "末级知识点": sibling_path,
                "打标解读（标绿的标签，新题不再打）": f"{sibling_path}。",
                "大模型压缩+人工微调的释义": f"{sibling_path}。",
            }
            for sibling_path in sibling_paths
        ],
        {
            "末级知识点": "知识点->句法->简单句->陈述句",
            "打标解读（标绿的标签，新题不再打）": "外部分支标签。",
            "大模型压缩+人工微调的释义": "外部分支标签。",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)
    return path, sibling_paths


class KnowledgeValidationPacketTests(unittest.TestCase):
    def test_rulebook_returns_all_active_direct_leaf_siblings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rulebook = load_knowledge_rulebook(write_teacher_csv(Path(temp_dir) / "teacher.csv"))

        siblings = rulebook.direct_active_leaf_siblings("知识点->词法->冠词->a/an的区别")

        self.assertEqual(
            [sibling.path for sibling in siblings],
            ["知识点->词法->冠词->the的用法"],
        )

    def test_all_direct_leaf_policy_keeps_every_type_allowed_terminal_sibling(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            teacher_csv, expected_siblings = write_wide_sibling_teacher_csv(
                directory / "teacher.csv"
            )
            source = write_jsonl(
                directory / "source.jsonl",
                [
                    {
                        "question_id": "child-wide-1",
                        "is_sub_question": True,
                        "input": "题干：被动语态形式。答案：A。解析：选择正确形式。",
                        "output": "知识点@词法@被动语态@目标形式",
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
                rulebook=load_knowledge_rulebook(teacher_csv),
                candidate_policy=load_knowledge_candidate_policy(
                    write_candidate_policy(
                        directory / "candidate-policy.json", [ALL_DIRECT_SIBLING_GRAMMAR_RULE]
                    )
                ),
                output_path=output,
            )
            row = json.loads(output.read_text(encoding="utf-8"))

        sibling_labels = [
            candidate["label"]
            for candidate in row["alternative_labels"]
            if candidate["source"] == "sibling"
        ]
        self.assertEqual(sibling_labels, expected_siblings)
        self.assertEqual(row["candidate_pool"]["sibling_selection"], "all_direct_leaves")
        self.assertIsNone(row["candidate_pool"]["max_sibling_candidates"])
        self.assertEqual(row["candidate_pool"]["direct_sibling_count"], 9)

    def test_forbidden_rule_has_no_retrieval_pool(self):
        self.assertTrue(
            callable(load_knowledge_candidate_policy),
            "load_knowledge_candidate_policy must be implemented",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            policy = load_knowledge_candidate_policy(
                write_candidate_policy(
                    directory / "candidate-policy.json",
                    [
                        {
                            "scope": "child",
                            "declared_type_structure": "复合题",
                            "declared_type_name": "阅读理解",
                            "knowledge_policy": "forbidden",
                        }
                    ],
                )
            )

        rule = policy.match("child", "复合题", "阅读理解")
        self.assertIsNotNone(rule)
        self.assertEqual(rule.knowledge_policy, "forbidden")
        self.assertEqual(rule.allowed_knowledge_prefixes, ())
        self.assertEqual(rule.max_retrieved_candidates, 0)
        self.assertEqual(rule.max_sibling_candidates, 0)
        self.assertEqual(rule.max_output_labels, 0)

    def test_required_rule_rejects_empty_candidate_pool(self):
        self.assertTrue(
            callable(load_knowledge_candidate_policy),
            "load_knowledge_candidate_policy must be implemented",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            with self.assertRaisesRegex(ValueError, "required"):
                load_knowledge_candidate_policy(
                    write_candidate_policy(
                        directory / "candidate-policy.json",
                        [
                            {
                                "scope": "child",
                                "declared_type_structure": "复合题",
                                "declared_type_name": "语法选择",
                                "knowledge_policy": "required",
                                "allowed_knowledge_prefixes": [],
                                "max_retrieved_candidates": 0,
                                "max_sibling_candidates": 0,
                                "max_output_labels": 0,
                            }
                        ],
                    )
                )

    def test_forbidden_route_preserves_historical_label_as_a_policy_conflict(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = write_jsonl(
                directory / "source.jsonl",
                [
                    {
                        "question_id": "child-1",
                        "is_sub_question": True,
                        "input": "题干：Choose the correct answer. 答案：A。",
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
                            "declared_type_name": "阅读理解",
                        },
                    }
                ],
            )
            output = directory / "packet.jsonl"
            report = build_knowledge_validation_packet(
                source,
                review_packet_path=review_packet,
                rulebook=load_knowledge_rulebook(write_teacher_csv(directory / "teacher.csv")),
                candidate_policy=load_knowledge_candidate_policy(
                    write_candidate_policy(
                        directory / "candidate-policy.json",
                        [
                            {
                                "scope": "child",
                                "declared_type_structure": "复合题",
                                "declared_type_name": "阅读理解",
                                "knowledge_policy": "forbidden",
                            }
                        ],
                    )
                ),
                output_path=output,
            )
            row = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(row["knowledge_policy"], "forbidden")
        self.assertEqual(row["validation_action"], "skip_policy_forbidden")
        self.assertEqual(row["alternative_labels"], [])
        self.assertEqual(row["candidate_pool"]["max_output_labels"], 0)
        self.assertEqual(report["policy_forbidden_items"], 1)
        self.assertEqual(report["model_validation_items"], 0)

    def test_unconfigured_route_is_unresolved_not_a_validated_empty_set(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = write_jsonl(
                directory / "source.jsonl",
                [
                    {
                        "question_id": "child-1",
                        "is_sub_question": True,
                        "input": "题干：Choose the correct answer. 答案：A。",
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
                            "declared_type_name": "尚未配置",
                        },
                    }
                ],
            )
            output = directory / "packet.jsonl"
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

        self.assertEqual(row["knowledge_policy"], "unresolved")
        self.assertEqual(row["validation_action"], "skip_policy_unresolved")
        self.assertEqual(row["alternative_labels"], [])
        self.assertEqual(report["policy_unresolved_items"], 1)
        self.assertEqual(report["model_validation_items"], 0)

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
            rows[0]["route_key"],
            {
                "scope": "child",
                "declared_type_structure": "复合题",
                "declared_type_name": "语法选择",
            },
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

    def test_report_excludes_unmapped_taxonomy_from_model_validation_items(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = write_jsonl(
                directory / "source.jsonl",
                [
                    {
                        "question_id": "child-1",
                        "is_sub_question": True,
                        "input": "题干：...答案：A。",
                        "output": "知识点@不存在的分类@不存在的标签",
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
            report = build_knowledge_validation_packet(
                source,
                review_packet_path=review_packet,
                rulebook=load_knowledge_rulebook(write_teacher_csv(directory / "teacher.csv")),
                candidate_policy=load_knowledge_candidate_policy(
                    write_candidate_policy(directory / "candidate-policy.json", [GRAMMAR_RULE])
                ),
                output_path=directory / "packet.jsonl",
            )

        self.assertEqual(report["unmapped_legacy_labels"], 1)
        self.assertEqual(report["model_validation_items"], 0)

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

    def test_packet_uses_one_shared_retrieval_shortlist_for_all_labels_on_the_same_question(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = write_jsonl(
                directory / "source.jsonl",
                [
                    {
                        "question_id": "child-1",
                        "is_sub_question": True,
                        "input": "题干：It is an umbrella every day. 解析：考查 a/an 和一般现在时。",
                        "output": (
                            "知识点@词法@冠词@a/an的区别;"
                            "知识点@词法@动词@时态@一般现在时"
                        ),
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
            packet = directory / "packet.jsonl"
            build_knowledge_validation_packet(
                source,
                review_packet_path=review_packet,
                rulebook=load_knowledge_rulebook(write_teacher_csv(directory / "teacher.csv")),
                candidate_policy=load_knowledge_candidate_policy(
                    write_candidate_policy(directory / "candidate-policy.json", [GRAMMAR_RULE])
                ),
                output_path=packet,
            )
            rows = [json.loads(line) for line in packet.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(len(rows), 2)
        self.assertEqual(
            rows[0]["candidate_pool"]["shared_retrieved_labels"],
            rows[1]["candidate_pool"]["shared_retrieved_labels"],
        )
        self.assertLessEqual(len(rows[0]["candidate_pool"]["shared_retrieved_labels"]), 12)


if __name__ == "__main__":
    unittest.main()
