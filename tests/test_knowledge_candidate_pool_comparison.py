import json
from pathlib import Path
import tempfile
import unittest

try:
    from english_knowledge_tagger.knowledge_candidate_pool_comparison import (
        compare_knowledge_candidate_pools,
    )
except ModuleNotFoundError:
    compare_knowledge_candidate_pools = None


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def packet_row(*, sibling_labels: list[str], include_route_key: bool = False) -> dict[str, object]:
    return {
        "review_id": "kp-validation:q-1:知识点@词法@被动语态@一般现在时的被动语态",
        "source_line": 12,
        "question_id": "q-1",
        "parent_id": "p-1",
        "canonical_label": "知识点->词法->被动语态->一般现在时的被动语态",
        "candidate_pool": {
            "sibling_selection": "limited_direct_leaves",
            "direct_sibling_count": len(sibling_labels),
        },
        "alternative_labels": [
            {"label": label, "definition": "", "source": "sibling"}
            for label in sibling_labels
        ]
        + [
            {
                "label": "知识点->句法->简单句->陈述句",
                "definition": "",
                "source": "type_retrieval",
            }
        ],
    } | (
        {
            "route_key": {
                "scope": "child",
                "declared_type_structure": "复合题",
                "declared_type_name": "语法选择",
            }
        }
        if include_route_key
        else {}
    )


class KnowledgeCandidatePoolComparisonTests(unittest.TestCase):
    def test_comparison_emits_only_newly_exposed_direct_siblings(self):
        self.assertTrue(
            callable(compare_knowledge_candidate_pools),
            "compare_knowledge_candidate_pools must be implemented",
        )
        existing = "知识点->词法->被动语态->一般过去时的被动语态"
        newly_exposed = "知识点->词法->被动语态->一般将来时的被动语态"
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            baseline = write_jsonl(directory / "v01.jsonl", [packet_row(sibling_labels=[existing])])
            candidate = write_jsonl(
                directory / "v02.jsonl", [packet_row(sibling_labels=[existing, newly_exposed])]
            )
            output = directory / "coverage.jsonl"

            report = compare_knowledge_candidate_pools(
                baseline,
                candidate,
                output_path=output,
            )
            row = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(report["matched_rows"], 1)
        self.assertEqual(report["expanded_rows"], 1)
        self.assertEqual(report["unchanged_rows"], 0)
        self.assertEqual(row["baseline_sibling_labels"], [existing])
        self.assertEqual(row["candidate_sibling_labels"], [existing, newly_exposed])
        self.assertEqual(row["newly_exposed_sibling_labels"], [newly_exposed])
        self.assertEqual(row["target_parent_path"], "知识点->词法->被动语态")
        self.assertIsNone(row["route_key"])


if __name__ == "__main__":
    unittest.main()
