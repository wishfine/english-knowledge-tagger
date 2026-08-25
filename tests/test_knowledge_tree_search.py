import unittest

try:
    from english_knowledge_tagger.knowledge_rulebook import (
        KnowledgeRulebook,
        KnowledgeRulebookRecord,
    )
    from english_knowledge_tagger.knowledge_taxonomy_tree import NO_MATCH, KnowledgeTaxonomyTree
    from english_knowledge_tagger.knowledge_tree_search import (
        TreeChoice,
        search_one_candidate,
    )
except ModuleNotFoundError:
    KnowledgeRulebook = None
    KnowledgeRulebookRecord = None
    NO_MATCH = "__NO_MATCH__"
    KnowledgeTaxonomyTree = None
    TreeChoice = None
    search_one_candidate = None


def _record(path: str) -> object:
    return KnowledgeRulebookRecord(
        path=path,
        status="active",
        marking_interpretation=path,
        compressed_definition=path,
    )


def _tree() -> object:
    return KnowledgeTaxonomyTree.from_rulebook(
        KnowledgeRulebook(
            records={
                "知识点->词法->名词->可数名词": _record("知识点->词法->名词->可数名词"),
                "知识点->词法->冠词->a/an的区别": _record("知识点->词法->冠词->a/an的区别"),
            }
        )
    )


def _choices(*values: str):
    iterator = iter(values)

    def choose(_request):
        return TreeChoice(
            choice=next(iterator),
            candidate_coverage="covered",
            evidence="题干证据",
            raw_response="{}",
        )

    return choose


class KnowledgeTreeSearchTests(unittest.TestCase):
    def test_search_descends_to_a_terminal_leaf_without_backtracking(self):
        self.assertTrue(callable(search_one_candidate), "search_one_candidate must be implemented")

        result = search_one_candidate(
            _tree(),
            question_context="题干：...",
            allowed_prefixes=("知识点->词法",),
            choose=_choices("知识点->词法", "知识点->词法->名词", "知识点->词法->名词->可数名词"),
        )

        self.assertEqual(result.status, "tree_candidate")
        self.assertEqual(result.candidate_label, "知识点->词法->名词->可数名词")
        self.assertEqual(len(result.trace), 3)

    def test_no_match_backtracks_and_excludes_the_failed_child(self):
        self.assertTrue(callable(search_one_candidate), "search_one_candidate must be implemented")

        result = search_one_candidate(
            _tree(),
            question_context="题干：...",
            allowed_prefixes=("知识点->词法",),
            choose=_choices(
                "知识点->词法",
                "知识点->词法->名词",
                NO_MATCH,
                "知识点->词法->冠词",
                "知识点->词法->冠词->a/an的区别",
            ),
        )

        self.assertEqual(result.status, "tree_candidate")
        self.assertEqual(result.candidate_label, "知识点->词法->冠词->a/an的区别")
        self.assertEqual(result.trace[3]["excluded_paths"], ("知识点->词法->名词",))

    def test_root_no_match_returns_uncovered_not_an_empty_label(self):
        self.assertTrue(callable(search_one_candidate), "search_one_candidate must be implemented")

        result = search_one_candidate(
            _tree(),
            question_context="题干：...",
            allowed_prefixes=("知识点->词法",),
            choose=_choices(NO_MATCH),
        )

        self.assertEqual((result.status, result.candidate_label), ("uncovered", None))

    def test_search_stops_after_the_configured_backtrack_budget(self):
        self.assertTrue(callable(search_one_candidate), "search_one_candidate must be implemented")

        result = search_one_candidate(
            _tree(),
            question_context="题干：...",
            allowed_prefixes=("知识点->词法",),
            choose=_choices("知识点->词法", "知识点->词法->名词", NO_MATCH),
            max_backtracks=0,
        )

        self.assertEqual((result.status, result.candidate_label), ("budget_exhausted", None))


if __name__ == "__main__":
    unittest.main()
