import json
import tempfile
import unittest
from pathlib import Path

from english_knowledge_tagger.global_type_merge import (
    GlobalTypeMergeError,
    build_global_merge_packet,
    materialize_global_merge,
    write_global_merge_packet,
)


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class GlobalTypeMergeTests(unittest.TestCase):
    def test_packet_flattens_candidates_and_keeps_unresolved_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_json(
                root / "progress.json",
                {
                    "completed_labels": [
                        {"label_index": 9, "decision_path": "标签B/decisions.json"},
                        {"label_index": 2, "decision_path": "标签A/decisions.json"},
                    ]
                },
            )
            for label, index in (("标签B", 9), ("标签A", 2)):
                write_json(
                    root / label / "decisions.json",
                    {
                        "source_type_label": label,
                        "source_label_index": index,
                        "clusters": [
                            {
                                "canonical_type_label": "听力匹配题",
                                "canonical_task_mechanism": "听录音后完成匹配",
                                "decision_status": "candidate",
                                "base_cluster_ids": [f"BASE-{index}"],
                                "member_count": index,
                            },
                            {
                                "canonical_type_label": "小簇",
                                "canonical_task_mechanism": "独立机制",
                                "decision_status": "unresolved",
                                "base_cluster_ids": [f"BASE-U{index}"],
                                "member_count": 1,
                            },
                        ],
                    },
                )
            packet = build_global_merge_packet(root, progress_path=root / "progress.json")
            self.assertEqual(packet["report"]["candidate_cluster_count"], 2)
            self.assertEqual(packet["report"]["unresolved_cluster_count"], 2)
            self.assertEqual(packet["candidate_clusters"][0]["member_count"], 9)
            self.assertNotIn("source_type_label", packet["candidate_clusters"][0])
            self.assertEqual(len(packet["provenance"]), 2)

    def test_materialize_requires_every_candidate_to_be_assigned_once(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            packet = {
                "candidate_clusters": [
                    {
                        "global_input_id": "LOCAL-000001",
                        "canonical_type_label": "听力匹配题",
                        "canonical_task_mechanism": "听录音后完成匹配",
                        "member_count": 3,
                    }
                ],
                "provenance": [
                    {
                        "global_input_id": "LOCAL-000001",
                        "source_type_label": "旧标签",
                        "base_cluster_ids": ["BASE-1"],
                    }
                ],
                "unresolved_clusters": [],
            }
            packet_path = root / "packet.json"
            decisions_path = root / "decisions.json"
            write_json(packet_path, packet)
            write_json(
                decisions_path,
                {
                    "groups": [
                        {
                            "global_cluster_id": "GLOBAL-0001",
                            "canonical_type_label": "听力匹配题",
                            "canonical_task_mechanism": "听录音后完成匹配",
                            "member_cluster_ids": ["LOCAL-000001"],
                            "merge_reason": "核心机制一致",
                        }
                    ]
                },
            )
            output = root / "output"
            report = materialize_global_merge(packet_path, decisions_path, output)
            self.assertEqual(report["global_cluster_count"], 1)
            self.assertTrue((output / "global-clusters.json").exists())
            members = (output / "global-cluster-members.jsonl").read_text(encoding="utf-8")
            self.assertIn('"member_count": 3', members)

            write_json(decisions_path, {"groups": []})
            with self.assertRaises(GlobalTypeMergeError):
                materialize_global_merge(packet_path, decisions_path, root / "output-again")


if __name__ == "__main__":
    unittest.main()
