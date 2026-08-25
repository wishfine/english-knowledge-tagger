from pathlib import Path
import unittest

try:
    from english_knowledge_tagger.knowledge_candidate_policy import (
        load_knowledge_candidate_policy,
    )
except ModuleNotFoundError:
    load_knowledge_candidate_policy = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class KnowledgeCandidatePolicyConfigTests(unittest.TestCase):
    def test_child_knowledge_presence_v01_encodes_only_confirmed_exact_routes(self):
        self.assertTrue(callable(load_knowledge_candidate_policy))
        policy = load_knowledge_candidate_policy(
            PROJECT_ROOT / "configs" / "knowledge_candidate_policies" / "child-knowledge-presence-v0.1.json"
        )

        expected = {
            ("child", "复合题", "语法选择"): "required",
            ("child", "完形填空", "语法选择"): "required",
            ("child", "复合题", "完形填空"): "forbidden",
            ("child", "完形填空", "完形填空"): "forbidden",
            ("child", "复合题", "阅读理解"): "forbidden",
        }
        self.assertEqual(
            {key: rule.knowledge_policy for key, rule in policy.rules.items()},
            expected,
        )


if __name__ == "__main__":
    unittest.main()
