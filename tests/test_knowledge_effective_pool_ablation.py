import json
from pathlib import Path
import tempfile
import unittest

try:
    from english_knowledge_tagger.knowledge_effective_pool_ablation import (
        build_effective_pool_ablation_packets,
    )
except ModuleNotFoundError:
    build_effective_pool_ablation_packets = None


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def packet_row(
    review_id: str, *, suffix: str, alternative_labels: list[str] | None = None
) -> dict[str, object]:
    return {
        "review_id": review_id,
        "source_line": 10 if suffix == "effective" else 20,
        "question_id": f"q-{suffix}",
        "parent_id": f"p-{suffix}",
        "canonical_label": "知识点->词法->被动语态->一般过去时的被动语态",
        "question_context": f"题干：{suffix}",
        "alternative_labels": [
            {"label": label, "definition": "", "source": "sibling"}
            for label in (alternative_labels or [])
        ],
    }


def coverage_row(review_id: str, *, effective: bool) -> dict[str, object]:
    suffix = "effective" if effective else "reclassified"
    return {
        "review_id": review_id,
        "source_line": 10 if effective else 20,
        "question_id": f"q-{suffix}",
        "parent_id": f"p-{suffix}",
        "canonical_label": "知识点->词法->被动语态->一般过去时的被动语态",
        "target_parent_path": "知识点->词法->被动语态",
        "newly_available_alternative_labels": (
            ["知识点->词法->被动语态->过去进行时的被动语态"] if effective else []
        ),
        "reclassified_retrieval_labels": (
            [] if effective else ["知识点->词法->被动语态->过去进行时的被动语态"]
        ),
    }


class KnowledgeEffectivePoolAblationTests(unittest.TestCase):
    def test_builder_emits_only_effective_coverage_rows_in_same_order_for_both_modes(self):
        self.assertTrue(
            callable(build_effective_pool_ablation_packets),
            "build_effective_pool_ablation_packets must be implemented",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            effective_id = "kp-validation:effective"
            reclassified_id = "kp-validation:reclassified"
            baseline = write_jsonl(
                directory / "v01.jsonl",
                [packet_row(effective_id, suffix="effective"), packet_row(reclassified_id, suffix="reclassified")],
            )
            candidate = write_jsonl(
                directory / "v02.jsonl",
                [
                    packet_row(
                        effective_id,
                        suffix="effective",
                        alternative_labels=["知识点->词法->被动语态->过去进行时的被动语态"],
                    ),
                    packet_row(reclassified_id, suffix="reclassified"),
                ],
            )
            coverage = write_jsonl(
                directory / "coverage.jsonl",
                [coverage_row(effective_id, effective=True), coverage_row(reclassified_id, effective=False)],
            )
            baseline_output = directory / "v01.effective.jsonl"
            candidate_output = directory / "v02.effective.jsonl"

            report = build_effective_pool_ablation_packets(
                baseline,
                candidate,
                coverage,
                baseline_output_path=baseline_output,
                candidate_output_path=candidate_output,
            )
            baseline_rows = [json.loads(line) for line in baseline_output.read_text(encoding="utf-8").splitlines()]
            candidate_rows = [json.loads(line) for line in candidate_output.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(report["selected_rows"], 1)
        self.assertEqual(report["selected_rows_by_target_parent"], {"知识点->词法->被动语态": 1})
        self.assertEqual([row["review_id"] for row in baseline_rows], [effective_id])
        self.assertEqual([row["review_id"] for row in candidate_rows], [effective_id])
        self.assertEqual(
            report["newly_available_labels"],
            ["知识点->词法->被动语态->过去进行时的被动语态"],
        )


if __name__ == "__main__":
    unittest.main()
