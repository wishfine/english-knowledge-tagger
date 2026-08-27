import json
from pathlib import Path
import tempfile
import unittest

from english_knowledge_tagger.mentor_label_rollout_partition import (
    partition_mentor_label_rollout_packet,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY_DIR = PROJECT_ROOT / "configs" / "terminal_label_rollout_policies"
POLICIES = (
    (
        "mentor-direct-v1-noun-discrimination-20260827.json",
        "知识点@词汇@词汇辨析@名词（短语）辨析",
    ),
    (
        "mentor-direct-v1-adverb-discrimination-20260827.json",
        "知识点@词汇@词汇辨析@副词（短语）辨析",
    ),
    (
        "mentor-direct-v1-verb-discrimination-20260827.json",
        "知识点@词汇@词汇辨析@动词（短语）辨析",
    ),
    (
        "mentor-direct-v1-adjective-discrimination-20260827.json",
        "知识点@词汇@词汇辨析@形容词（短语）辨析",
    ),
)


class TerminalLabelRolloutPolicyConfigTests(unittest.TestCase):
    def test_lexical_pos_configs_accept_only_non_composite_single_choice_parent_route(self):
        for policy_name, label in POLICIES:
            with self.subTest(policy=policy_name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    directory = Path(temp_dir)
                    packet = directory / "packet.jsonl"
                    packet.write_text(
                        json.dumps(
                            {
                                "schema_version": "mentor-label-rollout-packet-v1",
                                "review_id": "row-1",
                                "source_line": 1,
                                "verify_label": label,
                                "route_key": {
                                    "scope": "parent",
                                    "declared_type_structure": "单选题",
                                    "declared_type_name": "选择题",
                                },
                            },
                            ensure_ascii=False,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    report = partition_mentor_label_rollout_packet(
                        packet,
                        policy_path=POLICY_DIR / policy_name,
                        eligible_output_path=directory / "eligible.jsonl",
                        quarantine_output_path=directory / "quarantine.jsonl",
                    )

                self.assertEqual(report["eligible_records"], 1)
                self.assertEqual(report["quarantine_records"], 0)


if __name__ == "__main__":
    unittest.main()
