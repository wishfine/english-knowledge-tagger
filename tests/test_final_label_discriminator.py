import json
from pathlib import Path
import tempfile
import unittest


try:
    from english_knowledge_tagger.candidate_labeling import LabelingServiceConfig
    from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook
    from english_knowledge_tagger.knowledge_taxonomy_migration import load_knowledge_taxonomy_migration
    from english_knowledge_tagger.final_label_discriminator import (
        FinalLabelDiscriminatorClient,
        FinalLabelDiscriminatorRequest,
        build_final_label_discriminator_packet,
        build_final_label_discriminator_prompt,
        final_result_to_evidence,
    )
except ImportError:
    LabelingServiceConfig = None
    load_knowledge_rulebook = None
    load_knowledge_taxonomy_migration = None
    FinalLabelDiscriminatorClient = None
    FinalLabelDiscriminatorRequest = None
    build_final_label_discriminator_packet = None
    build_final_label_discriminator_prompt = None
    final_result_to_evidence = None


LABEL = "知识点@词汇@词汇辨析@名词（短语）辨析"


def write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def write_rulebook(path: Path) -> Path:
    path.write_text(
        "末级知识点,打标解读（标绿的标签，新题不再打）,大模型压缩+人工微调的释义\n"
        "知识点->词汇->词汇辨析->名词（短语）辨析,名词辨析,名词辨析\n",
        encoding="utf-8",
    )
    return path


def write_migration(path: Path) -> Path:
    write_json(path, {"schema_version": "knowledge-taxonomy-migration-v1", "rules": []})
    return path


class FinalLabelDiscriminatorPacketTests(unittest.TestCase):
    def test_final_packet_removes_type_metadata_and_historical_labels(self):
        self.assertTrue(callable(build_final_label_discriminator_packet))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            definitions_path = directory / "definitions.json"
            eligible_packet = directory / "eligible.packet.jsonl"
            output_path = directory / "final.packet.jsonl"
            write_json(definitions_path, {LABEL: {"definition": "仅非复合单选中的名词辨析。"}})
            eligible_packet.write_text(
                json.dumps(
                    {
                        "schema_version": "mentor-label-rollout-packet-v1",
                        "review_id": "mentor-direct-v1:7:label",
                        "source_line": 7,
                        "question_id": "question-7",
                        "parent_id": "parent-7",
                        "is_sub_question": False,
                        "route_key": {
                            "scope": "parent",
                            "declared_type_structure": "单选题",
                            "declared_type_name": "选择题",
                        },
                        "verify_label": LABEL,
                        "instruction": "这是历史指令，不得发送给最终判别器。",
                        "input": "题型结构为：复合题\n题型名称为：选词填空\n所给图片为题目题干\n题目题干：Choose the right noun.\n题目选项：A. book B. run\n\n根据以上信息，当前题目所属的题型方法类目和知识点类目为：",
                        "output_all": "知识点@词汇@词汇辨析@名词（短语）辨析;知识点@其他@不应泄漏",
                        "source_path": "/source.jsonl",
                        "label_definitions_path": str(definitions_path),
                        "label_definitions_sha256": "legacy-hash",
                        "rollout_route_decision": "eligible",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            report = build_final_label_discriminator_packet(
                eligible_packet,
                label_definitions_path=definitions_path,
                output_path=output_path,
            )
            row = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(report["selected_records"], 1)
        self.assertEqual(row["question_text"], "题目题干：Choose the right noun.\n题目选项：A. book B. run")
        self.assertEqual(row["verify_label"], LABEL)
        self.assertEqual(row["route_key"]["declared_type_name"], "选择题")
        self.assertNotIn("output_all", row)
        self.assertNotIn("instruction", row)
        self.assertNotIn("input", row)
        self.assertNotIn("题型结构为", row["question_text"])
        self.assertNotIn("题型名称为", row["question_text"])
        self.assertNotIn("当前题目所属的题型方法类目", row["question_text"])

    def test_final_prompt_and_evidence_exclude_historical_labels_and_type_metadata(self):
        self.assertTrue(callable(build_final_label_discriminator_prompt))
        self.assertTrue(callable(FinalLabelDiscriminatorClient))
        packet_row = {
            "schema_version": "final-label-discriminator-packet-v1",
            "review_id": "final-label-discriminator-v1:7:label",
            "source_line": 7,
            "question_id": "question-7",
            "parent_id": "parent-7",
            "is_sub_question": False,
            "route_key": {
                "scope": "parent",
                "declared_type_structure": "单选题",
                "declared_type_name": "选择题",
            },
            "verify_label": LABEL,
            "question_text": "题目题干：Choose the right noun.\n题目选项：A. book B. run",
        }
        definitions = {LABEL: {"definition": "仅非复合单选中的名词辨析。"}}
        prompt = build_final_label_discriminator_prompt(packet_row, label_definitions=definitions)
        self.assertIn("待验证标签", prompt)
        self.assertIn("标签释义", prompt)
        self.assertIn(packet_row["question_text"], prompt)
        self.assertNotIn("当前题目打的全部标签", prompt)
        self.assertNotIn("题型结构为", prompt)
        self.assertNotIn("题型名称为", prompt)
        self.assertNotIn("选择题", prompt)

        payloads = []
        client = FinalLabelDiscriminatorClient(
            LabelingServiceConfig(endpoint="http://example.invalid", model="ds-v4-flash"),
            label_definitions=definitions,
            transport=lambda _endpoint, payload, _timeout, _headers: (
                payloads.append(payload)
                or {
                    "id": "request-7",
                    "model": "ds-v4-flash",
                    "choices": [
                        {
                            "message": {
                                "content": '{"match":true,"confidence":"high","reason":"名词选项构成必要辨析。"}'
                            }
                        }
                    ],
                }
            ),
        )
        result = client.verify(FinalLabelDiscriminatorRequest(packet_row=packet_row))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            evidence = final_result_to_evidence(
                packet_row,
                result=result,
                rulebook=load_knowledge_rulebook(write_rulebook(directory / "rulebook.csv")),
                migration=load_knowledge_taxonomy_migration(write_migration(directory / "migration.json")),
            )

        self.assertEqual(payloads[0]["temperature"], 0)
        self.assertEqual(payloads[0]["chat_template_kwargs"], {"enable_thinking": False})
        self.assertTrue(evidence["llm_match"])
        self.assertEqual(evidence["confidence"], "high")
        self.assertEqual(evidence["prompt_version"], "final-label-discriminator-v1")
        self.assertNotIn("output_all", evidence)
        self.assertNotIn("instruction", evidence)
        self.assertNotIn("question_text", evidence)


if __name__ == "__main__":
    unittest.main()
