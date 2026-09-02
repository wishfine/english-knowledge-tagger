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


if __name__ == "__main__":
    unittest.main()
