import json
from pathlib import Path
import tempfile
import unittest


try:
    from english_knowledge_tagger.final_label_discriminator import (
        build_final_label_discriminator_prompt,
        load_final_label_prompt_clarifications,
    )
except ImportError:
    build_final_label_discriminator_prompt = None
    load_final_label_prompt_clarifications = None


LABEL = "知识点@词汇@固定搭配/句型"
OTHER_LABEL = "知识点@语法句法@主从复合句@状语从句@原因状语从句"


def packet(label: str) -> dict[str, object]:
    return {
        "verify_label": label,
        "question_text": "题目题干：示例题目。",
    }


def write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


class FinalLabelPromptClarificationTests(unittest.TestCase):
    def test_v2_clarification_is_appended_only_to_its_target_label(self):
        self.assertTrue(callable(load_final_label_prompt_clarifications))
        definitions = {LABEL: {"definition": "固定搭配释义"}, OTHER_LABEL: {"definition": "原因从句释义"}}
        with tempfile.TemporaryDirectory() as temp_dir:
            clarifications = load_final_label_prompt_clarifications(
                write_json(
                    Path(temp_dir) / "clarifications.json",
                    {
                        "schema_version": "final-label-prompt-clarifications-v1",
                        "prompt_version": "final-label-discriminator-v2",
                        "labels": [
                            {
                                "legacy_label": LABEL,
                                "clarification": "从句连接词功能本身不属于固定句型。",
                            }
                        ],
                    },
                ),
                label_definitions=definitions,
            )

        target_prompt = build_final_label_discriminator_prompt(
            packet(LABEL), label_definitions=definitions, clarification=clarifications.for_label(LABEL)
        )
        other_prompt = build_final_label_discriminator_prompt(
            packet(OTHER_LABEL), label_definitions=definitions, clarification=clarifications.for_label(OTHER_LABEL)
        )
        self.assertEqual(clarifications.prompt_version, "final-label-discriminator-v2")
        self.assertIn("本轮边界澄清", target_prompt)
        self.assertIn("从句连接词功能本身不属于固定句型。", target_prompt)
        self.assertNotIn("本轮边界澄清", other_prompt)

    def test_clarification_rejects_unknown_or_duplicate_label(self):
        self.assertTrue(callable(load_final_label_prompt_clarifications))
        definitions = {LABEL: {"definition": "固定搭配释义"}}
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            unknown = write_json(
                directory / "unknown.json",
                {
                    "schema_version": "final-label-prompt-clarifications-v1",
                    "prompt_version": "final-label-discriminator-v2",
                    "labels": [{"legacy_label": OTHER_LABEL, "clarification": "x"}],
                },
            )
            duplicate = write_json(
                directory / "duplicate.json",
                {
                    "schema_version": "final-label-prompt-clarifications-v1",
                    "prompt_version": "final-label-discriminator-v2",
                    "labels": [
                        {"legacy_label": LABEL, "clarification": "x"},
                        {"legacy_label": LABEL, "clarification": "y"},
                    ],
                },
            )
            with self.assertRaisesRegex(ValueError, "unknown label"):
                load_final_label_prompt_clarifications(unknown, label_definitions=definitions)
            with self.assertRaisesRegex(ValueError, "duplicate label"):
                load_final_label_prompt_clarifications(duplicate, label_definitions=definitions)


if __name__ == "__main__":
    unittest.main()
