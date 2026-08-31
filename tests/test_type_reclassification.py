import json
from pathlib import Path
import tempfile
import unittest

from english_knowledge_tagger.type_reclassification import (
    SAMPLE_SCHEMA_VERSION,
    QuestionTypeClient,
    QuestionTypeServiceConfig,
    QuestionTypeServiceError,
    StreamCompletion,
    build_question_type_prompt,
    build_type_reclassification_sample,
    clean_question_input,
    parse_question_type_response,
)


def discovery_payload(**overrides):
    payload = {
        "candidate_type_label": "阅读主旨选择题",
        "label_target": "独立小题",
        "input_modality": "文字",
        "material_structure": "连续语篇后接一个选择小题",
        "prompt_support": "四个选项",
        "core_operation": "概括语篇主旨并选择答案",
        "response_form": "选项编号，封闭选择",
        "assessment_focus": "主旨概括",
        "solution_basis": "整篇语篇的中心内容",
        "target_language_form": "不适用",
        "genre_or_product": "不适用",
        "communicative_purpose": "不适用",
        "content_focus": "不适用",
        "task_constraints": [],
        "additional_distinctions": [],
        "naming_basis": "任务机制命名",
        "information_sufficiency": "sufficient",
        "confidence": 0.93,
        "decision_evidence": ["根据语篇选择主旨"],
    }
    payload.update(overrides)
    return payload


class TypeReclassificationTests(unittest.TestCase):
    def test_prompt_uses_cleaned_input_without_declared_type_lines(self):
        source = (
            "题型结构为：完形填空\n"
            "题型名称为：完形填空\n"
            "题目题干：Choose the answer.\n"
            "当前小题答案：B"
        )

        cleaned = clean_question_input(source)
        prompt = build_question_type_prompt("只输出题型标签。", source)

        self.assertNotIn("题型结构为", cleaned)
        self.assertNotIn("题型名称为", cleaned)
        self.assertIn("题目题干：Choose the answer.", cleaned)
        self.assertEqual(prompt.count("只输出题型标签。"), 1)
        self.assertNotIn("题型结构为", prompt)
        self.assertNotIn("题型名称为", prompt)

    def test_sample_is_bounded_per_exact_type_label_and_deduplicates_rows(self):
        label_a = "题型@词句运用@单词拼写"
        label_b = "题型@语篇填空@完形填空"
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = directory / "source.jsonl"
            rows = [
                {
                    "question_id": str(index),
                    "parent_id": str(index),
                    "is_sub_question": False,
                    "instruction": "旧 instruction",
                    "input": f"题目题干：question {index}",
                    "output": f"{label_a};{label_b}",
                }
                for index in range(4)
            ]
            source.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )
            output = directory / "sample.jsonl"

            report = build_type_reclassification_sample(
                source, output_path=output, per_type=3, seed=7
            )
            sampled = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(report["type_category_count"], 2)
        self.assertEqual(report["type_category_sample_counts"], {label_a: 3, label_b: 3})
        self.assertEqual(report["sample_memberships"], 6)
        self.assertLess(report["unique_sample_records"], 6)
        self.assertEqual(len({row["source_line"] for row in sampled}), len(sampled))
        self.assertTrue(all(row["schema_version"] == SAMPLE_SCHEMA_VERSION for row in sampled))

    def test_client_requests_streaming_and_parses_delta_content(self):
        captured = {}

        def transport(endpoint, payload, timeout, headers):
            captured.update(
                endpoint=endpoint, payload=payload, timeout=timeout, headers=dict(headers)
            )
            return StreamCompletion(
                request_id="chatcmpl-1",
                model="served-model",
                content=json.dumps(discovery_payload(), ensure_ascii=False),
            )

        client = QuestionTypeClient(
            QuestionTypeServiceConfig(endpoint="http://example.test/v1/chat/completions"),
            base_prompt="只输出题型标签。",
            transport=transport,
        )

        result = client.classify(
            "题型结构为：选择题\n题型名称为：阅读理解\n题目题干：Read and choose."
        )

        self.assertTrue(captured["payload"]["stream"])
        self.assertEqual(captured["payload"]["temperature"], 0)
        self.assertNotIn("题型结构为", captured["payload"]["messages"][0]["content"])
        self.assertNotIn("题型名称为", captured["payload"]["messages"][0]["content"])
        self.assertEqual(result.discovery["candidate_type_label"], "阅读主旨选择题")
        self.assertEqual(result.model, "served-model")

    def test_parser_accepts_one_fenced_discovery_object(self):
        payload = discovery_payload(candidate_type_label="双提示单词拼写")
        parsed = parse_question_type_response(
            "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
        )

        self.assertEqual(parsed["candidate_type_label"], "双提示单词拼写")
        self.assertEqual(parsed["confidence"], 0.93)

    def test_parser_rejects_incomplete_discovery_object(self):
        with self.assertRaisesRegex(QuestionTypeServiceError, "fields mismatch"):
            parse_question_type_response('{"candidate_type_label":"单词拼写"}')

    def test_parser_rejects_invalid_enum(self):
        payload = discovery_payload(label_target="一道题")

        with self.assertRaisesRegex(QuestionTypeServiceError, "label_target"):
            parse_question_type_response(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
