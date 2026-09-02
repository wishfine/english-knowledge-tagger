import importlib.util
import unittest

from english_knowledge_tagger.local_type_clustering import (
    cluster_local_results,
    normalize_candidate_label,
    safe_label_directory_name,
)


SKLEARN_AVAILABLE = importlib.util.find_spec("sklearn") is not None


def result_row(index, label, mechanism, *, confidence=0.95, sufficiency="sufficient"):
    return {
        "question_id": str(index),
        "source_line": index,
        "input": f"题目 {index}",
        "candidate_type_label": label,
        "task_mechanism": mechanism,
        "key_evidence": ["题面证据"],
        "information_sufficiency": sufficiency,
        "confidence": confidence,
        "status": "candidate",
    }


class LocalTypeClusteringTests(unittest.TestCase):
    def test_candidate_label_surface_normalization_is_conservative(self):
        self.assertEqual(normalize_candidate_label("书面表达（日记）"), "日记写作")
        self.assertEqual(normalize_candidate_label("英语邮件写作"), "电子邮件写作")
        self.assertEqual(normalize_candidate_label("电子邮件写作"), "电子邮件写作")
        self.assertEqual(normalize_candidate_label("命题作文"), "命题写作")

    def test_source_label_directory_keeps_label_and_escapes_slash(self):
        label = "题型@完形填空@词性@完形：动词/动词短语"
        self.assertEqual(
            safe_label_directory_name(label),
            "题型@完形填空@词性@完形：动词／动词短语",
        )

    @unittest.skipUnless(SKLEARN_AVAILABLE, "scikit-learn is optional")
    def test_clusters_similar_labels_and_keeps_different_mechanisms_apart(self):
        rows = [
            result_row(1, "电子邮件写作", "根据交际情境和要点撰写电子邮件"),
            result_row(2, "邮件写作", "根据题目要求写一封电子邮件"),
            result_row(3, "书面表达（邮件）", "根据给出的信息回复电子邮件"),
            result_row(4, "日记写作", "根据一天的经历撰写日记"),
            result_row(5, "书面表达（日记）", "按日记格式记录一天的活动"),
            result_row(
                6,
                "无法判断题型",
                "题面信息不足",
                confidence=0.2,
                sufficiency="insufficient",
            ),
        ]

        result = cluster_local_results(
            rows,
            source_type_label="测试标签",
            local_distance_threshold=0.6,
        )

        cluster_names = {cluster["local_candidate_type_label"] for cluster in result["clusters"]}
        self.assertIn("电子邮件写作", cluster_names)
        self.assertIn("日记写作", cluster_names)
        self.assertEqual(result["report"]["clustered_rows"], 5)
        self.assertEqual(result["report"]["outlier_rows"], 1)

    @unittest.skipUnless(SKLEARN_AVAILABLE, "scikit-learn is optional")
    def test_high_confidence_partial_row_is_core(self):
        rows = [
            result_row(
                1,
                "听句子选图片",
                "听句子，从图片中选择与内容相符的图片",
                confidence=0.85,
                sufficiency="partial",
            ),
            result_row(
                2,
                "听力图片匹配",
                "听录音，从图片选项中匹配与内容对应的图片",
                confidence=0.85,
                sufficiency="partial",
            ),
        ]

        result = cluster_local_results(rows, source_type_label="听力测试")

        self.assertEqual(result["report"]["core_rows"], 2)
        self.assertEqual(result["report"]["auxiliary_rows"], 0)
        self.assertEqual(result["report"]["clustered_rows"], 2)

    @unittest.skipUnless(SKLEARN_AVAILABLE, "scikit-learn is optional")
    def test_cluster_status_reflects_member_count(self):
        rows = [
            *[
                result_row(index, "电子邮件写作", "根据要点撰写电子邮件")
                for index in range(1, 6)
            ],
            *[
                result_row(index, "日记写作", "记录一天经历并写成日记")
                for index in range(6, 9)
            ],
            result_row(9, "听力图片排序", "听短文并按顺序排列图片"),
        ]

        result = cluster_local_results(
            rows,
            source_type_label="簇状态测试",
            local_distance_threshold=0.2,
        )

        status_by_size = {
            cluster["member_count"]: cluster["cluster_status"]
            for cluster in result["clusters"]
        }
        self.assertEqual(status_by_size, {5: "stable", 3: "micro", 1: "unresolved"})
        self.assertEqual(result["report"]["stable_cluster_count"], 1)
        self.assertEqual(result["report"]["micro_cluster_count"], 1)
        self.assertEqual(result["report"]["unresolved_cluster_count"], 1)
        self.assertEqual(result["report"]["unresolved_row_count"], 1)

    @unittest.skipUnless(SKLEARN_AVAILABLE, "scikit-learn is optional")
    def test_same_normalized_candidate_label_is_never_split(self):
        rows = [
            result_row(1, "听力匹配题", "听句子并匹配图片"),
            result_row(2, "听力匹配题", "听独白并匹配人物信息"),
            result_row(3, "听力匹配题", "听对话并匹配地点"),
        ]

        result = cluster_local_results(rows, source_type_label="听力匹配")

        self.assertEqual(result["report"]["candidate_label_group_count"], 1)
        self.assertEqual(result["report"]["cluster_count"], 1)
        self.assertEqual(result["clusters"][0]["member_count"], 3)
        self.assertEqual(result["clusters"][0]["candidate_label_group_count"], 1)

    @unittest.skipUnless(SKLEARN_AVAILABLE, "scikit-learn is optional")
    def test_mechanism_dominant_group_features_merge_different_major_type_names(self):
        rows = [
            result_row(1, "听力图片匹配题", "听录音，根据内容选择对应图片完成匹配"),
            result_row(2, "听句子选图", "听录音，根据句子选择对应图片完成匹配"),
            result_row(3, "听力匹配题", "听录音，根据内容选择对应选项完成匹配"),
            result_row(4, "语法填空", "根据句子语境填写单词的正确形式"),
        ]

        result = cluster_local_results(
            rows,
            source_type_label="机制主导测试",
            candidate_label_weight=0.2,
            task_mechanism_weight=0.8,
        )

        cluster_sizes = sorted(
            (cluster["member_count"] for cluster in result["clusters"]), reverse=True
        )
        self.assertEqual(cluster_sizes, [3, 1])
        self.assertEqual(result["clusters"][0]["candidate_label_group_count"], 3)
        self.assertEqual(
            result["report"]["parameters"]["group_feature_block_normalization"],
            "l2-before-weighting",
        )


if __name__ == "__main__":
    unittest.main()
