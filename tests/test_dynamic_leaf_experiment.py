import csv
from pathlib import Path
import tempfile
import unittest

from english_knowledge_tagger.dynamic_leaf_experiment import (
    build_dynamic_candidate_verifier_packet,
    build_dynamic_leaf_tasks,
    summarize_dynamic_leaf_experiment,
)
from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook


class DynamicLeafExperimentTests(unittest.TestCase):
    def test_task_builder_requires_three_non_target_decisions(self):
        packet = (
            {
                "review_id": "D2:q1",
                "question_id": "q1",
                "parent_id": "q1",
                "canonical_label": "old-label",
                "legacy_label": "legacy-old",
                "definition_variant": "D2",
                "question_text": "question one",
                "route_key": {"scope": "parent"},
                "pseudo_gold_decision": "remove",
                "split": "locked_test",
            },
            {
                "review_id": "D2:q2",
                "question_id": "q2",
                "parent_id": "q2",
                "canonical_label": "old-label",
                "legacy_label": "legacy-old",
                "definition_variant": "D2",
                "question_text": "question two",
                "route_key": {"scope": "parent"},
                "pseudo_gold_decision": "remove",
                "split": "locked_test",
            },
        )
        base = (
            {"review_id": "D2:q1", "decision": "non_target", "confidence": "high"},
            {"review_id": "D2:q2", "decision": "non_target", "confidence": "high"},
        )
        third = (
            {"review_id": "D2:q1", "decision": "non_target", "confidence": "high"},
            {"review_id": "D2:q2", "decision": "keep", "confidence": "high"},
        )
        ambiguity = {
            "labels": [
                {
                    "canonical_label": "old-label",
                    "confusion_neighbors": [
                        {"canonical_label": "new-label", "count": 7}
                    ],
                }
            ]
        }
        tasks, holds, report = build_dynamic_leaf_tasks(
            packet,
            direct_runs=(("r1", base), ("r2", base), ("r3", third)),
            ambiguity_manifest=ambiguity,
            selected_variant_by_label={"old-label": "D2"},
            teacher_gold_by_question={"q1": ("new-label",)},
        )
        self.assertEqual([task["question_id"] for task in tasks], ["q1"])
        self.assertEqual([hold["question_id"] for hold in holds], ["q2"])
        self.assertEqual(tasks[0]["confusion_counts"], {"new-label": 7})
        self.assertEqual(tasks[0]["teacher_gold_labels"], ["new-label"])
        self.assertEqual(report["eligible_tasks"], 1)

    def test_summary_requires_unanimous_candidate_and_high_keep_verification(self):
        tasks = (
            {
                "review_id": "dynamic:q1",
                "question_id": "q1",
                "pseudo_gold_decision": "remove",
                "teacher_gold_labels": ["new-label"],
            },
            {
                "review_id": "dynamic:q2",
                "question_id": "q2",
                "pseudo_gold_decision": "uncertain",
                "teacher_gold_labels": [],
            },
        )
        resolver_rows = (
            {
                "review_id": "dynamic:q1",
                "status": "candidate",
                "candidate_label": "new-label",
                "call_count": 2,
            },
            {
                "review_id": "dynamic:q2",
                "status": "candidate",
                "candidate_label": "other-label",
                "call_count": 1,
            },
        )
        verifier_rows = (
            {
                "source_review_id": "dynamic:q1",
                "decision": "keep",
                "confidence": "high",
            },
            {
                "source_review_id": "dynamic:q2",
                "decision": "keep",
                "confidence": "high",
            },
        )
        summary = summarize_dynamic_leaf_experiment(
            tasks,
            resolver_runs=(("r1", resolver_rows), ("r2", resolver_rows), ("r3", resolver_rows)),
            verifier_runs=(("v1", verifier_rows), ("v2", verifier_rows), ("v3", verifier_rows)),
            root_baseline_mean_calls=5.0,
        )
        decisions = {row["question_id"]: row for row in summary["decisions"]}
        self.assertEqual(decisions["q1"]["disposition"], "stable_relabel_candidate")
        self.assertEqual(decisions["q2"]["disposition"], "hold")
        self.assertEqual(summary["metrics"]["unanimous_candidate_precision"], 1.0)
        self.assertEqual(summary["metrics"]["teacher_gold_candidate_accuracy"], 1.0)
        self.assertEqual(summary["metrics"]["forced_candidate_on_uncertain"], 1)
        self.assertGreaterEqual(summary["metrics"]["mean_call_reduction"], 0.30)

    def test_non_unanimous_resolver_needs_no_verifier_row_and_holds(self):
        tasks = (
            {"review_id": "dynamic:q1", "question_id": "q1", "pseudo_gold_decision": "remove", "teacher_gold_labels": ["new"]},
            {"review_id": "dynamic:q2", "question_id": "q2", "pseudo_gold_decision": "remove", "teacher_gold_labels": []},
        )
        r1 = (
            {"review_id": "dynamic:q1", "status": "candidate", "candidate_label": "new", "call_count": 1},
            {"review_id": "dynamic:q2", "status": "candidate", "candidate_label": "a", "call_count": 1},
        )
        r2 = (
            {"review_id": "dynamic:q1", "status": "candidate", "candidate_label": "new", "call_count": 1},
            {"review_id": "dynamic:q2", "status": "candidate", "candidate_label": "b", "call_count": 1},
        )
        verifier = (
            {"source_review_id": "dynamic:q1", "decision": "keep", "confidence": "high"},
        )
        summary = summarize_dynamic_leaf_experiment(
            tasks,
            resolver_runs=(("r1", r1), ("r2", r2), ("r3", r1)),
            verifier_runs=(("v1", verifier), ("v2", verifier), ("v3", verifier)),
            root_baseline_mean_calls=4.0,
        )
        decisions = {row["question_id"]: row for row in summary["decisions"]}
        self.assertEqual(decisions["q1"]["disposition"], "stable_relabel_candidate")
        self.assertEqual(decisions["q2"]["disposition"], "hold")

    def test_candidate_verifier_packet_uses_only_unanimous_candidates(self):
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
                        "末级知识点": "知识点->词汇->构词法->派生法",
                        "打标解读（标绿的标签，新题不再打）": "词缀派生",
                        "大模型压缩+人工微调的释义": "词缀派生",
                    }
                )
            rulebook = load_knowledge_rulebook(teacher)
            tasks = (
                {
                    "review_id": "dynamic:q1",
                    "question_id": "q1",
                    "parent_id": "q1",
                    "question_text": "direct变为director",
                    "route_key": {"scope": "parent"},
                },
            )
            rows = (
                {
                    "review_id": "dynamic:q1",
                    "status": "candidate",
                    "candidate_label": "知识点->词汇->构词法->派生法",
                },
            )
            packet = build_dynamic_candidate_verifier_packet(
                tasks,
                resolver_runs=(("r1", rows), ("r2", rows), ("r3", rows)),
                rulebook=rulebook,
            )
            self.assertEqual(len(packet), 1)
            self.assertEqual(packet[0]["source_review_id"], "dynamic:q1")
            self.assertEqual(packet[0]["definition_text"], "词缀派生")
            self.assertEqual(packet[0]["canonical_label"], "知识点->词汇->构词法->派生法")


if __name__ == "__main__":
    unittest.main()
