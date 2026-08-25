from pathlib import Path
import tempfile
import unittest

try:
    from english_knowledge_tagger.type_rulebook import load_type_rulebook
except ModuleNotFoundError:
    load_type_rulebook = None


class TypeRulebookTests(unittest.TestCase):
    def test_rulebook_filters_explicitly_deprecated_types_but_keeps_discouraged_types(self):
        self.assertTrue(callable(load_type_rulebook), "load_type_rulebook must be implemented")
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "teacher.csv"
            source.write_text(
                "末级知识点,打标解读（标绿的标签，新题不再打）\n"
                "题型->阅读理解->阅读选择->细节理解,小题打此标签\n"
                "题型->阅读理解->阅读理解（综合）,新题不用打\n"
                "题型->阅读理解->其他任务型阅读->阅读填空,新题基本不用打\n",
                encoding="utf-8",
            )

            rulebook = load_type_rulebook(source)

        self.assertEqual(
            rulebook.candidates_for_prefixes(("题型->阅读理解",)),
            (
                "题型->阅读理解->其他任务型阅读->阅读填空",
                "题型->阅读理解->阅读选择->细节理解",
            ),
        )
        self.assertEqual(rulebook.status_for("题型->阅读理解->阅读理解（综合）"), "deprecated")
        self.assertEqual(
            rulebook.status_for("题型->阅读理解->其他任务型阅读->阅读填空"),
            "discouraged",
        )

    def test_rulebook_rejects_duplicate_type_terminal_paths(self):
        self.assertTrue(callable(load_type_rulebook), "load_type_rulebook must be implemented")
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "teacher.csv"
            source.write_text(
                "末级知识点,打标解读（标绿的标签，新题不再打）\n"
                "题型->阅读理解->阅读选择->细节理解,第一行\n"
                "题型->阅读理解->阅读选择->细节理解,第二行\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_type_rulebook(source)


if __name__ == "__main__":
    unittest.main()
