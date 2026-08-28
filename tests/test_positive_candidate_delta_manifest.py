import hashlib
import json
from pathlib import Path
import tempfile
import unittest


try:
    from english_knowledge_tagger.positive_candidate_delta_manifest import (
        build_positive_candidate_delta_manifest,
    )
except ImportError:
    build_positive_candidate_delta_manifest = None


OLD_LABEL = "知识点@词法@测试@旧标签"
NEW_LABEL = "知识点@词法@测试@新标签"
OLD_CANONICAL = "知识点->词法->测试->旧标签"
NEW_CANONICAL = "知识点->词法->测试->新标签"


def candidate(legacy_label: str, canonical_label: str) -> dict[str, object]:
    return {
        "legacy_label": legacy_label,
        "canonical_label": canonical_label,
        "raw_yield": {"matches": 400, "sample_size": 500, "match_rate": 0.8},
        "human_true_audit": {"retain": 12, "reviewed": 12},
    }


def write_manifest(path: Path, candidates: list[dict[str, object]]) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "positive-candidate-manifest-v1",
                "purpose": "non_releasing_positive_candidate_work_queue",
                "criteria": {"wilson_lower_one_sided_95_minimum": 0.70},
                "inputs": {"full_sample_ledger_sha256": "full", "raw_yield_ledger_sha256": "raw"},
                "candidates": candidates,
                "taxonomy_blocked": [],
                "excluded": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


class PositiveCandidateDeltaManifestTests(unittest.TestCase):
    def test_delta_contains_only_new_latest_candidates_and_records_lineage(self):
        self.assertTrue(callable(build_positive_candidate_delta_manifest))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            base = write_manifest(directory / "base.json", [candidate(OLD_LABEL, OLD_CANONICAL)])
            base_sha256 = hashlib.sha256(base.read_bytes()).hexdigest()
            latest = write_manifest(
                directory / "latest.json",
                [candidate(OLD_LABEL, OLD_CANONICAL), candidate(NEW_LABEL, NEW_CANONICAL)],
            )
            output = directory / "delta.json"
            report = build_positive_candidate_delta_manifest(
                latest_manifest_path=latest,
                base_manifest_path=base,
                output_path=output,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(report["delta_candidate_records"], 1)
        self.assertEqual(payload["candidates"][0]["legacy_label"], NEW_LABEL)
        self.assertEqual(payload["base_manifest_sha256"], base_sha256)
        self.assertEqual(payload["inputs"]["full_sample_ledger_sha256"], "full")

    def test_delta_rejects_base_label_missing_from_latest(self):
        self.assertTrue(callable(build_positive_candidate_delta_manifest))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            base = write_manifest(directory / "base.json", [candidate(OLD_LABEL, OLD_CANONICAL)])
            latest = write_manifest(directory / "latest.json", [candidate(NEW_LABEL, NEW_CANONICAL)])
            with self.assertRaisesRegex(ValueError, "not present in latest manifest"):
                build_positive_candidate_delta_manifest(
                    latest_manifest_path=latest,
                    base_manifest_path=base,
                    output_path=directory / "delta.json",
                )


if __name__ == "__main__":
    unittest.main()
