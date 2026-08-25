import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

try:
    from english_knowledge_tagger.source_profile import profile_jsonl
except ModuleNotFoundError:
    profile_jsonl = None


def write_jsonl(directory: Path, lines: list[str]) -> Path:
    path = directory / "source.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class SourceProfileTests(unittest.TestCase):
    def test_profile_distinguishes_parent_child_and_partial_supervision(self):
        self.assertTrue(callable(profile_jsonl), "profile_jsonl must be implemented")
        with tempfile.TemporaryDirectory() as temp_dir:
            path = write_jsonl(
                Path(temp_dir),
                [
                    json.dumps(
                        {
                            "question_id": "parent-1",
                            "parent_id": "parent-1",
                            "is_standalone": True,
                            "question_info_cleaned": {"stem": "Read the passage.", "options": []},
                            "solve_func_ids": [101, 102],
                            "question_type_ids": [201],
                        }
                    ),
                    json.dumps(
                        {
                            "question_id": "child-1",
                            "parent_id": "parent-1",
                            "is_standalone": False,
                            "question_info_cleaned": {
                                "current_sub_question_stem": "Choose the best answer.",
                                "current_sub_question_options": ["A", "B"],
                            },
                            "solve_func_ids": [103],
                            "question_type_ids": [],
                        }
                    ),
                    json.dumps(
                        {
                            "question_id": "child-2",
                            "parent_id": "parent-1",
                            "solve_func_ids": [],
                            "question_type_ids": [202],
                        }
                    ),
                ],
            )

            profile = profile_jsonl(path)

        self.assertEqual(profile["valid_records"], 3)
        self.assertEqual(profile["parent_child"]["root"], 1)
        self.assertEqual(profile["parent_child"]["child"], 2)
        self.assertEqual(
            profile["supervision"],
            {"both": 1, "knowledge_only": 1, "type_only": 1, "neither": 0},
        )
        self.assertEqual(profile["label_cardinality"]["knowledge"], {"0": 1, "1": 1, "2": 1})
        self.assertEqual(profile["label_cardinality"]["type"], {"0": 1, "1": 2})
        self.assertEqual(
            profile["cleaned_content"],
            {
                "dict": 2,
                "missing": 1,
                "sub_question_stem_present": 1,
                "parent_answer_present": 0,
            },
        )

    def test_profile_counts_invalid_and_non_object_lines_without_aborting(self):
        self.assertTrue(callable(profile_jsonl), "profile_jsonl must be implemented")
        with tempfile.TemporaryDirectory() as temp_dir:
            path = write_jsonl(
                Path(temp_dir),
                [
                    "not-json",
                    "[]",
                    json.dumps(
                        {
                            "question_id": "q-1",
                            "parent_id": "q-1",
                            "solve_func_ids": [],
                            "questjon_type_ids": [7],
                        }
                    ),
                ],
            )

            profile = profile_jsonl(path)

        self.assertEqual(profile["nonempty_lines"], 3)
        self.assertEqual(profile["valid_records"], 1)
        self.assertEqual(profile["invalid_json_lines"], 1)
        self.assertEqual(profile["non_object_lines"], 1)
        self.assertEqual(profile["field_presence"]["questjon_type_ids"], 1)
        self.assertEqual(
            profile["supervision"],
            {"both": 0, "knowledge_only": 0, "type_only": 1, "neither": 0},
        )

    def test_profile_cli_writes_json_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = write_jsonl(
                directory,
                [
                    json.dumps(
                        {
                            "question_id": "q-1",
                            "parent_id": "q-1",
                            "solve_func_ids": [1],
                            "question_type_ids": [2],
                        }
                    )
                ],
            )
            output = directory / "profile.json"
            script = Path(__file__).resolve().parents[1] / "scripts" / "profile_source.py"

            completed = subprocess.run(
                [sys.executable, str(script), "--input", str(source), "--output", str(output)],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["valid_records"], 1)
