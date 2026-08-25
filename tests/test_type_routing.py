import json
from pathlib import Path
import tempfile
import unittest

try:
    from english_knowledge_tagger.type_routing import (
        bootstrap_type_routing_policy,
        load_type_routing_policy,
    )
except ModuleNotFoundError:
    bootstrap_type_routing_policy = None
    load_type_routing_policy = None


RULE = {
    "rule_id": "route:child:复合题:阅读理解",
    "scope": "child",
    "declared_type_structure": "复合题",
    "declared_type_name": "阅读理解",
    "policy_status": "needs_review",
    "canonical_family": "reading",
    "type_selection_mode": "single",
    "candidate_type_prefixes": ["题型->阅读理解"],
    "knowledge_inheritance": "never",
    "knowledge_policy": "unresolved",
    "review_notes": "需要按小题内容细分阅读选择、问答等。",
}


def write_policy(path: Path, rules: list[dict[str, object]]) -> Path:
    path.write_text(
        json.dumps(
            {"schema_version": "type-routing-policy-v1", "rules": rules},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


class TypeRoutingPolicyTests(unittest.TestCase):
    def test_policy_rejects_duplicate_exact_keys_and_approved_rules_without_candidates(self):
        self.assertTrue(callable(load_type_routing_policy), "load_type_routing_policy must be implemented")
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            duplicate = write_policy(directory / "duplicate.json", [RULE, RULE])
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_type_routing_policy(duplicate)

            invalid = write_policy(
                directory / "invalid.json",
                [{**RULE, "policy_status": "approved", "candidate_type_prefixes": []}],
            )
            with self.assertRaisesRegex(ValueError, "approved"):
                load_type_routing_policy(invalid)

    def test_bootstrap_creates_one_unmapped_rule_for_each_inventory_key(self):
        self.assertTrue(
            callable(bootstrap_type_routing_policy),
            "bootstrap_type_routing_policy must be implemented",
        )
        policy = bootstrap_type_routing_policy(
            {
                "rows": [
                    {
                        "scope": "child",
                        "declared_type_structure": "复合题",
                        "declared_type_name": "阅读理解",
                    },
                    {
                        "scope": "parent",
                        "declared_type_structure": "单选题",
                        "declared_type_name": "选择题",
                    },
                ]
            }
        )

        self.assertEqual(policy["schema_version"], "type-routing-policy-v1")
        self.assertEqual(
            [rule["scope"] for rule in policy["rules"]],
            ["parent", "child"],
        )
        self.assertEqual(policy["rules"][1]["policy_status"], "unmapped")
        self.assertEqual(policy["rules"][1]["knowledge_inheritance"], "never")
        self.assertEqual(policy["rules"][1]["candidate_type_prefixes"], [])

    def test_policy_matches_only_the_exact_scope_structure_and_name(self):
        self.assertTrue(callable(load_type_routing_policy), "load_type_routing_policy must be implemented")
        with tempfile.TemporaryDirectory() as temp_dir:
            policy = load_type_routing_policy(write_policy(Path(temp_dir) / "policy.json", [RULE]))

        self.assertEqual(
            policy.match("child", "复合题", "阅读理解").rule_id,
            "route:child:复合题:阅读理解",
        )
        self.assertIsNone(policy.match("parent", "复合题", "阅读理解"))
        self.assertIsNone(policy.match("child", "复合题", "阅读还原"))


if __name__ == "__main__":
    unittest.main()
