import hashlib
import json
from pathlib import Path
import tempfile
import unittest


try:
    from english_knowledge_tagger.candidate_route_guidance import (
        build_candidate_route_guidance_report,
        load_candidate_route_guidance,
    )
    from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook
except ImportError:
    build_candidate_route_guidance_report = None
    load_candidate_route_guidance = None
    load_knowledge_rulebook = None


HARD_LEGACY = "知识点@词汇@词汇辨析@名词（短语）辨析"
HARD_CANONICAL = "知识点->词汇->词汇辨析->名词（短语）辨析"
SOFT_LEGACY = "知识点@词法@代词@反身代词"
SOFT_CANONICAL = "知识点->词法->代词->反身代词"
ALLOWED_ROUTE = "parent × 单选题 × 选择题"


def write_rulebook(path: Path) -> Path:
    path.write_text(
        "末级知识点,打标解读（标绿的标签，新题不再打）,大模型压缩+人工微调的释义\n"
        f"{HARD_CANONICAL},题型范畴限定在：单选题（非复合题）；只有单选题打此类标签,释义\n"
        f"{SOFT_CANONICAL},常见题型：单选题、填空题；未限制题型,释义\n",
        encoding="utf-8",
    )
    return path


def write_manifest(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "positive-candidate-manifest-v1",
                "candidates": [
                    {"legacy_label": HARD_LEGACY, "canonical_label": HARD_CANONICAL},
                    {"legacy_label": SOFT_LEGACY, "canonical_label": SOFT_CANONICAL},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def write_guidance(path: Path, manifest: Path, *, override_label: str = HARD_LEGACY) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "candidate-route-guidance-v1",
                "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                "default": {
                    "mode": "soft_typical",
                    "allowed_routes": [],
                    "reason": "常见题型不是硬过滤条件。",
                },
                "hard_exclusive_overrides": [
                    {
                        "legacy_label": override_label,
                        "canonical_label": HARD_CANONICAL,
                        "allowed_routes": [ALLOWED_ROUTE],
                        "csv_evidence": "题型范畴限定在：单选题（非复合题）；只有单选题打此类标签",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


class CandidateRouteGuidanceTests(unittest.TestCase):
    def test_default_soft_guidance_and_explicit_hard_override(self):
        self.assertTrue(callable(load_candidate_route_guidance))
        self.assertTrue(callable(build_candidate_route_guidance_report))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            manifest = write_manifest(directory / "manifest.json")
            rulebook = load_knowledge_rulebook(write_rulebook(directory / "rulebook.csv"))
            guidance = load_candidate_route_guidance(
                write_guidance(directory / "guidance.json", manifest),
                manifest_path=manifest,
                rulebook=rulebook,
            )
            report = build_candidate_route_guidance_report(guidance)

        self.assertEqual(guidance.mode_for(HARD_LEGACY).mode, "hard_exclusive")
        self.assertEqual(guidance.mode_for(HARD_LEGACY).allowed_routes, (ALLOWED_ROUTE,))
        self.assertEqual(guidance.mode_for(SOFT_LEGACY).mode, "soft_typical")
        self.assertEqual(guidance.mode_for(SOFT_LEGACY).allowed_routes, ())
        self.assertEqual(report["hard_exclusive_count"], 1)
        self.assertEqual(report["soft_typical_count"], 1)

    def test_rejects_hard_override_outside_manifest(self):
        self.assertTrue(callable(load_candidate_route_guidance))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            manifest = write_manifest(directory / "manifest.json")
            rulebook = load_knowledge_rulebook(write_rulebook(directory / "rulebook.csv"))
            guidance_path = write_guidance(
                directory / "guidance.json", manifest, override_label="知识点@词汇@不存在标签"
            )

            with self.assertRaisesRegex(ValueError, "not present in candidate manifest"):
                load_candidate_route_guidance(
                    guidance_path, manifest_path=manifest, rulebook=rulebook
                )


if __name__ == "__main__":
    unittest.main()
