import json
from pathlib import Path
import tempfile
import unittest


try:
    from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook
    from english_knowledge_tagger.knowledge_taxonomy_migration import load_knowledge_taxonomy_migration
    from english_knowledge_tagger.positive_candidate_manifest import (
        build_positive_candidate_manifest,
    )
except ImportError:
    load_knowledge_rulebook = None
    load_knowledge_taxonomy_migration = None
    build_positive_candidate_manifest = None


LABEL = "知识点@词汇@词汇辨析@测试标签"
BLOCKED = "知识点@词汇@词汇辨析@旧标签"
LOW_LCB = "知识点@词汇@词汇辨析@低下界标签"
TRUE_ERROR = "知识点@词汇@词汇辨析@正例错误标签"


def write_rulebook(path: Path) -> Path:
    path.write_text(
        "末级知识点,打标解读（标绿的标签，新题不再打）,大模型压缩+人工微调的释义\n"
        "知识点->词汇->词汇辨析->测试标签,测试标签,测试标签\n",
        encoding="utf-8",
    )
    return path


def write_migration(path: Path) -> Path:
    path.write_text(
        json.dumps({"schema_version": "knowledge-taxonomy-migration-v1", "rules": []}),
        encoding="utf-8",
    )
    return path


def row(label: str, match: str, true_audit: str) -> str:
    return f"| {label} | {match} | {true_audit} | 0/12 = 0.0% | 备注 |\n"


class PositiveCandidateManifestTests(unittest.TestCase):
    def test_manifest_requires_wilson_true_12_and_active_taxonomy(self):
        self.assertTrue(callable(build_positive_candidate_manifest))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            full = directory / "full.md"
            raw = directory / "raw.md"
            full.write_text(
                "| 末级知识点 | DS 匹配率 | True 采样准确率 | False 采样错判率 | 结论 |\n"
                "|---|---:|---:|---:|---|\n"
                + row(LABEL, "12/24 = 50.0%", "12/12 = 100.0%")
                + row(BLOCKED, "12/24 = 50.0%", "12/12 = 100.0%")
                + row(LOW_LCB, "12/24 = 50.0%", "12/12 = 100.0%")
                + row(TRUE_ERROR, "12/24 = 50.0%", "11/12 = 91.7%"),
                encoding="utf-8",
            )
            raw.write_text(
                "| 末级知识点 | DS 匹配率 | True 采样准确率 | False 采样错判率 | 结论 |\n"
                "|---|---:|---:|---:|---|\n"
                + row(LABEL, "400/500 = 80.0%", "12/12 = 100.0%")
                + row(BLOCKED, "400/500 = 80.0%", "12/12 = 100.0%")
                + row(LOW_LCB, "364/500 = 72.8%", "12/12 = 100.0%")
                + row(TRUE_ERROR, "400/500 = 80.0%", "11/12 = 91.7%"),
                encoding="utf-8",
            )
            output = directory / "manifest.json"
            report = build_positive_candidate_manifest(
                full,
                raw_yield_ledger_path=raw,
                rulebook=load_knowledge_rulebook(write_rulebook(directory / "rulebook.csv")),
                migration=load_knowledge_taxonomy_migration(write_migration(directory / "migration.json")),
                output_path=output,
            )
            manifest = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(report["candidate_records"], 1)
        self.assertEqual(manifest["candidates"][0]["legacy_label"], LABEL)
        self.assertEqual(
            manifest["candidates"][0]["human_true_audit"], {"retain": 12, "reviewed": 12}
        )
        self.assertNotIn("positive_disposition", manifest["candidates"][0])
        self.assertEqual(manifest["taxonomy_blocked"][0]["legacy_label"], BLOCKED)
        self.assertEqual(manifest["excluded"][0]["legacy_label"], LOW_LCB)
        self.assertEqual(manifest["excluded"][1]["legacy_label"], TRUE_ERROR)


if __name__ == "__main__":
    unittest.main()
