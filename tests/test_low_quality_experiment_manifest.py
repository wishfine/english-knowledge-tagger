import csv
import json
from pathlib import Path
import tempfile
import unittest

from english_knowledge_tagger.low_quality_experiment_manifest import (
    load_low_quality_experiment_manifest,
    prepare_low_quality_definition_batch,
)


class LowQualityExperimentManifestTests(unittest.TestCase):
    def test_loads_env_paths_and_prepares_one_label_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            teacher = root / "teacher.csv"
            with teacher.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=(
                        "末级知识点",
                        "打标解读（标绿的标签，新题不再打）",
                        "大模型压缩+人工微调的释义",
                    ),
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "末级知识点": "知识点->语用->时间->顺序",
                        "打标解读（标绿的标签，新题不再打）": "事件先后",
                        "大模型压缩+人工微调的释义": "步骤或事件先后",
                    }
                )
            overrides = root / "overrides.json"
            overrides.write_text(
                json.dumps(
                    {
                        "schema_version": "knowledge-definition-overrides-v1",
                        "overrides": [
                            {
                                "label": "知识点->语用->时间->顺序",
                                "replacement_definition": "比较两个事件的先后；不标时段。",
                                "status": "active_for_experiment",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            migration = root / "migration.json"
            migration.write_text(
                json.dumps(
                    {"schema_version": "knowledge-taxonomy-migration-v1", "rules": []}
                ),
                encoding="utf-8",
            )
            samples = root / "samples.jsonl"
            sample = {
                "verify_label": "知识点@语用@时间@顺序",
                "question_id": "q1",
                "parent_id": "q1",
                "is_sub_question": False,
                "input": "题型结构为：单选题\n题型名称为：选择题\n题目题干：先做什么？",
                "output_all": "知识点@语用@时间@顺序",
            }
            samples.write_text(json.dumps(sample, ensure_ascii=False) + "\n", encoding="utf-8")
            results = root / "results.jsonl"
            result = {
                "verify_label": "知识点@语用@时间@顺序",
                "question_id": "q1",
                "llm_match": True,
                "llm_reason": "顺序",
                "llm_should_be": "正确",
            }
            results.write_text(json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8")
            gold = root / "gold.jsonl"
            gold.write_text(
                json.dumps(
                    {
                        "verify_label": "知识点@语用@时间@顺序",
                        "question_id": "q1",
                        "decision": "keep",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": "low-quality-definition-experiment-manifest-v1",
                        "teacher_csv": "${DATA_ROOT}/teacher.csv",
                        "definition_overrides": "${DATA_ROOT}/overrides.json",
                        "taxonomy_migration": "${DATA_ROOT}/migration.json",
                        "mentor_samples": "${DATA_ROOT}/samples.jsonl",
                        "mentor_results": "${DATA_ROOT}/results.jsonl",
                        "pseudo_gold_sources": [
                            {
                                "legacy_label": "知识点@语用@时间@顺序",
                                "path": "${DATA_ROOT}/gold.jsonl",
                                "expected_records": 1,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manifest = load_low_quality_experiment_manifest(
                manifest_path, environment={"DATA_ROOT": str(root)}, check_paths=True
            )
            output_root = root / "batch"
            report = prepare_low_quality_definition_batch(
                manifest, output_root=output_root, seed="seed"
            )
            self.assertEqual(report["labels"], 1)
            index = json.loads((output_root / "batch.index.json").read_text(encoding="utf-8"))
            item = index["labels"][0]
            self.assertEqual(item["questions"], 1)
            self.assertEqual(item["packet_rows"], 3)
            self.assertTrue(Path(item["packet_path"]).is_file())

    def test_rejects_duplicate_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "manifest.json"
            source = {
                "legacy_label": "知识点@语用@时间@顺序",
                "path": "x.jsonl",
                "expected_records": 1,
            }
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "low-quality-definition-experiment-manifest-v1",
                        "teacher_csv": "a",
                        "definition_overrides": "b",
                        "taxonomy_migration": "c",
                        "mentor_samples": "d",
                        "mentor_results": "e",
                        "pseudo_gold_sources": [source, source],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_low_quality_experiment_manifest(path, check_paths=False)


if __name__ == "__main__":
    unittest.main()
