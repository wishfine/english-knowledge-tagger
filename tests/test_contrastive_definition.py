import json
import unittest

from english_knowledge_tagger.candidate_labeling import LabelingServiceConfig
from english_knowledge_tagger.contrastive_definition import (
    ContrastiveDefinitionClient,
    build_contrastive_definition_prompt,
    build_contrastive_definition_task,
    expand_stability_packet_with_definition_candidates,
    select_contrastive_definition,
)


class ContrastiveDefinitionTests(unittest.TestCase):
    def test_generation_task_uses_only_train_examples(self):
        packet = (
            {
                "review_id": "D0:q1",
                "question_id": "q1",
                "canonical_label": "知识点->语用->时间->顺序",
                "legacy_label": "知识点@语用@时间@顺序",
                "definition_variant": "D0",
                "definition_text": "原始定义",
                "question_text": "TRAIN QUESTION",
                "pseudo_gold_decision": "keep",
                "split": "definition_train",
            },
            {
                "review_id": "D0:q2",
                "question_id": "q2",
                "canonical_label": "知识点->语用->时间->顺序",
                "legacy_label": "知识点@语用@时间@顺序",
                "definition_variant": "D0",
                "definition_text": "原始定义",
                "question_text": "DEV SECRET QUESTION",
                "pseudo_gold_decision": "remove",
                "split": "definition_dev",
            },
        )
        ambiguity = {
            "labels": [
                {
                    "canonical_label": "知识点->语用->时间->顺序",
                    "confusion_neighbors": [
                        {"canonical_label": "知识点->语用->时间->时段", "count": 8}
                    ],
                }
            ]
        }
        task = build_contrastive_definition_task(
            packet,
            ambiguity_manifest=ambiguity,
            canonical_label="知识点->语用->时间->顺序",
        )
        prompt = build_contrastive_definition_prompt(task)
        self.assertIn("TRAIN QUESTION", prompt)
        self.assertNotIn("DEV SECRET QUESTION", prompt)
        self.assertIn("知识点->语用->时间->时段", prompt)

    def test_client_parses_three_structured_candidates(self):
        def transport(endpoint, payload, timeout, headers):
            candidates = []
            for index in range(1, 4):
                candidates.append(
                    {
                        "candidate_id": f"D3-{index}",
                        "positive_criteria": f"必要条件{index}",
                        "neighbor_exclusions": ["排除时段"],
                        "insufficient_rule": "缺上下文时判 insufficient",
                        "co_label_rule": "允许与其他标签共标",
                        "appearance_dependency_rule": "出现关键词不等于答案依赖",
                    }
                )
            return {
                "choices": [
                    {"message": {"content": json.dumps({"definitions": candidates}, ensure_ascii=False)}}
                ]
            }

        client = ContrastiveDefinitionClient(
            LabelingServiceConfig(endpoint="http://example.invalid"), transport=transport
        )
        result = client.generate(
            {
                "canonical_label": "知识点->语用->时间->顺序",
                "legacy_label": "知识点@语用@时间@顺序",
                "source_definitions": ["原始定义"],
                "confusion_neighbors": [],
                "train_examples": [],
            }
        )
        self.assertEqual(len(result.candidates), 3)
        self.assertIn("正向必要条件：必要条件1", result.candidates[0].definition_text)
        self.assertIn("相邻标签排除：排除时段", result.candidates[0].definition_text)

    def test_expansion_only_uses_requested_split(self):
        packet = (
            {
                "review_id": "D0:q1",
                "question_id": "q1",
                "canonical_label": "label",
                "definition_variant": "D0",
                "split": "definition_dev",
            },
            {
                "review_id": "D0:q2",
                "question_id": "q2",
                "canonical_label": "label",
                "definition_variant": "D0",
                "split": "locked_test",
            },
        )
        candidates = (
            {"candidate_id": "D3-1", "definition_text": "definition one"},
            {"candidate_id": "D3-2", "definition_text": "definition two"},
            {"candidate_id": "D3-3", "definition_text": "definition three"},
        )
        expanded = expand_stability_packet_with_definition_candidates(
            packet, candidates=candidates, split="definition_dev"
        )
        self.assertEqual(len(expanded), 3)
        self.assertEqual({row["question_id"] for row in expanded}, {"q1"})
        self.assertEqual({row["definition_variant"] for row in expanded}, {"D3-1", "D3-2", "D3-3"})

    def test_selection_requires_d3_to_pass_and_beat_baseline(self):
        summary = {
            "groups": {
                "label|D2|definition_dev": {
                    "passes_precision_first_gate": True,
                    "unanimous_keep_precision": 0.96,
                    "three_run_decision_agreement": 0.96,
                    "high_confidence_false_positive_rate": 0.01,
                    "mean_prompt_chars": 200,
                },
                "label|D3-1|definition_dev": {
                    "passes_precision_first_gate": True,
                    "unanimous_keep_precision": 1.0,
                    "three_run_decision_agreement": 0.99,
                    "high_confidence_false_positive_rate": 0.0,
                    "mean_prompt_chars": 220,
                },
                "label|D3-2|definition_dev": {
                    "passes_precision_first_gate": False,
                    "unanimous_keep_precision": 1.0,
                    "three_run_decision_agreement": 0.80,
                    "high_confidence_false_positive_rate": 0.0,
                    "mean_prompt_chars": 180,
                },
            }
        }
        selection = select_contrastive_definition(summary, canonical_label="label")
        self.assertEqual(selection["status"], "selected")
        self.assertEqual(selection["definition_variant"], "D3-1")


if __name__ == "__main__":
    unittest.main()
