import json
import unittest

from english_knowledge_tagger.candidate_labeling import LabelingServiceConfig
from english_knowledge_tagger.conversion_gate import (
    ConversionGateClient,
    build_conversion_gate_prompt,
)


class ConversionGateTests(unittest.TestCase):
    def test_prompt_requires_target_non_target_or_insufficient(self):
        prompt = build_conversion_gate_prompt(
            {"question_context": "题干：plant(v.) → plant(n.)，词形不变。"}
        )
        self.assertIn(
            '"decision":"target_conversion|non_target|insufficient"', prompt
        )
        self.assertIn("form_unchanged", prompt)
        self.assertIn("answer_depends_on_relation", prompt)
        self.assertNotIn("candidate_label", prompt)

    def test_client_parses_target_conversion_with_structural_evidence(self):
        captured = {}

        def transport(endpoint, payload, timeout, headers):
            captured["payload"] = payload
            return {
                "id": "gate-1",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "decision": "target_conversion",
                                    "confidence": "high",
                                    "source_forms": ["plant"],
                                    "target_forms": ["plant"],
                                    "form_unchanged": True,
                                    "pos_or_function_changed": True,
                                    "answer_depends_on_relation": True,
                                    "evidence": "plant 词形不变，由动词转为名词，答案依赖词性变化。",
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
            }

        client = ConversionGateClient(
            LabelingServiceConfig(endpoint="http://example.invalid"),
            transport=transport,
        )
        result = client.classify(
            {"question_context": "题干：plant(v.) → plant(n.)，词形不变。"}
        )

        self.assertEqual(result.decision, "target_conversion")
        self.assertEqual(result.confidence, "high")
        self.assertTrue(result.form_unchanged)
        self.assertTrue(result.pos_or_function_changed)
        self.assertTrue(result.answer_depends_on_relation)
        self.assertEqual(result.source_forms, ("plant",))
        self.assertEqual(result.target_forms, ("plant",))
        self.assertEqual(captured["payload"]["temperature"], 0.0)

    def test_client_rejects_missing_structural_fields(self):
        def transport(endpoint, payload, timeout, headers):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "decision": "non_target",
                                    "confidence": "high",
                                    "evidence": "这是派生法。",
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }

        client = ConversionGateClient(
            LabelingServiceConfig(endpoint="http://example.invalid"),
            transport=transport,
        )
        with self.assertRaises(Exception):
            client.classify({"question_context": "direct → director"})

    def test_client_downgrades_target_when_forms_are_not_identical(self):
        def transport(endpoint, payload, timeout, headers):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "decision": "target_conversion",
                                    "confidence": "high",
                                    "source_forms": ["direct (adj.)"],
                                    "target_forms": ["director (n.)"],
                                    "form_unchanged": True,
                                    "pos_or_function_changed": True,
                                    "answer_depends_on_relation": True,
                                    "evidence": "模型声称词形不变，但源词和目标词不同。",
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }

        client = ConversionGateClient(
            LabelingServiceConfig(endpoint="http://example.invalid"),
            transport=transport,
        )
        result = client.classify({"question_context": "direct → director"})
        self.assertEqual(result.decision, "insufficient")
        self.assertEqual(result.confidence, "low")
        self.assertIn("结构字段不一致", result.evidence)


if __name__ == "__main__":
    unittest.main()
