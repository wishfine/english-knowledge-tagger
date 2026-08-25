import unittest

try:
    from english_knowledge_tagger.candidate_labeling import (
        CandidateLabelClient,
        LabelingRequest,
        LabelingServiceConfig,
        parse_label_response,
    )
except ModuleNotFoundError:
    CandidateLabelClient = None
    LabelingRequest = None
    LabelingServiceConfig = None
    parse_label_response = None


class CandidateLabelingTests(unittest.TestCase):
    def test_client_sends_versioned_prompt_and_preserves_candidate_provenance(self):
        self.assertTrue(callable(CandidateLabelClient), "CandidateLabelClient must be implemented")
        captured = {}

        def transport(endpoint, payload, timeout_seconds, headers):
            captured.update(
                endpoint=endpoint,
                payload=payload,
                timeout_seconds=timeout_seconds,
                headers=headers,
            )
            return {
                "id": "chatcmpl-test",
                "model": "ds-v4-flash",
                "choices": [
                    {
                        "message": {
                            "content": "新知识树@词汇@词汇辨析@名词（短语）辨析;新知识树@词汇@固定搭配/句型"
                        }
                    }
                ],
            }

        client = CandidateLabelClient(
            LabelingServiceConfig(
                endpoint="http://172.22.0.35:6636/v1/chat/completions",
                model="ds-v4-flash",
                timeout_seconds=45,
            ),
            transport=transport,
        )
        result = client.label(
            LabelingRequest(
                review_id="question-1",
                question_context="题目类型为：单选题（考词汇）\n题目答案：A\n题目解析：考查名词辨析。",
                candidate_definitions="新知识树@词汇@词汇辨析@名词（短语）辨析：辨析名词含义。",
            )
        )

        self.assertEqual(captured["endpoint"], "http://172.22.0.35:6636/v1/chat/completions")
        self.assertEqual(captured["payload"]["model"], "ds-v4-flash")
        self.assertEqual(captured["payload"]["temperature"], 0.0)
        self.assertIn("考查名词辨析", captured["payload"]["messages"][0]["content"])
        self.assertIn("候选标签及释义", captured["payload"]["messages"][0]["content"])
        self.assertEqual(
            result.labels,
            (
                "新知识树@词汇@词汇辨析@名词（短语）辨析",
                "新知识树@词汇@固定搭配/句型",
            ),
        )
        self.assertEqual(result.review_id, "question-1")
        self.assertEqual(result.prompt_version, "child-kp-ds-v4-v1")
        self.assertEqual(result.request_id, "chatcmpl-test")
        self.assertEqual(result.status, "candidate")

    def test_parser_marks_non_label_explanations_without_promoting_them_to_labels(self):
        self.assertTrue(callable(parse_label_response), "parse_label_response must be implemented")

        labels, unparsed = parse_label_response(
            "本题考查名词辨析。\n"
            "新知识树@词汇@词汇辨析@名词（短语）辨析；新知识树@词汇@固定搭配/句型"
        )

        self.assertEqual(
            labels,
            (
                "新知识树@词汇@词汇辨析@名词（短语）辨析",
                "新知识树@词汇@固定搭配/句型",
            ),
        )
        self.assertEqual(unparsed, ("本题考查名词辨析。",))
