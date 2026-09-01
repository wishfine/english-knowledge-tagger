import csv
import json
from pathlib import Path
import tempfile
import unittest

from english_knowledge_tagger.definition_ambiguity_profile import (
    build_definition_ambiguity_manifest,
    load_p0_label_policy,
    summarize_confusion_evidence,
    summarize_mentor_results,
)
from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook
from english_knowledge_tagger.knowledge_taxonomy_migration import (
    KnowledgeTaxonomyAlias,
    KnowledgeTaxonomyMigration,
)


class DefinitionAmbiguityProfileTests(unittest.TestCase):
    def test_builds_label_flags_yields_siblings_and_confusion_neighbors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            teacher = root / "teacher.csv"
            with teacher.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=(
                        "末级知识点",
                        "打标解读（标绿的标签，新题不再打）",
                        "大模型压缩+人工微调的释义",
                    ),
                )
                writer.writeheader()
                writer.writerows(
                    [
                        {
                            "末级知识点": "知识点->词汇->构词法->转化法",
                            "打标解读（标绿的标签，新题不再打）": "所有涉及词性变化都打，无明确说明。",
                            "大模型压缩+人工微调的释义": "同形词发生词性变化。",
                        },
                        {
                            "末级知识点": "知识点->词汇->构词法->派生法",
                            "打标解读（标绿的标签，新题不再打）": "适用题型：填空题。例如 direct 到 director；不标同形转化。",
                            "大模型压缩+人工微调的释义": "通过词缀构成新词，不标同形转化。",
                        },
                        {
                            "末级知识点": "知识点->句法->句子成分->主语",
                            "打标解读（标绿的标签，新题不再打）": "判断句子的主语。",
                            "大模型压缩+人工微调的释义": "答案直接依赖主语识别。",
                        },
                    ]
                )
            overrides = root / "overrides.json"
            overrides.write_text(
                json.dumps(
                    {
                        "schema_version": "knowledge-definition-overrides-v1",
                        "overrides": [
                            {
                                "label": "知识点->词汇->构词法->转化法",
                                "replacement_definition": "只有词形不变且答案依赖词性转换时才标；不标派生。",
                                "status": "active_for_experiment",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            results = root / "results.jsonl"
            rows = [
                {
                    "verify_label": "知识点@词汇@构词法@转化法",
                    "question_id": "q1",
                    "llm_match": False,
                    "llm_should_be": "知识点@词汇@构词法@派生法",
                },
                {
                    "verify_label": "知识点@词汇@构词法@转化法",
                    "question_id": "q2",
                    "llm_match": True,
                    "llm_should_be": "正确",
                },
                {
                    "verify_label": "知识点@句法@句子成分@主语",
                    "question_id": "q3",
                    "llm_match": True,
                    "llm_should_be": "正确",
                },
            ]
            results.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )
            p0 = root / "p0.json"
            p0.write_text(
                json.dumps(
                    {
                        "schema_version": "p0-terminal-label-policy-v1",
                        "labels": ["知识点->词汇->构词法->转化法"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            migration = KnowledgeTaxonomyMigration(
                aliases=(
                    KnowledgeTaxonomyAlias(
                        rule_id="legacy-syntax",
                        source_prefix="知识点->语法句法",
                        target_prefix="知识点->句法",
                    ),
                )
            )
            rulebook = load_knowledge_rulebook(teacher, overrides_path=overrides)

            yields = summarize_mentor_results(results, migration=migration, rulebook=rulebook)
            manifest = build_definition_ambiguity_manifest(
                rulebook,
                yields=yields,
                p0_labels=load_p0_label_policy(p0),
                additional_confusions={
                    "知识点->词汇->构词法->转化法": {
                        "知识点->词汇->构词法->派生法": 2
                    }
                },
            )

            indexed = {row["canonical_label"]: row for row in manifest["labels"]}
            conversion = indexed["知识点->词汇->构词法->转化法"]
            self.assertEqual(conversion["mentor_yield"]["matches"], 1)
            self.assertEqual(conversion["mentor_yield"]["sample_size"], 2)
            self.assertEqual(conversion["direct_active_leaf_siblings"], 1)
            self.assertTrue(conversion["is_p0"])
            self.assertTrue(conversion["flags"]["known_definition_override"])
            self.assertTrue(conversion["flags"]["broad_trigger_wording"])
            self.assertEqual(
                conversion["confusion_neighbors"][0],
                {"canonical_label": "知识点->词汇->构词法->派生法", "count": 3},
            )
            self.assertEqual(manifest["summary"]["knowledge_labels"], 3)
            self.assertEqual(manifest["summary"]["p0_labels"], 1)
            self.assertIn("fisher_exact", manifest["summary"])
            self.assertIn("spearman_ambiguity_score_vs_match_rate", manifest["summary"])
            self.assertEqual(
                manifest["summary"]["ambiguity_concentration_definition"],
                "audit_family_or_explicit_high_risk_flag",
            )

    def test_rejects_duplicate_p0_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "p0.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "p0-terminal-label-policy-v1",
                        "labels": ["知识点->词法->名词", "知识点->词法->名词"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_p0_label_policy(path)

    def test_summarizes_flat_and_tree_confusion_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            teacher = root / "teacher.csv"
            with teacher.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=(
                        "末级知识点",
                        "打标解读（标绿的标签，新题不再打）",
                        "大模型压缩+人工微调的释义",
                    ),
                )
                writer.writeheader()
                for label in (
                    "知识点->词汇->构词法->转化法",
                    "知识点->词汇->构词法->派生法",
                ):
                    writer.writerow(
                        {
                            "末级知识点": label,
                            "打标解读（标绿的标签，新题不再打）": label,
                            "大模型压缩+人工微调的释义": label,
                        }
                    )
            evidence = root / "evidence.jsonl"
            evidence.write_text(
                "".join(
                    json.dumps(row, ensure_ascii=False) + "\n"
                    for row in (
                        {
                            "canonical_label": "知识点->词汇->构词法->转化法",
                            "validation": {
                                "verdict": "replace",
                                "best_label": "知识点->词汇->构词法->派生法",
                            },
                        },
                        {
                            "historical_label": "知识点->词汇->构词法->转化法",
                            "candidate_label": "知识点->词汇->构词法->派生法",
                            "status": "tree_candidate",
                        },
                    )
                ),
                encoding="utf-8",
            )
            rulebook = load_knowledge_rulebook(teacher)
            result = summarize_confusion_evidence(
                (evidence,),
                migration=KnowledgeTaxonomyMigration(aliases=()),
                rulebook=rulebook,
            )
            self.assertEqual(
                result["知识点->词汇->构词法->转化法"][
                    "知识点->词汇->构词法->派生法"
                ],
                2,
            )


if __name__ == "__main__":
    unittest.main()
