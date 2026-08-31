import json
import unittest

try:
    from english_knowledge_tagger.candidate_labeling import LabelingServiceConfig
    from english_knowledge_tagger.conversion_relation import ConversionRelationClient, build_conversion_relation_prompt
except ModuleNotFoundError:
    LabelingServiceConfig = None
    ConversionRelationClient = None
    build_conversion_relation_prompt = None


class ConversionRelationTests(unittest.TestCase):
    def test_prompt_requires_one_of_five_relation_classes(self):
        self.assertTrue(callable(build_conversion_relation_prompt))
        prompt = build_conversion_relation_prompt({"task_id": "x", "question_context": "题干：direct 变为 director。"})
        self.assertIn('"relation":"conversion|derivation|inflection|lexical_or_other|insufficient"', prompt)
        self.assertNotIn("知识点@词汇@构词法@转化法", prompt)

    def test_client_parses_derivation_without_tree_taxonomy(self):
        self.assertTrue(callable(ConversionRelationClient))
        captured = {}
        def transport(endpoint, payload, timeout, headers):
            captured.update(endpoint=endpoint, payload=payload)
            return {"id": "x", "choices": [{"message": {"content": json.dumps({"relation": "derivation", "confidence": "high", "evidence": "direct 加 -or 变 director"}, ensure_ascii=False)}}]}
        client = ConversionRelationClient(LabelingServiceConfig(endpoint="http://example.invalid"), transport=transport)
        result = client.classify({"task_id": "x", "question_context": "题干：direct 变为 director。"})
        self.assertEqual(result.relation, "derivation")
        self.assertEqual(result.confidence, "high")
        self.assertIn("direct 加 -or", result.evidence)
        self.assertIn("词形完全不变", captured["payload"]["messages"][0]["content"])


if __name__ == "__main__":
    unittest.main()
