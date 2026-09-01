import csv
from pathlib import Path
import tempfile
import unittest

from english_knowledge_tagger.candidate_labeling import LabelingServiceConfig
from english_knowledge_tagger.dynamic_leaf_routing import (
    BACKTRACK,
    HOLD,
    MORE,
    DynamicLeafChoice,
    DynamicLeafChoiceClient,
    build_dynamic_leaf_neighborhood,
    build_dynamic_leaf_choice_prompt,
    page_dynamic_leaf_neighborhood,
    resolve_dynamic_leaf,
    search_dynamic_tree_candidate,
)
from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook
from english_knowledge_tagger.knowledge_taxonomy_tree import KnowledgeTaxonomyTree
from english_knowledge_tagger.knowledge_tree_search import TreeChoice


class DynamicLeafRoutingTests(unittest.TestCase):
    def _rulebook(self, root: Path):
        teacher = root / "teacher.csv"
        rows = [
            ("知识点->语用->社会交往->争辩", "反驳或争论"),
            ("知识点->语用->社会交往->描述", "描述信息"),
            ("知识点->语用->社会交往->介绍", "介绍身份"),
            ("知识点->语用->社会交往->询问", "询问信息"),
            ("知识点->语用->情感->责备", "批评责备"),
            ("知识点->语用->时间->顺序", "事件先后顺序"),
            ("知识点->其他", "新题不再打"),
        ]
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
            for label, definition in rows:
                writer.writerow(
                    {
                        "末级知识点": label,
                        "打标解读（标绿的标签，新题不再打）": definition,
                        "大模型压缩+人工微调的释义": definition,
                    }
                )
        return load_knowledge_rulebook(teacher)

    def test_neighborhood_prioritizes_confusion_then_sibling_route_and_similarity(self):
        with tempfile.TemporaryDirectory() as directory:
            rulebook = self._rulebook(Path(directory))
            neighborhood = build_dynamic_leaf_neighborhood(
                rulebook,
                target_label="知识点->语用->社会交往->争辩",
                question_text="题目要求描述一个人的信息",
                confusion_counts={
                    "知识点->语用->情感->责备": 9,
                    "知识点->语用->社会交往->描述": 4,
                },
                soft_route_compatible={"知识点->语用->时间->顺序"},
                hard_excluded=frozenset(),
                max_neighbors=6,
            )
            self.assertEqual(neighborhood.candidates[0].label, "知识点->语用->情感->责备")
            self.assertEqual(neighborhood.candidates[1].label, "知识点->语用->社会交往->描述")
            self.assertNotIn(
                "知识点->语用->社会交往->争辩",
                {candidate.label for candidate in neighborhood.candidates},
            )
            self.assertNotIn(
                "知识点->其他", {candidate.label for candidate in neighborhood.candidates}
            )
            self.assertIn("confusion", neighborhood.candidates[0].sources)
            self.assertIn("direct_sibling", neighborhood.candidates[1].sources)

    def test_hard_exclusion_removes_candidate_but_soft_route_only_changes_rank(self):
        with tempfile.TemporaryDirectory() as directory:
            rulebook = self._rulebook(Path(directory))
            neighborhood = build_dynamic_leaf_neighborhood(
                rulebook,
                target_label="知识点->语用->社会交往->争辩",
                question_text="先后顺序",
                confusion_counts={},
                soft_route_compatible={"知识点->语用->时间->顺序"},
                hard_excluded=frozenset({"知识点->语用->社会交往->描述"}),
            )
            labels = {candidate.label for candidate in neighborhood.candidates}
            self.assertNotIn("知识点->语用->社会交往->描述", labels)
            self.assertIn("知识点->语用->时间->顺序", labels)

    def test_direct_sibling_mode_does_not_add_cross_parent_escape_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            rulebook = self._rulebook(Path(directory))
            neighborhood = build_dynamic_leaf_neighborhood(
                rulebook,
                target_label="知识点->语用->社会交往->争辩",
                question_text="责备后再说明事件顺序",
                confusion_counts={"知识点->语用->情感->责备": 10},
                soft_route_compatible={"知识点->语用->时间->顺序"},
                include_escape_candidates=False,
            )
            self.assertEqual(
                {candidate.label for candidate in neighborhood.candidates},
                {
                    "知识点->语用->社会交往->描述",
                    "知识点->语用->社会交往->介绍",
                    "知识点->语用->社会交往->询问",
                },
            )

    def test_pagination_exposes_distinct_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            rulebook = self._rulebook(Path(directory))
            neighborhood = build_dynamic_leaf_neighborhood(
                rulebook,
                target_label="知识点->语用->社会交往->争辩",
                question_text="普通问题",
                confusion_counts={},
                soft_route_compatible=set(),
            )
            first = page_dynamic_leaf_neighborhood(neighborhood, cursor=0, page_size=2)
            self.assertEqual(first.controls, (MORE, BACKTRACK, HOLD))
            last = page_dynamic_leaf_neighborhood(
                neighborhood,
                cursor=len(neighborhood.candidates) - 1,
                page_size=2,
            )
            self.assertEqual(last.controls, (BACKTRACK, HOLD))
            self.assertEqual(len({MORE, BACKTRACK, HOLD}), 3)

    def test_resolver_expands_more_and_returns_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            rulebook = self._rulebook(Path(directory))
            neighborhood = build_dynamic_leaf_neighborhood(
                rulebook,
                target_label="知识点->语用->社会交往->争辩",
                question_text="普通问题",
                confusion_counts={},
                soft_route_compatible=set(),
            )
            calls = []

            def choose(page):
                calls.append(page)
                if len(calls) == 1:
                    return DynamicLeafChoice(choice=MORE, evidence="需要更多候选")
                return DynamicLeafChoice(
                    choice=page.candidates[0].label, evidence="该候选直接解释答案"
                )

            result = resolve_dynamic_leaf(neighborhood, choose=choose, page_size=1)
            self.assertEqual(result.status, "candidate")
            self.assertEqual(result.candidate_label, calls[1].candidates[0].label)
            self.assertEqual(len(result.trace), 2)

    def test_prompt_contains_only_page_candidates_definitions_and_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            rulebook = self._rulebook(Path(directory))
            neighborhood = build_dynamic_leaf_neighborhood(
                rulebook,
                target_label="知识点->语用->社会交往->争辩",
                question_text="描述一个人",
                confusion_counts={},
                soft_route_compatible=set(),
            )
            page = page_dynamic_leaf_neighborhood(neighborhood, cursor=0, page_size=2)
            prompt = build_dynamic_leaf_choice_prompt(page, question_text="描述一个人")
            self.assertIn(page.candidates[0].definition, prompt)
            self.assertIn(BACKTRACK, prompt)
            self.assertIn(HOLD, prompt)
            self.assertNotIn("知识点->语用->社会交往->争辩", prompt)

    def test_client_parses_page_choice_and_disables_thinking(self):
        with tempfile.TemporaryDirectory() as directory:
            rulebook = self._rulebook(Path(directory))
            neighborhood = build_dynamic_leaf_neighborhood(
                rulebook,
                target_label="知识点->语用->社会交往->争辩",
                question_text="描述一个人",
                confusion_counts={},
                soft_route_compatible=set(),
            )
            page = page_dynamic_leaf_neighborhood(neighborhood, cursor=0, page_size=2)
            captured = {}

            def transport(endpoint, payload, timeout, headers):
                captured["payload"] = payload
                return {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"choice":"'
                                    + page.candidates[0].label
                                    + '","evidence":"直接解释答案"}'
                                )
                            }
                        }
                    ]
                }

            client = DynamicLeafChoiceClient(
                LabelingServiceConfig(endpoint="http://example.invalid"),
                transport=transport,
            )
            choice = client.choose(page, question_text="描述一个人")
            self.assertEqual(choice.choice, page.candidates[0].label)
            self.assertEqual(
                captured["payload"]["chat_template_kwargs"], {"enable_thinking": False}
            )

    def test_hybrid_search_backtracks_to_another_parent_branch(self):
        with tempfile.TemporaryDirectory() as directory:
            rulebook = self._rulebook(Path(directory))
            tree = KnowledgeTaxonomyTree.from_rulebook(rulebook)
            leaf_calls = []

            def choose_leaf(page):
                leaf_calls.append(page)
                if len(leaf_calls) == 1:
                    return DynamicLeafChoice(choice=BACKTRACK, evidence="社会交往均不适用")
                candidate = next(
                    item for item in page.candidates if item.label.endswith("时间->顺序")
                )
                return DynamicLeafChoice(choice=candidate.label, evidence="答案依赖事件先后")

            def choose_branch(request):
                choice = next(
                    path for path in request.candidate_paths if path.endswith("语用->时间")
                )
                return TreeChoice(
                    choice=choice,
                    candidate_coverage="covered",
                    evidence="属于时间语用",
                )

            result = search_dynamic_tree_candidate(
                tree,
                rulebook=rulebook,
                target_label="知识点->语用->社会交往->争辩",
                question_text="先做第一步，再完成第二步",
                confusion_counts={},
                soft_route_compatible=set(),
                choose_branch=choose_branch,
                choose_leaf=choose_leaf,
            )
            self.assertEqual(result.status, "candidate")
            self.assertEqual(result.candidate_label, "知识点->语用->时间->顺序")
            self.assertGreaterEqual(len(result.trace), 3)


if __name__ == "__main__":
    unittest.main()
