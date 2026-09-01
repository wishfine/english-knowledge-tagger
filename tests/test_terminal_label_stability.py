import csv
import json
from pathlib import Path
import tempfile
import unittest

from english_knowledge_tagger.candidate_labeling import LabelingServiceConfig
from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook
from english_knowledge_tagger.knowledge_taxonomy_migration import KnowledgeTaxonomyMigration
from english_knowledge_tagger.terminal_label_stability import (
    TerminalLabelStabilityClient,
    build_terminal_label_stability_packet,
    build_terminal_label_stability_prompt,
    summarize_terminal_label_stability_runs,
    select_stable_definition_variants,
    assemble_terminal_stability_decisions,
    filter_terminal_label_stability_packet,
)


class TerminalLabelStabilityTests(unittest.TestCase):
    def _rulebook(self, root: Path):
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
            writer.writerow(
                {
                    "末级知识点": "知识点->词汇->构词法->转化法",
                    "打标解读（标绿的标签，新题不再打）": "老师原始释义。",
                    "大模型压缩+人工微调的释义": "压缩释义。",
                }
            )
        overrides = root / "overrides.json"
        overrides.write_text(
            json.dumps(
                {
                    "schema_version": "knowledge-definition-overrides-v1",
                    "overrides": [
                        {
                            "label": "知识点->词汇->构词法->转化法",
                            "replacement_definition": "覆盖释义：词形不变；不标派生。",
                            "status": "active_for_experiment",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return load_knowledge_rulebook(teacher, overrides_path=overrides)

    def test_packet_strictly_joins_gold_and_keeps_split_equal_across_variants(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rulebook = self._rulebook(root)
            materialized = root / "materialized.jsonl"
            source_rows = []
            gold_rows = []
            decisions = ("keep", "remove", "uncertain", "keep", "remove")
            for index, decision in enumerate(decisions, 1):
                source_rows.append(
                    {
                        "verify_label": "知识点@词汇@构词法@转化法",
                        "question_id": f"q{index}",
                        "parent_id": f"p{index}",
                        "is_sub_question": False,
                        "input": (
                            "题型结构为：填空题\n题型名称为：语法填空\n"
                            f"题目题干：question {index}\n题目答案：answer"
                        ),
                    }
                )
                gold_rows.append(
                    {
                        "verify_label": "知识点@词汇@构词法@转化法",
                        "question_id": f"q{index}",
                        "decision": decision,
                    }
                )
            materialized.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in source_rows),
                encoding="utf-8",
            )
            gold = root / "gold.jsonl"
            gold.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in gold_rows),
                encoding="utf-8",
            )
            output = root / "packet.jsonl"

            report = build_terminal_label_stability_packet(
                materialized,
                pseudo_gold_path=gold,
                verify_label="知识点@词汇@构词法@转化法",
                rulebook=rulebook,
                migration=KnowledgeTaxonomyMigration(aliases=()),
                output_path=output,
                seed="definition-stability-v1",
            )

            packet_rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(report["questions"], 5)
            self.assertEqual(report["packet_rows"], 15)
            self.assertEqual(
                {row["definition_variant"] for row in packet_rows}, {"D0", "D1", "D2"}
            )
            split_by_question = {}
            for row in packet_rows:
                split_by_question.setdefault(row["question_id"], set()).add(row["split"])
                self.assertNotIn("题型结构为", row["question_text"])
                self.assertNotIn("题型名称为", row["question_text"])
            self.assertTrue(all(len(splits) == 1 for splits in split_by_question.values()))

    def test_prompt_hides_gold_and_route(self):
        row = {
            "legacy_label": "知识点@词汇@构词法@转化法",
            "definition_text": "词形不变且词性改变。",
            "question_text": "题目题干：water作动词。",
            "pseudo_gold_decision": "remove",
            "route_key": {
                "scope": "parent",
                "declared_type_structure": "填空题",
                "declared_type_name": "语法填空",
            },
        }
        prompt = build_terminal_label_stability_prompt(row)
        self.assertIn("词形不变且词性改变", prompt)
        self.assertIn("water作动词", prompt)
        self.assertNotIn("pseudo_gold", prompt)
        self.assertNotIn("remove", prompt)
        self.assertNotIn("填空题", prompt)
        self.assertNotIn("语法填空", prompt)

    def test_client_sends_thinking_false_and_parses_three_way_result(self):
        captured = {}

        def transport(endpoint, payload, timeout, headers):
            captured["payload"] = payload
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "decision": "keep",
                                    "confidence": "high",
                                    "criterion_evidence": ["water词形不变并改作动词"],
                                    "missing_context": [],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }

        client = TerminalLabelStabilityClient(
            LabelingServiceConfig(endpoint="http://example.invalid"), transport=transport
        )
        result = client.classify(
            {
                "legacy_label": "知识点@词汇@构词法@转化法",
                "definition_text": "词形不变且词性改变。",
                "question_text": "water作动词。",
            }
        )
        self.assertEqual(result.decision, "keep")
        self.assertEqual(result.criterion_evidence, ("water词形不变并改作动词",))
        self.assertEqual(
            captured["payload"]["chat_template_kwargs"], {"enable_thinking": False}
        )

    def test_three_run_summary_applies_precision_first_gate(self):
        packet = (
            {
                "review_id": "D2:q1",
                "canonical_label": "知识点->词汇->构词法->转化法",
                "definition_variant": "D2",
                "split": "locked_test",
                "pseudo_gold_decision": "keep",
            },
            {
                "review_id": "D2:q2",
                "canonical_label": "知识点->词汇->构词法->转化法",
                "definition_variant": "D2",
                "split": "locked_test",
                "pseudo_gold_decision": "remove",
            },
        )
        rows = (
            {
                "review_id": "D2:q1",
                "decision": "keep",
                "confidence": "high",
                "elapsed_ms": 10.0,
                "prompt_chars": 100,
            },
            {
                "review_id": "D2:q2",
                "decision": "non_target",
                "confidence": "high",
                "elapsed_ms": 20.0,
                "prompt_chars": 120,
            },
        )
        summary = summarize_terminal_label_stability_runs(
            packet,
            runs=(("r1", rows), ("r2", rows), ("r3", rows)),
        )
        group = summary["groups"]["知识点->词汇->构词法->转化法|D2|locked_test"]
        self.assertEqual(group["three_run_decision_agreement"], 1.0)
        self.assertEqual(group["unanimous_keep_precision"], 1.0)
        self.assertEqual(group["unanimous_keep_recall"], 1.0)
        self.assertTrue(group["passes_precision_first_gate"])

    def test_selects_best_passing_variant_per_label_for_one_split(self):
        summary = {
            "groups": {
                "label-a|D0|definition_dev": {
                    "passes_precision_first_gate": True,
                    "unanimous_keep_precision": 0.97,
                    "three_run_decision_agreement": 0.98,
                    "high_confidence_false_positive_rate": 0.01,
                    "mean_prompt_chars": 200,
                },
                "label-a|D1|definition_dev": {
                    "passes_precision_first_gate": True,
                    "unanimous_keep_precision": 1.0,
                    "three_run_decision_agreement": 0.99,
                    "high_confidence_false_positive_rate": 0.0,
                    "mean_prompt_chars": 220,
                },
                "label-b|D0|definition_dev": {
                    "passes_precision_first_gate": False,
                    "unanimous_keep_precision": 1.0,
                    "three_run_decision_agreement": 0.80,
                    "high_confidence_false_positive_rate": 0.0,
                    "mean_prompt_chars": 100,
                },
            }
        }
        selection = select_stable_definition_variants(summary, split="definition_dev")
        self.assertEqual(selection["labels"]["label-a"]["definition_variant"], "D1")
        self.assertEqual(selection["labels"]["label-b"]["status"], "hold")

    def test_assembles_stable_keep_drop_and_uncertain_hold(self):
        packet = (
            {
                "review_id": "D1:q1",
                "question_id": "q1",
                "canonical_label": "label",
                "definition_variant": "D1",
                "pseudo_gold_decision": "keep",
            },
            {
                "review_id": "D1:q2",
                "question_id": "q2",
                "canonical_label": "label",
                "definition_variant": "D1",
                "pseudo_gold_decision": "remove",
            },
            {
                "review_id": "D1:q3",
                "question_id": "q3",
                "canonical_label": "label",
                "definition_variant": "D1",
                "pseudo_gold_decision": "uncertain",
            },
        )
        rows = (
            {"review_id": "D1:q1", "decision": "keep", "confidence": "high"},
            {"review_id": "D1:q2", "decision": "non_target", "confidence": "high"},
            {"review_id": "D1:q3", "decision": "keep", "confidence": "high"},
        )
        selection = {
            "labels": {
                "label": {"status": "selected", "definition_variant": "D1"}
            }
        }
        decisions = assemble_terminal_stability_decisions(
            packet,
            runs=(("r1", rows), ("r2", rows), ("r3", rows)),
            definition_selection=selection,
        )
        by_question = {row["question_id"]: row["disposition"] for row in decisions}
        self.assertEqual(by_question["q1"], "stable_keep_candidate")
        self.assertEqual(by_question["q2"], "stable_drop_candidate")
        self.assertEqual(by_question["q3"], "hold")

    def test_filters_packet_by_split_and_definition_variants(self):
        rows = (
            {"review_id": "D0:q1", "split": "definition_dev", "definition_variant": "D0"},
            {"review_id": "D1:q1", "split": "definition_dev", "definition_variant": "D1"},
            {"review_id": "D0:q2", "split": "locked_test", "definition_variant": "D0"},
        )
        filtered = filter_terminal_label_stability_packet(
            rows, split="definition_dev", definition_variants=frozenset({"D0", "D1"})
        )
        self.assertEqual([row["review_id"] for row in filtered], ["D0:q1", "D1:q1"])


if __name__ == "__main__":
    unittest.main()
