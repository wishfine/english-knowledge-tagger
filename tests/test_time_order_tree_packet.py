import json
from pathlib import Path
import tempfile
import unittest

from english_knowledge_tagger.time_order_tree_packet import build_time_order_tree_packet


LABEL = "知识点@语用@时间@顺序"


def _source_row(question_id: str, *, structure: str, name: str, child: bool = False) -> dict[str, object]:
    return {
        "verify_label": LABEL,
        "question_id": question_id,
        "parent_id": f"parent-{question_id}" if child else question_id,
        "is_sub_question": child,
        "contain_audio": name == "听力单选",
        "whole_image": False,
        "input": (
            f"题型结构为：{structure}\n"
            f"题型名称为：{name}\n"
            "题目题干：请判断事件发生的先后顺序。\n"
            "题目解析：根据题干信息作答。\n"
            "题目答案：A"
        ),
    }


class TimeOrderTreePacketTests(unittest.TestCase):
    def test_selects_all_60_remove_and_12_keep_by_required_strata(self):
        source_rows = []
        evidence_rows = []
        index = 0
        strata = [
            (31, "单选题", "选择题", False),
            (16, "单选题", "听力单选", False),
            (8, "复合题", "听力单选", True),
            (5, "填空题", "完成句子", False),
        ]
        for count, structure, name, child in strata:
            for _ in range(count):
                question_id = f"remove-{index}"
                source_rows.append(
                    _source_row(question_id, structure=structure, name=name, child=child)
                )
                evidence_rows.append(
                    {"question_id": question_id, "parent_id": f"parent-{question_id}" if child else question_id, "decision": "remove"}
                )
                index += 1
        for keep_index in range(12):
            question_id = f"keep-{keep_index}"
            source_rows.append(
                _source_row(question_id, structure="单选题", name="选择题")
            )
            evidence_rows.append(
                {"question_id": question_id, "parent_id": question_id, "decision": "keep"}
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jsonl"
            evidence = root / "evidence.jsonl"
            output = root / "tasks.jsonl"
            audit = root / "audit.jsonl"
            for path, rows in ((source, source_rows), (evidence, evidence_rows)):
                path.write_text(
                    "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8",
                )

            report = build_time_order_tree_packet(
                source,
                evidence_path=evidence,
                output_path=output,
                audit_index_path=audit,
                seed="test-time-order",
            )
            tasks = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            audits = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(report["selected_records"], 72)
        self.assertEqual(len(tasks), 72)
        self.assertEqual(len(audits), 72)
        self.assertEqual(
            {task["knowledge_policy"] for task in tasks}, {"optional"}
        )
        self.assertEqual(
            {task["allowed_knowledge_prefixes"][0] for task in tasks}, {"知识点"}
        )
        self.assertEqual(
            {audit_row["web_gpt_decision"] for audit_row in audits}, {"remove", "keep"}
        )
        strata_counts = {}
        for audit_row in audits:
            strata_counts[audit_row["selection_stratum"]] = strata_counts.get(audit_row["selection_stratum"], 0) + 1
        self.assertEqual(
            strata_counts,
            {
                "parent_choice_remove": 31,
                "parent_listening_remove": 16,
                "child_listening_remove": 8,
                "other_remove": 5,
                "keep_control": 12,
            },
        )

    def test_rejects_unmatched_parent_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jsonl"
            evidence = root / "evidence.jsonl"
            source.write_text(
                json.dumps(_source_row("q1", structure="单选题", name="选择题"), ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            evidence.write_text(
                json.dumps({"question_id": "q1", "parent_id": "wrong", "decision": "remove"}) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                build_time_order_tree_packet(
                    source,
                    evidence_path=evidence,
                    output_path=root / "tasks.jsonl",
                    audit_index_path=root / "audit.jsonl",
                    seed="test-time-order",
                )

    def test_rejects_directory_instead_of_input_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "source must be a readable file"):
                build_time_order_tree_packet(
                    root,
                    evidence_path=root,
                    output_path=root / "tasks.jsonl",
                    audit_index_path=root / "audit.jsonl",
                    seed="test-time-order",
                )


if __name__ == "__main__":
    unittest.main()
