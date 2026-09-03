import json
from pathlib import Path
import tempfile
import unittest


from english_knowledge_tagger.input_status_pilot_packet import (
    build_input_status_pilot_packets,
)


LABEL_A = "知识点@语法句法@句子种类@祈使句@祈使句否定形式"
LABEL_B = "知识点@语法词法@代词@反身代词"


def _row(source_line, label, question_text, *, child=False):
    return {
        "question_id": f"q-{source_line}",
        "parent_id": f"p-{source_line}",
        "is_sub_question": child,
        "output": label,
        "input": question_text,
    }


class InputStatusPilotPacketTests(unittest.TestCase):
    def test_builds_sanitized_stratified_packets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.jsonl"
            manifest = root / "manifest.json"
            definitions = root / "definitions.json"
            output_dir = root / "packets"

            source.write_text(
                "\n".join(
                    [
                        json.dumps(_row(1, LABEL_A, "题型结构为：单选题\n题目题干：Don't run."), ensure_ascii=False),
                        json.dumps(_row(2, LABEL_A, "题型名称为：听力单选\n本题题干中包含音频内容，音频片段时长10秒，\n题目解析：略\n题目答案：A"), ensure_ascii=False),
                        json.dumps(_row(3, LABEL_A, "题目大题题干：Read.\n当前小题解析：根据don't可知使用祈使句否定形式。\n当前小题答案：Don't run.", child=True), ensure_ascii=False),
                        json.dumps(_row(4, LABEL_B, "题目题干：They hurt ___.\n题目选项：A. myself B. themselves\n题目答案：B"), ensure_ascii=False),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            manifest.write_text(
                json.dumps({"schema_version": "input-status-pilot-label-manifest-v1", "labels": [LABEL_A, LABEL_B]}),
                encoding="utf-8",
            )
            definitions.write_text(json.dumps({LABEL_A: {"definition": "祈使句否定形式"}, LABEL_B: {"definition": "反身代词"}}, ensure_ascii=False), encoding="utf-8")

            report = build_input_status_pilot_packets(
                source,
                manifest_path=manifest,
                label_definitions_path=definitions,
                output_dir=output_dir,
                max_per_label=4,
                max_per_status=1,
            )

            self.assertEqual(report["labels"], 2)
            self.assertEqual(report["selected_records"], 4)
            rows = []
            for path in output_dir.glob("*.packet.jsonl"):
                rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line)
            self.assertEqual(len(rows), 4)
            self.assertTrue(all(row["schema_version"] == "final-label-discriminator-packet-v1" for row in rows))
            self.assertTrue(all("题型结构为：" not in row["question_text"] for row in rows))
            self.assertTrue(all("题型名称为：" not in row["question_text"] for row in rows))
            self.assertTrue(all("output" not in row and "input" not in row for row in rows))
            self.assertTrue(all("input_precheck" in row for row in rows))

    def test_rejects_unknown_manifest_label(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.jsonl"
            manifest = root / "manifest.json"
            definitions = root / "definitions.json"
            source.write_text("", encoding="utf-8")
            manifest.write_text(json.dumps({"schema_version": "input-status-pilot-label-manifest-v1", "labels": [LABEL_A]}), encoding="utf-8")
            definitions.write_text(json.dumps({}), encoding="utf-8")
            with self.assertRaises(ValueError):
                build_input_status_pilot_packets(
                    source,
                    manifest_path=manifest,
                    label_definitions_path=definitions,
                    output_dir=root / "packets",
                )


if __name__ == "__main__":
    unittest.main()
