import json
import tempfile
import unittest
from pathlib import Path

from english_knowledge_tagger.enhanced_source_audit import profile_enhanced_source


class EnhancedSourceAuditTests(unittest.TestCase):
    def test_profile_separates_scope_shape_modality_and_type_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jsonl"
            index = root / "index.sqlite3"
            sample_output = root / "samples.jsonl"
            source.write_text(
                "\n".join(
                    json.dumps(row, ensure_ascii=False)
                    for row in (
                        {
                            "input": "题型结构为：复合题\n题型名称为：完成句子\n题目题干：六、按要求完成句子\n",
                            "output": "知识点@父题标签",
                            "question_id": "p1",
                            "parent_id": "p1",
                            "is_sub_question": False,
                            "contain_audio": False,
                            "whole_image": False,
                        },
                        {
                            "input": "题型结构为：复合题\n题型名称为：完形填空\n当前小题选项：\nA. one\n当前小题解析：选择。\n当前小题答案：A",
                            "output": "题型@完形填空",
                            "question_id": "c1",
                            "parent_id": "p2",
                            "is_sub_question": True,
                            "contain_audio": False,
                            "whole_image": False,
                        },
                        {
                            "input": "题型结构为：复合题\n题型名称为：听力单选\n本题题干中包含音频内容，音频片段时长3秒，\n当前小题题干：What?",
                            "output": "知识点@听力",
                            "question_id": "c2",
                            "parent_id": "p3",
                            "is_sub_question": True,
                            "contain_audio": True,
                            "whole_image": True,
                            "images": ["image-a"],
                        },
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            report = profile_enhanced_source(
                source,
                index_path=index,
                sample_output_path=sample_output,
                sample_per_bucket=2,
                seed="test-seed",
            )

            self.assertEqual(report["valid_records"], 3)
            self.assertEqual(report["scope_counts"], {"parent": 1, "child": 2, "unknown": 0})
            self.assertEqual(report["content_shape_counts"]["parent_shell_compact"], 1)
            self.assertEqual(report["content_shape_counts"]["child_without_stem"], 1)
            self.assertEqual(report["content_shape_counts"]["child_with_stem"], 1)
            self.assertEqual(report["modality_counts"]["text"], 2)
            self.assertEqual(report["modality_counts"]["audio_image"], 1)
            self.assertEqual(report["duplicate_identity_count"], 0)
            self.assertGreaterEqual(report["type_bucket_count"], 3)

            samples = [
                json.loads(line)
                for line in sample_output.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(samples), 6)
            self.assertTrue(all("input" in row and "output" in row for row in samples))
            self.assertTrue(any(row["content_shape"] == "parent_shell_compact" for row in samples))

    def test_profile_counts_duplicate_identity_without_deduplicating_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jsonl"
            index = root / "index.sqlite3"
            samples = root / "samples.jsonl"
            row = {
                "input": "题型结构为：单选题\n题型名称为：选择题\n题目题干：x",
                "output": "知识点@x",
                "question_id": "q1",
                "parent_id": "q1",
                "is_sub_question": False,
                "contain_audio": False,
                "whole_image": False,
            }
            source.write_text(
                json.dumps(row, ensure_ascii=False) + "\n" + json.dumps(row, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            report = profile_enhanced_source(
                source,
                index_path=index,
                sample_output_path=samples,
                sample_per_bucket=1,
                seed="duplicate-test",
            )

            self.assertEqual(report["valid_records"], 2)
            self.assertEqual(report["duplicate_identity_count"], 1)
            self.assertEqual(report["sampled_records"], 2)


if __name__ == "__main__":
    unittest.main()
