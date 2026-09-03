import json
import unittest

from english_knowledge_tagger.pairwise_type_clustering import (
    PairwiseTypeClient,
    build_naming_prompt,
    build_pair_prompt,
    make_local_cluster_id,
    parse_pair_response,
    strict_complete_link_groups,
)
from english_knowledge_tagger.type_reclassification import (
    QuestionTypeServiceConfig,
    QuestionTypeServiceError,
    StreamCompletion,
)


def base(base_id, label, mechanism, count=100):
    return {
        "base_cluster_id": base_id,
        "source_type_label": "题型@旧标签",
        "member_count": count,
        "candidate_label_counts": {label: count},
        "canonical_task_mechanism": mechanism,
        "representative_question_ids": [base_id],
    }


def decision(same, confidence=0.95):
    return {
        "same_type": same,
        "same_primary_operation": same,
        "same_answer_generation": same,
        "same_required_support": same,
        "confidence": confidence,
    }


class PairwiseTypeClusteringTests(unittest.TestCase):
    def setUp(self):
        self.left = base("BASE-A", "语法填空", "阅读语篇并填写词形", 846)
        self.right = base("BASE-B", "单词拼写", "根据首字母填写单词", 10)

    def test_pair_prompt_hides_old_label_counts_and_previous_grouping(self):
        prompt = build_pair_prompt("统一判断", self.left, self.right)

        self.assertIn("BASE-A", prompt)
        self.assertIn("语法填空", prompt)
        self.assertNotIn("题型@旧标签", prompt)
        self.assertNotIn("member_count", prompt)
        self.assertNotIn("candidate_label_counts", prompt)
        self.assertNotIn("846", prompt)
        self.assertNotIn("initial_clusters", prompt)

    def test_pair_parser_requires_exact_boolean_dimensions(self):
        parsed = parse_pair_response(json.dumps(decision(False)))
        self.assertFalse(parsed["same_type"])

        invalid = decision(True)
        invalid["reason"] = "extra"
        with self.assertRaises(QuestionTypeServiceError):
            parse_pair_response(json.dumps(invalid))

    def test_complete_link_prevents_transitive_chain_merge(self):
        decisions = {
            ("A", "B"): decision(True, 0.95),
            ("A", "C"): decision(False, 0.99),
            ("B", "C"): decision(True, 0.90),
        }

        groups = strict_complete_link_groups(
            ["A", "B", "C"], decisions, min_confidence=0.8
        )

        self.assertEqual(groups, [["A", "B"], ["C"]])

    def test_low_confidence_pair_stays_separate(self):
        groups = strict_complete_link_groups(
            ["A", "B"], {("A", "B"): decision(True, 0.79)}, min_confidence=0.8
        )
        self.assertEqual(groups, [["A"], ["B"]])

    def test_naming_prompt_keeps_membership_fixed_and_hides_counts(self):
        groups = [["BASE-A"], ["BASE-B"]]
        prompt = build_naming_prompt(
            "只命名", groups=groups, base_clusters=[self.left, self.right]
        )

        self.assertIn(make_local_cluster_id(["BASE-A"]), prompt)
        self.assertNotIn("member_count", prompt)
        self.assertNotIn("846", prompt)
        self.assertNotIn("题型@旧标签", prompt)

    def test_client_uses_streaming_requests(self):
        requests = []

        def transport(endpoint, payload, timeout_seconds, headers):
            requests.append(payload)
            return StreamCompletion(
                request_id="request-1",
                model="DeepSeek-V4-Flash",
                content=json.dumps(decision(False)),
            )

        client = PairwiseTypeClient(
            QuestionTypeServiceConfig(endpoint="http://example.test", max_tokens=256),
            pair_prompt="统一判断",
            naming_prompt="只命名",
            transport=transport,
        )
        result = client.compare(self.left, self.right)

        self.assertFalse(result.decision["same_type"])
        self.assertTrue(requests[0]["stream"])
        self.assertEqual(requests[0]["max_tokens"], 256)


if __name__ == "__main__":
    unittest.main()
