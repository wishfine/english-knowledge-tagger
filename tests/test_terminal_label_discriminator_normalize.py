import json
from pathlib import Path
import tempfile
import unittest

try:
    from english_knowledge_tagger.terminal_label_discriminator_normalize import (
        load_discriminator_field_map,
        normalise_terminal_label_discriminator_row,
    )
except ModuleNotFoundError:
    load_discriminator_field_map = None
    normalise_terminal_label_discriminator_row = None


class TerminalLabelDiscriminatorNormaliseTests(unittest.TestCase):
    def test_maps_nested_runner_fields_without_inferring_anything(self):
        self.assertTrue(callable(load_discriminator_field_map))
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "field-map.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "terminal-label-discriminator-field-map-v1",
                        "fields": {
                            "review_id": ["id"],
                            "question_id": ["source", "question_id"],
                            "parent_id": ["source", "parent_id"],
                            "source_line": ["source", "line"],
                            "is_sub_question": ["source", "is_sub_question"],
                            "legacy_label": ["candidate", "legacy"],
                            "canonical_label": ["candidate", "canonical"],
                            "llm_match": ["result", "match"],
                            "status": ["result", "status"],
                        },
                        "constants": {
                            "model": "ds-v4-flash",
                            "prompt_version": "direct-label-v1",
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            field_map = load_discriminator_field_map(path)
            normalized = normalise_terminal_label_discriminator_row(
                {
                    "id": "run-1",
                    "source": {
                        "question_id": "101",
                        "parent_id": "100",
                        "line": 42,
                        "is_sub_question": True,
                    },
                    "candidate": {"legacy": "知识点@语法词法@冠词@a/an的区别", "canonical": "知识点->词法->冠词->a/an的区别"},
                    "result": {"match": True, "status": "candidate"},
                    "runner_only": "keep for audit",
                },
                line_number=1,
                field_map=field_map,
            )

        self.assertEqual(normalized["schema_version"], "terminal-label-discriminator-evidence-v1")
        self.assertTrue(normalized["llm_match"])
        self.assertEqual(normalized["model"], "ds-v4-flash")
        self.assertEqual(normalized["raw_discriminator_record"]["runner_only"], "keep for audit")

    def test_rejects_field_map_that_silently_omits_a_required_contract_field(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "field-map.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "terminal-label-discriminator-field-map-v1",
                        "fields": {},
                        "constants": {},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "missing required fields"):
                load_discriminator_field_map(path)


if __name__ == "__main__":
    unittest.main()
