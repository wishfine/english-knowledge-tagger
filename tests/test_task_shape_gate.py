import unittest


try:
    from english_knowledge_tagger.task_shape_gate import TaskShapeGateClient, build_task_shape_prompt
    from english_knowledge_tagger.candidate_labeling import LabelingServiceConfig
except ImportError:
    TaskShapeGateClient = None
    build_task_shape_prompt = None
    LabelingServiceConfig = None


class TaskShapeGateTests(unittest.TestCase):
    def test_prompt_has_no_historical_label_and_defines_gate_outcomes(self):
        self.assertTrue(callable(build_task_shape_prompt))
        prompt = build_task_shape_prompt({"question_context": "题干：direct 变为 director。"})
        self.assertIn('"task_shape":"atomic_knowledge|lexical_or_other|mixed_or_multiple_relations|insufficient"', prompt)
        self.assertNotIn("历史", prompt)

    def test_client_parses_atomic_shape(self):
        self.assertTrue(callable(TaskShapeGateClient))
        def transport(*_args):
            return {"choices": [{"message": {"content": '{"task_shape":"atomic_knowledge","evidence":"要求 direct 变为 director"}'}}]}
        client = TaskShapeGateClient(LabelingServiceConfig(endpoint="http://example", model="test"), transport=transport)
        result = client.classify({"question_context": "题干：direct 变为 director。"})
        self.assertEqual(result.task_shape, "atomic_knowledge")

