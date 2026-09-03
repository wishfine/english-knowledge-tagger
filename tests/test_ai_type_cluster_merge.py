import json
import unittest

from english_knowledge_tagger.ai_type_cluster_merge import (
    AIClusterMergeClient,
    build_cluster_merge_prompt,
    materialize_ai_clusters,
    parse_cluster_merge_response,
)
from english_knowledge_tagger.type_reclassification import (
    QuestionTypeServiceConfig,
    QuestionTypeServiceError,
    StreamCompletion,
)


def base_cluster(base_id, label, mechanism, count=1):
    return {
        "base_cluster_id": base_id,
        "candidate_label_counts": {label: count},
        "canonical_task_mechanism": mechanism,
        "local_candidate_type_label": label,
        "member_count": count,
        "representative_question_ids": [base_id],
        "source_type_label": "题型@听力理解@听力匹配",
    }


class AITypeClusterMergeTests(unittest.TestCase):
    def setUp(self):
        self.base_clusters = [
            base_cluster("BASE-1", "听句子选图片", "听句子并匹配图片", 3),
            base_cluster("BASE-2", "听对话选图片", "听对话并匹配图片", 2),
            base_cluster("BASE-3", "听力排序", "听短文并排列图片", 1),
        ]

    def test_prompt_contains_only_compact_base_cluster_fields(self):
        prompt = build_cluster_merge_prompt(
            "统一规则",
            source_type_label="题型@听力理解@听力匹配",
            granularity_guidance="不按图片和人物拆分",
            base_clusters=self.base_clusters,
        )

        self.assertIn("BASE-1", prompt)
        self.assertIn("不按图片和人物拆分", prompt)
        self.assertNotIn("representative_question_ids", prompt)
        self.assertNotIn("local_candidate_type_label", prompt)

    def test_prompt_does_not_require_label_specific_guidance(self):
        prompt = build_cluster_merge_prompt(
            "统一方法论",
            source_type_label="题型@任意原标签",
            base_clusters=self.base_clusters,
        )

        self.assertIn("题型@任意原标签", prompt)
        self.assertNotIn("granularity_guidance", prompt)

    def test_response_must_partition_every_base_cluster_exactly_once(self):
        valid = {
            "clusters": [
                {
                    "canonical_type_label": "听力匹配",
                    "canonical_task_mechanism": "听取音频并完成匹配",
                    "decision_status": "candidate",
                    "base_cluster_ids": ["BASE-1", "BASE-2"],
                },
                {
                    "canonical_type_label": "听力排序",
                    "canonical_task_mechanism": "听取音频并排序",
                    "decision_status": "candidate",
                    "base_cluster_ids": ["BASE-3"],
                },
            ]
        }
        parsed = parse_cluster_merge_response(
            json.dumps(valid, ensure_ascii=False),
            expected_base_cluster_ids={"BASE-1", "BASE-2", "BASE-3"},
        )
        self.assertEqual(len(parsed), 2)

        valid["clusters"][1]["base_cluster_ids"] = ["BASE-2"]
        with self.assertRaisesRegex(
            QuestionTypeServiceError, "assigned more than once"
        ):
            parse_cluster_merge_response(
                json.dumps(valid, ensure_ascii=False),
                expected_base_cluster_ids={"BASE-1", "BASE-2", "BASE-3"},
            )

    def test_streaming_client_and_materialization_are_merge_only(self):
        requests = []

        def transport(endpoint, payload, timeout_seconds, headers):
            requests.append((endpoint, payload, timeout_seconds, headers))
            return StreamCompletion(
                request_id="request-1",
                model="DeepSeek-V4-Flash",
                content=json.dumps(
                    {
                        "clusters": [
                            {
                                "canonical_type_label": "听力匹配",
                                "canonical_task_mechanism": "听取音频并完成匹配",
                                "decision_status": "candidate",
                                "base_cluster_ids": ["BASE-1", "BASE-2"],
                            },
                            {
                                "canonical_type_label": "听力排序",
                                "canonical_task_mechanism": "听取音频并排序",
                                "decision_status": "candidate",
                                "base_cluster_ids": ["BASE-3"],
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
            )

        client = AIClusterMergeClient(
            QuestionTypeServiceConfig(endpoint="http://example.test", max_tokens=4096),
            base_prompt="统一规则",
            transport=transport,
        )
        result = client.merge(
            source_type_label="题型@听力理解@听力匹配",
            granularity_guidance="不按图片和人物拆分",
            base_clusters=self.base_clusters,
        )
        clusters, base_to_final = materialize_ai_clusters(
            source_type_label="题型@听力理解@听力匹配",
            base_clusters=self.base_clusters,
            decisions=result.decisions,
        )

        self.assertTrue(requests[0][1]["stream"])
        self.assertEqual(requests[0][1]["max_tokens"], 4096)
        self.assertEqual(len(clusters), 2)
        self.assertEqual(base_to_final["BASE-1"], base_to_final["BASE-2"])
        self.assertNotEqual(base_to_final["BASE-1"], base_to_final["BASE-3"])
        self.assertEqual(sum(cluster["member_count"] for cluster in clusters), 6)


if __name__ == "__main__":
    unittest.main()
