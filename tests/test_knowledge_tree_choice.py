import unittest

try:
    from english_knowledge_tagger.candidate_labeling import LabelingServiceConfig
    from english_knowledge_tagger.knowledge_rulebook import (
        KnowledgeRulebook,
        KnowledgeRulebookRecord,
    )
    from english_knowledge_tagger.knowledge_taxonomy_tree import NO_MATCH, KnowledgeTaxonomyTree
    from english_knowledge_tagger.knowledge_tree_choice import (
        KnowledgeTreeChoiceClient,
        build_tree_choice_prompt,
        parse_tree_choice_response,
    )
    from english_knowledge_tagger.knowledge_tree_search import TreeChoiceRequest
except ModuleNotFoundError:
    LabelingServiceConfig = None
    KnowledgeRulebook = None
    KnowledgeRulebookRecord = None
    NO_MATCH = "__NO_MATCH__"
    KnowledgeTaxonomyTree = None
    KnowledgeTreeChoiceClient = None
    build_tree_choice_prompt = None
    TreeChoiceRequest = None
    parse_tree_choice_response = None


def _tree() -> object:
    label = "知识点->词法->冠词->a/an的区别"
    return KnowledgeTaxonomyTree.from_rulebook(
        KnowledgeRulebook(
            records={
                label: KnowledgeRulebookRecord(
                    path=label,
                    status="active",
                    marking_interpretation="按发音判断 a/an。",
                    compressed_definition="按发音选择 a/an。",
                )
            }
        )
    )


class KnowledgeTreeChoiceTests(unittest.TestCase):
    def test_none_mode_keeps_terminal_path_but_omits_its_compressed_definition(self):
        self.assertTrue(callable(build_tree_choice_prompt), "build_tree_choice_prompt must be implemented")
        candidate = "知识点->词法->冠词->a/an的区别"

        prompt = build_tree_choice_prompt(
            TreeChoiceRequest(
                question_context="题干：It is ___ umbrella. 答案：an。",
                parent_path="知识点->词法->冠词",
                candidate_paths=(candidate,),
                excluded_paths=(),
            ),
            _tree(),
            terminal_definition_mode="none",
        )

        self.assertIn(candidate, prompt)
        self.assertNotIn("按发音选择 a/an。", prompt)

    def test_client_only_allows_current_siblings_and_no_match(self):
        self.assertTrue(callable(KnowledgeTreeChoiceClient), "KnowledgeTreeChoiceClient must be implemented")
        captured = {}
        candidate = "知识点->词法->冠词->a/an的区别"

        def transport(endpoint, payload, timeout_seconds, headers):
            captured.update(endpoint=endpoint, payload=payload, timeout_seconds=timeout_seconds, headers=headers)
            return {
                "id": "tree-choice-1",
                "model": "ds-v4-flash",
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"choice":"知识点->词法->冠词->a/an的区别",'
                                '"candidate_coverage":"covered","evidence":"umbrella 以元音音素开头。"}'
                            )
                        }
                    }
                ],
            }

        client = KnowledgeTreeChoiceClient(
            LabelingServiceConfig(endpoint="http://172.22.0.35:6636/v1/chat/completions"),
            _tree(),
            transport=transport,
        )
        result = client.choose(
            TreeChoiceRequest(
                question_context="题干：It is ___ umbrella. 答案：an。解析：考查冠词。",
                parent_path="知识点->词法->冠词",
                candidate_paths=(candidate,),
                excluded_paths=(),
            )
        )

        prompt = captured["payload"]["messages"][0]["content"]
        self.assertEqual(result.choice, candidate)
        self.assertEqual(result.candidate_coverage, "covered")
        self.assertIsNone(result.parse_error)
        self.assertIn(candidate, prompt)
        self.assertIn("按发音选择 a/an。", prompt)
        self.assertIn(NO_MATCH, prompt)
        self.assertNotIn("历史标签", prompt)
        self.assertEqual(captured["payload"]["temperature"], 0.0)
        self.assertGreaterEqual(result.model_call_elapsed_ms, 0.0)
        self.assertEqual(result.prompt_chars, len(prompt))
        self.assertEqual(result.response_chars, len(result.raw_response))

    def test_conversion_negative_constraint_only_appears_at_conversion_terminal(self):
        conversion = "知识点->词汇->构词法->转化法"
        tree = KnowledgeTaxonomyTree.from_rulebook(
            KnowledgeRulebook(
                records={
                    conversion: KnowledgeRulebookRecord(
                        path=conversion,
                        status="active",
                        marking_interpretation="同形词性转换。",
                        compressed_definition="同形词性转换。",
                    )
                }
            )
        )
        terminal = TreeChoiceRequest(
            question_context="题干：warmth 变为 warm。",
            parent_path="知识点->词汇->构词法",
            candidate_paths=(conversion,),
            excluded_paths=(),
        )
        non_terminal = TreeChoiceRequest(
            question_context="题干：warmth 变为 warm。",
            parent_path="知识点",
            candidate_paths=("知识点->词汇",),
            excluded_paths=(),
        )

        constrained = build_tree_choice_prompt(terminal, tree, conversion_negative_constraint=True)
        unconstrained = build_tree_choice_prompt(non_terminal, tree, conversion_negative_constraint=True)

        self.assertIn("词缀、拼写增删", constrained)
        self.assertNotIn("词缀、拼写增删", unconstrained)

    def test_structured_conversion_guard_requires_task_and_form_checks(self):
        conversion = "知识点->词汇->构词法->转化法"
        tree = KnowledgeTaxonomyTree.from_rulebook(
            KnowledgeRulebook(records={conversion: KnowledgeRulebookRecord(
                path=conversion,
                status="active",
                marking_interpretation="同形词性转换。",
                compressed_definition="同形词性转换。",
            )})
        )
        request = TreeChoiceRequest(
            question_context="题干：direct 变为 director。",
            parent_path="知识点->词汇->构词法",
            candidate_paths=(conversion,),
            excluded_paths=(),
        )
        prompt = build_tree_choice_prompt(request, tree, conversion_structured_guard=True)
        self.assertIn("实际要求完成", prompt)
        self.assertIn("词形是否完全不变", prompt)

    def test_parser_rejects_a_child_not_offered_by_the_current_step(self):
        self.assertTrue(callable(parse_tree_choice_response), "parse_tree_choice_response must be implemented")

        parsed = parse_tree_choice_response(
            '{"choice":"知识点->词汇","candidate_coverage":"covered","evidence":"x"}',
            allowed_choices=frozenset({"知识点->词法", NO_MATCH}),
        )

        self.assertEqual(parsed.status, "unparsed")
        self.assertIn("outside", parsed.error or "")


if __name__ == "__main__":
    unittest.main()
