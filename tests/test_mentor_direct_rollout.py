import json
from pathlib import Path
import tempfile
import unittest

try:
    from english_knowledge_tagger.candidate_labeling import LabelingServiceConfig
    from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook
    from english_knowledge_tagger.knowledge_taxonomy_migration import load_knowledge_taxonomy_migration
    from english_knowledge_tagger.mentor_direct_rollout import (
        MentorDirectClient,
        MentorDirectRequest,
        build_mentor_direct_v1_prompt,
        build_mentor_label_rollout_packet,
        clean_mentor_v1_input,
        mentor_result_to_evidence,
    )
except ImportError:
    LabelingServiceConfig = None
    load_knowledge_rulebook = None
    load_knowledge_taxonomy_migration = None
    MentorDirectClient = None
    MentorDirectRequest = None
    build_mentor_direct_v1_prompt = None
    build_mentor_label_rollout_packet = None
    clean_mentor_v1_input = None
    mentor_result_to_evidence = None


LABEL = "知识点@词汇@词汇辨析@名词（短语）辨析"
OTHER_LABEL = "知识点@词汇@固定搭配/句型"


def write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def definitions() -> dict[str, object]:
    return {
        LABEL: {
            "definition": "只标非复合单选中的名词或名词短语辨析。",
            "examples": "A. book B. pen",
            "similar_labels": [{"label": OTHER_LABEL}],
            "cooccur_labels": [{"label": OTHER_LABEL, "condition": "固定搭配义是答案关键"}],
            "exclusive_labels": [{"label": "None", "condition": "题目为复合题"}],
        },
        OTHER_LABEL: {"definition": "固定搭配或句型。"},
    }


def write_rulebook(path: Path) -> Path:
    path.write_text(
        "末级知识点,打标解读（标绿的标签，新题不再打）,大模型压缩+人工微调的释义\n"
        "知识点->词汇->词汇辨析->名词（短语）辨析,名词辨析,名词辨析\n",
        encoding="utf-8",
    )
    return path


def write_migration(path: Path) -> Path:
    return write_json(
        path,
        {
            "schema_version": "knowledge-taxonomy-migration-v1",
            "rules": [],
        },
    )


class MentorDirectRolloutPacketTests(unittest.TestCase):
    def test_packet_selects_only_the_exact_historical_label_and_preserves_source_identity(self):
        self.assertTrue(callable(build_mentor_label_rollout_packet))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = write_jsonl(
                directory / "source.jsonl",
                [
                    {
                        "question_id": "100",
                        "parent_id": "100",
                        "is_sub_question": False,
                        "instruction": "给题目打标",
                        "input": "题型结构为：单选题\n题目题干：book",
                        "output": OTHER_LABEL,
                    },
                    {
                        "question_id": "101",
                        "parent_id": "100",
                        "is_sub_question": True,
                        "instruction": "给题目打标",
            "input": "题型结构为：单选题\n题目题干：请选择名词。",
                        "output": f"{LABEL};{OTHER_LABEL}",
                    },
                ],
            )
            packet = directory / "packet.jsonl"
            report = build_mentor_label_rollout_packet(
                source,
                verify_label=LABEL,
                label_definitions_path=write_json(directory / "definitions.json", definitions()),
                output_path=packet,
            )
            row = json.loads(packet.read_text(encoding="utf-8"))

        self.assertEqual(report["selected_records"], 1)
        self.assertEqual(row["source_line"], 2)
        self.assertEqual(row["question_id"], "101")
        self.assertEqual(row["verify_label"], LABEL)
        self.assertEqual(row["output_all"], f"{LABEL};{OTHER_LABEL}")
        self.assertEqual(row["input"], "题型结构为：单选题\n题目题干：请选择名词。")
        self.assertEqual(
            row["route_key"],
            {
                "scope": "child",
                "declared_type_structure": "单选题",
                "declared_type_name": None,
            },
        )

    def test_mentor_v1_prompt_keeps_output_all_but_removes_only_declared_type_and_picture_lines(self):
        self.assertTrue(callable(build_mentor_direct_v1_prompt))
        row = {
            "verify_label": LABEL,
            "instruction": "给题目打标",
            "input": "题型结构为：单选题\n题型名称为：词汇单选\n所给图片为题目题干\n题目题干：book",
            "output_all": f"{LABEL};{OTHER_LABEL}",
        }
        prompt = build_mentor_direct_v1_prompt(row, label_definitions=definitions())

        self.assertNotIn("题型结构为：单选题", prompt)
        self.assertNotIn("题型名称为：词汇单选", prompt)
        self.assertNotIn("所给图片为题目题干", prompt)
        self.assertIn("题目题干：book", prompt)
        self.assertIn("当前题目打的全部标签", prompt)
        self.assertIn(f"{LABEL};{OTHER_LABEL}", prompt)
        self.assertIn("关联标签", prompt)
        self.assertIn("互斥标签", prompt)

    def test_input_cleaning_uses_mentor_v1_2000_character_prefix_and_suffix(self):
        self.assertTrue(callable(clean_mentor_v1_input))
        cleaned = clean_mentor_v1_input("题型名称为：单选题\n" + "x" * 2001)

        self.assertEqual(cleaned, "x" * 2000 + "...（截断）")

    def test_client_emits_gate_compatible_candidate_evidence_for_match_true(self):
        self.assertTrue(callable(MentorDirectClient))
        packet_row = {
            "review_id": "mentor-direct-v1:1:target",
            "source_line": 1,
            "question_id": "101",
            "parent_id": "100",
            "is_sub_question": True,
            "verify_label": LABEL,
            "instruction": "给题目打标",
            "input": "题目题干：book",
            "output_all": LABEL,
        }
        client = MentorDirectClient(
            LabelingServiceConfig(endpoint="http://example.invalid", model="ds-v4-flash"),
            label_definitions=definitions(),
            transport=lambda *_: {
                "id": "request-1",
                "model": "ds-v4-flash",
                "choices": [
                    {"message": {"content": '{"reason":"名词单选","match":true,"should_be":"正确"}'}}
                ],
            },
        )
        result = client.verify(MentorDirectRequest(packet_row=packet_row))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            evidence = mentor_result_to_evidence(
                packet_row,
                result=result,
                rulebook=load_knowledge_rulebook(write_rulebook(directory / "rulebook.csv")),
                migration=load_knowledge_taxonomy_migration(write_migration(directory / "migration.json")),
            )

        self.assertTrue(evidence["llm_match"])
        self.assertEqual(evidence["status"], "candidate")
        self.assertEqual(evidence["canonical_label"], "知识点->词汇->词汇辨析->名词（短语）辨析")
        self.assertEqual(evidence["prompt_version"], "mentor-direct-v1")
        self.assertEqual(evidence["output_all"], LABEL)
        self.assertEqual(evidence["input_sha256"], __import__("hashlib").sha256("题目题干：book".encode()).hexdigest())


if __name__ == "__main__":
    unittest.main()
