import json
from pathlib import Path
import tempfile
import unittest

from english_knowledge_tagger.low_quality_full_packets import (
    build_low_quality_label_full_packets,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return path


class LowQualityFullPacketTests(unittest.TestCase):
    def test_builds_exact_label_files_and_preserves_all_source_rows(self):
        labels = [
            "知识点->词法->动词->实义动词->及物动词",
            "知识点->语法词法->现在进行时",
            "知识点->语篇主题->人与社会->互联通讯",
        ]
        policy = {
            "schema_version": "p0-terminal-label-policy-v1",
            "labels": labels,
        }
        source_rows = [
            {
                "question_id": "q1",
                "output": "知识点@语法词法@动词@实义动词@及物动词;知识点@语篇主题@人与社会@互联通讯",
                "input": "question 1",
            },
            {
                "question_id": "q2",
                "output": "知识点@语法词法@现在进行时",
                "input": "question 2",
            },
            {"question_id": "q3", "output": "题型@选择题", "input": "question 3"},
        ]
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source = _write_jsonl(directory / "source.jsonl", source_rows)
            policy_path = directory / "policy.json"
            policy_path.write_text(
                json.dumps(policy, ensure_ascii=False), encoding="utf-8"
            )
            output = directory / "output"
            report = build_low_quality_label_full_packets(
                source,
                policy_path=policy_path,
                output_dir=output,
                exclude_labels={
                    "知识点->词法->动词->实义动词->及物动词",
                },
            )

            files = sorted(output.glob("劣质-*.jsonl"))
            self.assertEqual(report["labels"], 2)
            self.assertEqual(report["source_records"], 3)
            self.assertEqual(report["source_label_hits"], 2)
            self.assertEqual([path.name for path in files], [
                "劣质-001-知识点@语法词法@现在进行时.jsonl",
                "劣质-002-知识点@语篇主题@人与社会@互联通讯.jsonl",
            ])
            self.assertEqual(
                [json.loads(line)["question_id"] for line in files[0].read_text(encoding="utf-8").splitlines()],
                ["q2"],
            )
            self.assertEqual(
                [json.loads(line)["question_id"] for line in files[1].read_text(encoding="utf-8").splitlines()],
                ["q1"],
            )

    def test_refuses_existing_target_file(self):
        labels = ["知识点->语用->时间->顺序"]
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source = _write_jsonl(
                directory / "source.jsonl",
                [{"question_id": "q1", "output": "知识点@语用@时间@顺序"}],
            )
            policy = directory / "policy.json"
            policy.write_text(
                json.dumps({"schema_version": "p0-terminal-label-policy-v1", "labels": labels}),
                encoding="utf-8",
            )
            output = directory / "output"
            output.mkdir()
            (output / "劣质-001-知识点@语用@时间@顺序.jsonl").write_text("x\n", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                build_low_quality_label_full_packets(
                    source, policy_path=policy, output_dir=output
                )

    def test_allows_existing_directory_with_unrelated_files(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source = _write_jsonl(
                directory / "source.jsonl",
                [{"question_id": "q1", "output": "知识点@语用@时间@顺序"}],
            )
            policy = directory / "policy.json"
            policy.write_text(
                json.dumps(
                    {
                        "schema_version": "p0-terminal-label-policy-v1",
                        "labels": ["知识点->语用->时间->顺序"],
                    }
                ),
                encoding="utf-8",
            )
            output = directory / "output"
            output.mkdir()
            (output / "README.md").write_text("keep", encoding="utf-8")
            report = build_low_quality_label_full_packets(
                source, policy_path=policy, output_dir=output
            )
            self.assertEqual(report["labels"], 1)


if __name__ == "__main__":
    unittest.main()
