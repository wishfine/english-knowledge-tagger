import json
from pathlib import Path
import tempfile
import unittest

try:
    from english_knowledge_tagger.knowledge_candidate_policy import load_knowledge_candidate_policy
    from english_knowledge_tagger.knowledge_rulebook import (
        KnowledgeRulebook,
        KnowledgeRulebookRecord,
    )
    from english_knowledge_tagger.knowledge_taxonomy_tree import KnowledgeTaxonomyTree
    from english_knowledge_tagger.knowledge_tree_search import TreeChoice
    from english_knowledge_tagger.knowledge_tree_tasks import (
        build_knowledge_tree_tasks,
        route_knowledge_tree_task,
    )
except ModuleNotFoundError:
    load_knowledge_candidate_policy = None
    KnowledgeRulebook = None
    KnowledgeRulebookRecord = None
    KnowledgeTaxonomyTree = None
    TreeChoice = None
    build_knowledge_tree_tasks = None
    route_knowledge_tree_task = None


GRAMMAR_ROUTE = {
    "scope": "child",
    "declared_type_structure": "复合题",
    "declared_type_name": "语法选择",
    "knowledge_policy": "required",
    "allowed_knowledge_prefixes": ["知识点->词法"],
    "max_retrieved_candidates": 12,
    "max_sibling_candidates": 8,
    "max_output_labels": 3,
}


def _jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
    return path


def _policy(path: Path) -> Path:
    path.write_text(
        json.dumps({"schema_version": "knowledge-candidate-policy-v1", "rules": [GRAMMAR_ROUTE]}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _route_key() -> dict[str, str]:
    return {
        "scope": "child",
        "declared_type_structure": "复合题",
        "declared_type_name": "语法选择",
    }


class _ChoiceClient:
    def __init__(self, choices: list[str]):
        self._choices = iter(choices)
        self.requests = []

    def choose(self, request):
        self.requests.append(request)
        return TreeChoice(
            choice=next(self._choices),
            candidate_coverage="covered",
            evidence="umbrella",
            raw_response="{}",
        )


class KnowledgeTreeTasksTests(unittest.TestCase):
    def test_builder_groups_replace_and_required_missing_label_by_source_line(self):
        self.assertTrue(callable(build_knowledge_tree_tasks), "build_knowledge_tree_tasks must be implemented")
        self.assertTrue(callable(load_knowledge_candidate_policy))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = _jsonl(
                directory / "source.jsonl",
                [
                    {
                        "question_id": "child-replace",
                        "is_sub_question": True,
                        "input": "题型结构为：复合题\n题型名称为：语法选择\n题干：It is ___ umbrella. 答案：an。",
                        "output": "知识点@词法@冠词@the的用法",
                    },
                    {
                        "question_id": "child-add",
                        "is_sub_question": True,
                        "input": "题型结构为：复合题\n题型名称为：语法选择\n题干：It is ___ umbrella. 答案：an。",
                        "output": "题型@特殊题型@语法选择",
                    },
                ],
            )
            review = _jsonl(
                directory / "review.jsonl",
                [
                    {"source_line": 1, "route_key": _route_key()},
                    {"source_line": 2, "route_key": _route_key()},
                ],
            )
            packet = _jsonl(
                directory / "packet.jsonl",
                [
                    {
                        "review_id": "kp-validation:child-replace:the",
                        "source_line": 1,
                        "question_id": "child-replace",
                    }
                ],
            )
            verdicts = _jsonl(
                directory / "verdicts.jsonl",
                [
                    {
                        "review_id": "kp-validation:child-replace:the",
                        "source_line": 1,
                        "status": "candidate",
                        "validation": {
                            "verdict": "replace",
                            "candidate_coverage": "covered",
                            "best_label": "知识点->词法->冠词->a/an的区别",
                        },
                    }
                ],
            )
            output = directory / "tasks.jsonl"
            report = build_knowledge_tree_tasks(
                source,
                review_packet_path=review,
                validation_packet_path=packet,
                validation_verdict_path=verdicts,
                candidate_policy=load_knowledge_candidate_policy(_policy(directory / "policy.json")),
                output_path=output,
            )
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["trigger_kinds"], ["replace"])
        self.assertEqual(rows[1]["trigger_kinds"], ["add_missing_required"])
        self.assertNotIn("题型结构为：", rows[0]["question_context"])
        self.assertNotIn("题型名称为：", rows[0]["question_context"])
        self.assertEqual(report["replace_triggers"], 1)
        self.assertEqual(report["add_missing_required_triggers"], 1)

    def test_router_writes_a_terminal_candidate_and_trace_without_flat_validator(self):
        self.assertTrue(callable(route_knowledge_tree_task), "route_knowledge_tree_task must be implemented")
        label = "知识点->词法->冠词->a/an的区别"
        tree = KnowledgeTaxonomyTree.from_rulebook(
            KnowledgeRulebook(
                records={
                    label: KnowledgeRulebookRecord(
                        path=label,
                        status="active",
                        marking_interpretation="a/an",
                        compressed_definition="a/an",
                    )
                }
            )
        )
        client = _ChoiceClient(["知识点->词法", "知识点->词法->冠词", label])

        result = route_knowledge_tree_task(
            {
                "task_id": "kp-tree:child-1",
                "question_context": "题干：It is ___ umbrella. 答案：an。",
                "allowed_knowledge_prefixes": ["知识点->词法"],
            },
            client=client,
            tree=tree,
        )

        self.assertEqual(result["status"], "tree_candidate")
        self.assertEqual(result["candidate_label"], label)
        self.assertEqual(len(result["trace"]), 3)
        self.assertEqual(len(client.requests), 3)
        self.assertGreaterEqual(result["task_elapsed_ms"], 0.0)


if __name__ == "__main__":
    unittest.main()
