import json
from pathlib import Path
import tempfile
import unittest


try:
    from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook
    from english_knowledge_tagger.knowledge_taxonomy_migration import load_knowledge_taxonomy_migration
    from english_knowledge_tagger.positive_candidate_inventory import (
        inventory_positive_candidate_batch,
    )
except ImportError:
    load_knowledge_rulebook = None
    load_knowledge_taxonomy_migration = None
    inventory_positive_candidate_batch = None


LABEL_A = "知识点@词汇@词汇辨析@标签A"
LABEL_B = "知识点@词汇@词汇辨析@标签B"
LABEL_C = "知识点@词汇@词汇辨析@标签C"


def canonical(label: str) -> str:
    return "知识点->" + label.removeprefix("知识点@").replace("@", "->")


def write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def write_rulebook(path: Path) -> Path:
    path.write_text(
        "末级知识点,打标解读（标绿的标签，新题不再打）,大模型压缩+人工微调的释义\n"
        "知识点->词汇->词汇辨析->标签A,标签A,标签A\n"
        "知识点->词汇->词汇辨析->标签B,标签B,标签B\n"
        "知识点->词汇->词汇辨析->标签C,标签C,标签C\n",
        encoding="utf-8",
    )
    return path


def write_migration(path: Path) -> Path:
    return write_json(path, {"schema_version": "knowledge-taxonomy-migration-v1", "rules": []})


def source_row(question_id: str, *, output: str, structure: str, name: str) -> dict[str, object]:
    return {
        "question_id": question_id,
        "parent_id": question_id,
        "is_sub_question": False,
        "instruction": "不得进入 route review 输出",
        "input": (
            f"题型结构为：{structure}\n题型名称为：{name}\n"
            f"题目题干：{question_id}\n"
            "根据以上信息，当前题目所属的题型方法类目和知识点类目为："
        ),
        "output": output,
    }


class PositiveCandidateInventoryTests(unittest.TestCase):
    def test_inventory_counts_matching_labels_and_predicts_complete_queue_coverage(self):
        self.assertTrue(callable(inventory_positive_candidate_batch))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            manifest = write_json(
                directory / "manifest.json",
                {
                    "schema_version": "positive-candidate-manifest-v1",
                    "candidates": [
                        {"legacy_label": LABEL_A, "canonical_label": canonical(LABEL_A)},
                        {"legacy_label": LABEL_B, "canonical_label": canonical(LABEL_B)},
                    ],
                },
            )
            source = write_jsonl(
                directory / "source.jsonl",
                [
                    source_row(
                        "1",
                        output=f"{LABEL_A};{LABEL_B}",
                        structure="单选题",
                        name="选择题",
                    ),
                    source_row(
                        "2",
                        output=f"{LABEL_A};{LABEL_C}",
                        structure="填空题",
                        name="完成句子",
                    ),
                    source_row("3", output=LABEL_C, structure="单选题", name="选择题"),
                ],
            )
            inventory_path = directory / "inventory.json"
            samples_path = directory / "route-samples.jsonl"
            report = inventory_positive_candidate_batch(
                source,
                manifest_path=manifest,
                rulebook=load_knowledge_rulebook(write_rulebook(directory / "rulebook.csv")),
                migration=load_knowledge_taxonomy_migration(write_migration(directory / "migration.json")),
                inventory_output_path=inventory_path,
                route_samples_output_path=samples_path,
                sample_size_per_route=2,
                seed="test-seed",
            )
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            samples = [json.loads(line) for line in samples_path.read_text(encoding="utf-8").splitlines()]

        first_route = "parent × 单选题 × 选择题"
        second_route = "parent × 填空题 × 完成句子"
        label_a = inventory["labels"][LABEL_A]
        self.assertEqual(report["source_records"], 3)
        self.assertEqual(label_a["route_counts"][first_route], 1)
        self.assertEqual(label_a["route_counts"][second_route], 1)
        self.assertEqual(label_a["coverage"]["all_active_labels_in_candidate_queue"], 1)
        self.assertEqual(label_a["coverage"]["has_active_labels_outside_candidate_queue"], 1)
        self.assertEqual(label_a["coverage"]["missing_active_label_counts"][canonical(LABEL_C)], 1)
        self.assertEqual(len(samples), 3)
        self.assertTrue(all("output_all" not in row and "instruction" not in row for row in samples))
        self.assertTrue(all("题型结构为：" not in row["question_text"] for row in samples))


if __name__ == "__main__":
    unittest.main()
