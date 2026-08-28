import hashlib
import json
from pathlib import Path
import tempfile
import unittest


try:
    from english_knowledge_tagger.candidate_final_packet_batch import (
        build_candidate_final_packet_batch,
    )
    from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook
except ImportError:
    build_candidate_final_packet_batch = None
    load_knowledge_rulebook = None


HARD_LEGACY = "知识点@词汇@词汇辨析@名词（短语）辨析"
HARD_CANONICAL = "知识点->词汇->词汇辨析->名词（短语）辨析"
SOFT_LEGACY = "知识点@词法@代词@反身代词"
SOFT_CANONICAL = "知识点->词法->代词->反身代词"
ALLOWED_ROUTE = "parent × 单选题 × 选择题"


def write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8"
    )
    return path


def write_rulebook(path: Path) -> Path:
    path.write_text(
        "末级知识点,打标解读（标绿的标签，新题不再打）,大模型压缩+人工微调的释义\n"
        f"{HARD_CANONICAL},题型范畴限定在：单选题（非复合题）；只有单选题打此类标签,释义\n"
        f"{SOFT_CANONICAL},常见题型：单选题、填空题；未限制题型,释义\n",
        encoding="utf-8",
    )
    return path


def write_manifest(path: Path) -> Path:
    return write_json(
        path,
        {
            "schema_version": "positive-candidate-manifest-v1",
            "candidates": [
                {"legacy_label": HARD_LEGACY, "canonical_label": HARD_CANONICAL},
                {"legacy_label": SOFT_LEGACY, "canonical_label": SOFT_CANONICAL},
            ],
        },
    )


def write_guidance(path: Path, manifest: Path) -> Path:
    return write_json(
        path,
        {
            "schema_version": "candidate-route-guidance-v1",
            "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            "default": {
                "mode": "soft_typical",
                "allowed_routes": [],
                "reason": "常见题型不是硬过滤。",
            },
            "hard_exclusive_overrides": [
                {
                    "legacy_label": HARD_LEGACY,
                    "canonical_label": HARD_CANONICAL,
                    "allowed_routes": [ALLOWED_ROUTE],
                    "csv_evidence": "题型范畴限定在：单选题（非复合题）",
                }
            ],
        },
    )


def source_row(
    question_id: str, *, output: str, structure: str, name: str, question: str
) -> dict[str, object]:
    return {
        "question_id": question_id,
        "parent_id": question_id,
        "is_sub_question": False,
        "instruction": "不得进入最终 packet",
        "input": (
            f"题型结构为：{structure}\n题型名称为：{name}\n"
            f"题目题干：{question}\n"
            "根据以上信息，当前题目所属的题型方法类目和知识点类目为："
        ),
        "output": output,
    }


class CandidateFinalPacketBatchTests(unittest.TestCase):
    def test_one_scan_uses_hard_route_filter_and_keeps_soft_routes(self):
        self.assertTrue(callable(build_candidate_final_packet_batch))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            manifest = write_manifest(directory / "manifest.json")
            source = write_jsonl(
                directory / "source.jsonl",
                [
                    source_row(
                        "1",
                        output=f"{HARD_LEGACY};{SOFT_LEGACY}",
                        structure="单选题",
                        name="选择题",
                        question="allowed",
                    ),
                    source_row(
                        "2",
                        output=f"{HARD_LEGACY};{SOFT_LEGACY}",
                        structure="填空题",
                        name="完成句子",
                        question="soft route remains eligible",
                    ),
                    {
                        "question_id": "3",
                        "parent_id": "3",
                        "is_sub_question": False,
                        "input": "题型结构为：填空题\n题型名称为：完成句子\n",
                        "output": SOFT_LEGACY,
                    },
                ],
            )
            definitions = write_json(
                directory / "definitions.json",
                {
                    HARD_LEGACY: {"definition": "名词辨析"},
                    SOFT_LEGACY: {"definition": "反身代词"},
                },
            )
            report = build_candidate_final_packet_batch(
                source,
                manifest_path=manifest,
                guidance_path=write_guidance(directory / "guidance.json", manifest),
                rulebook=load_knowledge_rulebook(write_rulebook(directory / "rulebook.csv")),
                label_definitions_path=definitions,
                output_dir=directory / "batch",
            )
            index = json.loads((directory / "batch" / "batch.index.json").read_text(encoding="utf-8"))
            hard = index["labels"][HARD_LEGACY]
            soft = index["labels"][SOFT_LEGACY]
            soft_rows = [
                json.loads(line)
                for line in (directory / "batch" / soft["packet_relative_path"])
                .read_text(encoding="utf-8")
                .splitlines()
            ]

        self.assertEqual(report["source_records"], 3)
        self.assertEqual(hard["selected_packet_records"], 1)
        self.assertEqual(hard["hard_route_hold_records"], 1)
        self.assertEqual(soft["selected_packet_records"], 2)
        self.assertEqual(soft["input_incomplete_hold_records"], 1)
        self.assertEqual([row["question_id"] for row in soft_rows], ["1", "2"])
        self.assertTrue(all(row["schema_version"] == "final-label-discriminator-packet-v1" for row in soft_rows))
        self.assertTrue(all("input" not in row and "output" not in row for row in soft_rows))
        self.assertTrue(all("题型结构为：" not in row["question_text"] for row in soft_rows))
        self.assertTrue(all("根据以上信息" not in row["question_text"] for row in soft_rows))


if __name__ == "__main__":
    unittest.main()
