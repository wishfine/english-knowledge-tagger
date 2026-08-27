import json
from pathlib import Path
import tempfile
import unittest

try:
    from english_knowledge_tagger.mentor_label_rollout_partition import (
        partition_mentor_label_rollout_packet,
    )
except ModuleNotFoundError:
    partition_mentor_label_rollout_packet = None


LABEL = "知识点@词汇@词汇辨析@名词（短语）辨析"


def packet_row(*, source_line: int, scope: str, structure: str, name: str) -> dict[str, object]:
    return {
        "schema_version": "mentor-label-rollout-packet-v1",
        "review_id": f"mentor-direct-v1:{source_line}:target",
        "source_line": source_line,
        "question_id": str(source_line),
        "parent_id": str(source_line),
        "is_sub_question": scope == "child",
        "verify_label": LABEL,
        "input": "题目题干",
        "output_all": LABEL,
        "route_key": {
            "scope": scope,
            "declared_type_structure": structure,
            "declared_type_name": name,
        },
    }


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def write_policy(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "terminal-label-rollout-route-policy-v1",
                "verify_label": LABEL,
                "prompt_version": "mentor-direct-v1",
                "eligible_routes": [
                    {
                        "scope": "parent",
                        "declared_type_structure": "单选题",
                        "declared_type_name": "选择题",
                    }
                ],
                "quarantine_reason": "outside_teacher_approved_non_composite_single_choice_route",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


class MentorLabelRolloutPartitionTests(unittest.TestCase):
    def test_partitioner_keeps_only_the_exact_human_approved_route(self):
        self.assertTrue(callable(partition_mentor_label_rollout_packet))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            packet = write_jsonl(
                directory / "full.packet.jsonl",
                [
                    packet_row(source_line=1, scope="parent", structure="单选题", name="选择题"),
                    packet_row(source_line=2, scope="parent", structure="复合题", name="翻译题"),
                    packet_row(source_line=3, scope="child", structure="复合题", name="语法选择"),
                ],
            )
            eligible = directory / "eligible.packet.jsonl"
            quarantine = directory / "quarantine.packet.jsonl"
            report = partition_mentor_label_rollout_packet(
                packet,
                policy_path=write_policy(directory / "policy.json"),
                eligible_output_path=eligible,
                quarantine_output_path=quarantine,
            )
            eligible_rows = [json.loads(line) for line in eligible.read_text(encoding="utf-8").splitlines()]
            quarantine_rows = [json.loads(line) for line in quarantine.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(report["eligible_records"], 1)
        self.assertEqual(report["quarantine_records"], 2)
        self.assertEqual(eligible_rows[0]["rollout_route_decision"], "eligible")
        self.assertEqual(quarantine_rows[0]["rollout_route_decision"], "quarantine")
        self.assertEqual(
            quarantine_rows[0]["rollout_route_reason"],
            "outside_teacher_approved_non_composite_single_choice_route",
        )

    def test_partitioner_rejects_packet_label_that_disagrees_with_policy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            row = packet_row(source_line=1, scope="parent", structure="单选题", name="选择题")
            row["verify_label"] = "知识点@词汇@固定搭配/句型"
            packet = write_jsonl(directory / "full.packet.jsonl", [row])
            with self.assertRaisesRegex(ValueError, "verify_label"):
                partition_mentor_label_rollout_packet(
                    packet,
                    policy_path=write_policy(directory / "policy.json"),
                    eligible_output_path=directory / "eligible.packet.jsonl",
                    quarantine_output_path=directory / "quarantine.packet.jsonl",
                )


if __name__ == "__main__":
    unittest.main()
