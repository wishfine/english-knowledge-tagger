import unittest

try:
    from english_knowledge_tagger.knowledge_rulebook import (
        KnowledgeRulebook,
        KnowledgeRulebookRecord,
    )
    from english_knowledge_tagger.knowledge_taxonomy_tree import (
        NO_MATCH,
        KnowledgeTaxonomyTree,
    )
except ModuleNotFoundError:
    KnowledgeRulebook = None
    KnowledgeRulebookRecord = None
    NO_MATCH = None
    KnowledgeTaxonomyTree = None


def record(path: str, *, status: str = "active") -> object:
    return KnowledgeRulebookRecord(
        path=path,
        status=status,
        marking_interpretation=f"原始释义：{path}",
        compressed_definition=f"压缩释义：{path}",
    )


class KnowledgeTaxonomyTreeTests(unittest.TestCase):
    def test_tree_uses_active_terminal_paths_and_keeps_real_other_distinct_from_control_token(self):
        self.assertTrue(callable(KnowledgeTaxonomyTree), "KnowledgeTaxonomyTree must be implemented")
        rulebook = KnowledgeRulebook(
            records={
                "知识点->其他": record("知识点->其他"),
                "知识点->词法->冠词->a/an的区别": record("知识点->词法->冠词->a/an的区别"),
                "知识点->词法->冠词->the的用法": record("知识点->词法->冠词->the的用法"),
                "知识点->词法->冠词->旧标签": record("知识点->词法->冠词->旧标签", status="deprecated"),
            }
        )

        tree = KnowledgeTaxonomyTree.from_rulebook(rulebook)

        self.assertEqual(tree.root_candidates(("知识点->词法",)), ("知识点->词法",))
        self.assertIn("知识点->其他", tree.children("知识点"))
        self.assertNotIn(NO_MATCH, tree.children("知识点"))
        self.assertEqual(
            tree.children("知识点->词法->冠词"),
            (
                "知识点->词法->冠词->a/an的区别",
                "知识点->词法->冠词->the的用法",
            ),
        )
        self.assertTrue(tree.is_terminal("知识点->词法->冠词->a/an的区别"))
        self.assertFalse(tree.is_terminal("知识点->词法->冠词"))
        self.assertEqual(
            tree.definition("知识点->词法->冠词->a/an的区别"),
            "压缩释义：知识点->词法->冠词->a/an的区别",
        )

    def test_tree_rejects_a_policy_prefix_that_is_not_a_taxonomy_node(self):
        self.assertTrue(callable(KnowledgeTaxonomyTree), "KnowledgeTaxonomyTree must be implemented")
        tree = KnowledgeTaxonomyTree.from_rulebook(
            KnowledgeRulebook(records={"知识点->词法->冠词": record("知识点->词法->冠词")})
        )

        with self.assertRaisesRegex(ValueError, "not in taxonomy"):
            tree.root_candidates(("知识点->杜撰",))


if __name__ == "__main__":
    unittest.main()
