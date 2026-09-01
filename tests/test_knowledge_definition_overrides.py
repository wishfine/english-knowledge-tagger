from pathlib import Path
import json
import tempfile
import unittest

from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook


class KnowledgeDefinitionOverrideTests(unittest.TestCase):
    def _write_rulebook(self, directory: str) -> Path:
        path = Path(directory) / "teacher.csv"
        path.write_text(
            "末级知识点,打标解读（标绿的标签，新题不再打）,大模型压缩+人工微调的释义\n"
            "知识点->词汇->构词法->转化法,原始转化法定义,原始压缩定义\n"
            "知识点->词汇->固定搭配/句型,原始搭配定义,原始搭配压缩定义\n",
            encoding="utf-8",
        )
        return path

    def _write_overrides(self, directory: str, payload: dict) -> Path:
        path = Path(directory) / "overrides.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_override_becomes_effective_definition_without_mutating_csv_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            rulebook_path = self._write_rulebook(directory)
            overrides_path = self._write_overrides(
                directory,
                {
                    "schema_version": "knowledge-definition-overrides-v1",
                    "overrides": [
                        {
                            "label": "知识点->词汇->构词法->转化法",
                            "replacement_definition": "修订后的转化法定义",
                            "status": "active_for_experiment",
                        }
                    ],
                },
            )

            rulebook = load_knowledge_rulebook(rulebook_path, overrides_path=overrides_path)

        conversion = rulebook.records["知识点->词汇->构词法->转化法"]
        self.assertEqual(conversion.target_definition, "修订后的转化法定义")
        self.assertEqual(conversion.alternative_definition, "修订后的转化法定义")
        self.assertEqual(
            rulebook.records["知识点->词汇->固定搭配/句型"].target_definition,
            "原始搭配定义",
        )

    def test_override_rejects_unknown_knowledge_label(self):
        with tempfile.TemporaryDirectory() as directory:
            rulebook_path = self._write_rulebook(directory)
            overrides_path = self._write_overrides(
                directory,
                {
                    "schema_version": "knowledge-definition-overrides-v1",
                    "overrides": [
                        {
                            "label": "知识点->不存在",
                            "replacement_definition": "不应加载",
                            "status": "active_for_experiment",
                        }
                    ],
                },
            )

            with self.assertRaisesRegex(ValueError, "absent from teacher CSV"):
                load_knowledge_rulebook(rulebook_path, overrides_path=overrides_path)

    def test_override_rejects_duplicate_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            rulebook_path = self._write_rulebook(directory)
            overrides_path = self._write_overrides(
                directory,
                {
                    "schema_version": "knowledge-definition-overrides-v1",
                    "overrides": [
                        {
                            "label": "知识点->词汇->构词法->转化法",
                            "replacement_definition": "第一版",
                            "status": "active_for_experiment",
                        },
                        {
                            "label": "知识点->词汇->构词法->转化法",
                            "replacement_definition": "第二版",
                            "status": "active_for_experiment",
                        },
                    ],
                },
            )

            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_knowledge_rulebook(rulebook_path, overrides_path=overrides_path)


if __name__ == "__main__":
    unittest.main()
