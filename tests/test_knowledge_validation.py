import unittest

try:
    from english_knowledge_tagger.candidate_labeling import LabelingServiceConfig
    from english_knowledge_tagger.knowledge_validation import (
        KnowledgeValidationClient,
        KnowledgeValidationRequest,
        ValidationAlternative,
        parse_validation_response,
    )
except ModuleNotFoundError:
    LabelingServiceConfig = None
    KnowledgeValidationClient = None
    KnowledgeValidationRequest = None
    ValidationAlternative = None
    parse_validation_response = None


TARGET = "知识点->词法->冠词->a/an的区别"
ALTERNATIVE = "知识点->词法->冠词->the的用法"


class KnowledgeValidationTests(unittest.TestCase):
    def test_validator_sends_target_and_alternatives_then_parses_replace_verdict(self):
        self.assertTrue(callable(KnowledgeValidationClient), "KnowledgeValidationClient must be implemented")
        captured = {}

        def transport(endpoint, payload, timeout_seconds, headers):
            captured.update(endpoint=endpoint, payload=payload, timeout_seconds=timeout_seconds, headers=headers)
            return {
                "id": "chatcmpl-validation-test",
                "model": "ds-v4-flash",
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"verdict":"replace","best_label":"知识点->词法->冠词->the的用法",'
                                '"evidence":"题干考查特指。","reason":"应使用定冠词规则。"}'
                            )
                        }
                    }
                ],
            }

        client = KnowledgeValidationClient(
            LabelingServiceConfig(
                endpoint="http://172.22.0.35:6636/v1/chat/completions",
                model="ds-v4-flash",
            ),
            transport=transport,
        )
        result = client.validate(
            KnowledgeValidationRequest(
                review_id="kp-validation:child-1:a-an",
                question_context="题干：___ sun is bright. 答案：The。解析：表示特指。",
                legacy_label=TARGET,
                target_definition="原始释义：按读音判断 a 或 an。",
                alternatives=(ValidationAlternative(label=ALTERNATIVE, definition="判断是否使用 the。"),),
                max_output_labels=3,
            )
        )

        self.assertEqual(result.verdict, "replace")
        self.assertEqual(result.best_label, ALTERNATIVE)
        self.assertEqual(result.status, "candidate")
        prompt = captured["payload"]["messages"][0]["content"]
        self.assertIn("待验证历史标签", prompt)
        self.assertIn("原始释义", prompt)
        self.assertIn(ALTERNATIVE, prompt)
        self.assertEqual(captured["payload"]["temperature"], 0.0)

    def test_parser_marks_unsupported_replacement_as_unparsed_instead_of_promoting_it(self):
        self.assertTrue(callable(parse_validation_response), "parse_validation_response must be implemented")
        parsed = parse_validation_response(
            '{"verdict":"replace","best_label":"知识点->词法->杜撰标签",'
            '"evidence":"x","reason":"x"}',
            legacy_label=TARGET,
            allowed_labels=frozenset({TARGET, ALTERNATIVE}),
        )

        self.assertEqual(parsed.status, "unparsed")
        self.assertIsNone(parsed.verdict)
        self.assertIn("best_label", parsed.error or "")

    def test_parser_rejects_keep_when_historical_label_is_outside_small_question_pool(self):
        self.assertTrue(callable(parse_validation_response), "parse_validation_response must be implemented")
        parsed = parse_validation_response(
            '{"verdict":"keep","best_label":"知识点->词汇->词汇辨析->副词（短语）辨析",'
            '"evidence":"x","reason":"x"}',
            legacy_label="知识点->词汇->词汇辨析->副词（短语）辨析",
            allowed_labels=frozenset({"知识点->词法->形容词与副词->副词的用法->副词修饰动词"}),
            target_is_type_allowed=False,
        )

        self.assertEqual(parsed.status, "unparsed")
        self.assertIn("outside", parsed.error or "")


if __name__ == "__main__":
    unittest.main()
