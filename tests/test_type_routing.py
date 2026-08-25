import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

try:
    from english_knowledge_tagger.type_routing import (
        bootstrap_type_routing_policy,
        load_type_routing_policy,
        route_sft_record,
    )
    from english_knowledge_tagger.type_rulebook import load_type_rulebook
except (ImportError, ModuleNotFoundError):
    bootstrap_type_routing_policy = None
    load_type_routing_policy = None
    route_sft_record = None
    load_type_rulebook = None


RULE = {
    "rule_id": "route:child:复合题:阅读理解",
    "scope": "child",
    "declared_type_structure": "复合题",
    "declared_type_name": "阅读理解",
    "policy_status": "needs_review",
    "canonical_family": "reading",
    "type_selection_mode": "single",
    "candidate_type_prefixes": ["题型->阅读理解"],
    "knowledge_inheritance": "never",
    "knowledge_policy": "unresolved",
    "review_notes": "需要按小题内容细分阅读选择、问答等。",
}


def write_policy(path: Path, rules: list[dict[str, object]]) -> Path:
    path.write_text(
        json.dumps(
            {"schema_version": "type-routing-policy-v1", "rules": rules},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


class TypeRoutingPolicyTests(unittest.TestCase):
    def test_policy_rejects_duplicate_exact_keys_and_approved_rules_without_candidates(self):
        self.assertTrue(callable(load_type_routing_policy), "load_type_routing_policy must be implemented")
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            duplicate = write_policy(directory / "duplicate.json", [RULE, RULE])
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_type_routing_policy(duplicate)

            invalid = write_policy(
                directory / "invalid.json",
                [{**RULE, "policy_status": "approved", "candidate_type_prefixes": []}],
            )
            with self.assertRaisesRegex(ValueError, "approved"):
                load_type_routing_policy(invalid)

    def test_bootstrap_creates_one_unmapped_rule_for_each_inventory_key(self):
        self.assertTrue(
            callable(bootstrap_type_routing_policy),
            "bootstrap_type_routing_policy must be implemented",
        )
        policy = bootstrap_type_routing_policy(
            {
                "rows": [
                    {
                        "scope": "child",
                        "declared_type_structure": "复合题",
                        "declared_type_name": "阅读理解",
                    },
                    {
                        "scope": "parent",
                        "declared_type_structure": "单选题",
                        "declared_type_name": "选择题",
                    },
                ]
            }
        )

        self.assertEqual(policy["schema_version"], "type-routing-policy-v1")
        self.assertEqual(
            [rule["scope"] for rule in policy["rules"]],
            ["parent", "child"],
        )
        self.assertEqual(policy["rules"][1]["policy_status"], "unmapped")
        self.assertEqual(policy["rules"][1]["knowledge_inheritance"], "never")
        self.assertEqual(policy["rules"][1]["candidate_type_prefixes"], [])

    def test_policy_matches_only_the_exact_scope_structure_and_name(self):
        self.assertTrue(callable(load_type_routing_policy), "load_type_routing_policy must be implemented")
        with tempfile.TemporaryDirectory() as temp_dir:
            policy = load_type_routing_policy(write_policy(Path(temp_dir) / "policy.json", [RULE]))

        self.assertEqual(
            policy.match("child", "复合题", "阅读理解").rule_id,
            "route:child:复合题:阅读理解",
        )
        self.assertIsNone(policy.match("parent", "复合题", "阅读理解"))
        self.assertIsNone(policy.match("child", "复合题", "阅读还原"))

    def test_router_marks_legacy_labels_as_evidence_and_detects_deprecated_labels(self):
        self.assertTrue(callable(route_sft_record), "route_sft_record must be implemented")
        self.assertTrue(callable(load_type_rulebook), "load_type_rulebook must be implemented")
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            policy = load_type_routing_policy(
                write_policy(
                    directory / "policy.json",
                    [{**RULE, "policy_status": "approved"}],
                )
            )
            teacher_csv = directory / "teacher.csv"
            teacher_csv.write_text(
                "末级知识点,打标解读（标绿的标签，新题不再打）\n"
                "题型->阅读理解->阅读选择->细节理解,小题打此标签\n"
                "题型->阅读理解->阅读理解（综合）,新题不用打\n",
                encoding="utf-8",
            )
            rulebook = load_type_rulebook(teacher_csv)

            route = route_sft_record(
                {
                    "question_id": "child-1",
                    "parent_id": "parent-1",
                    "is_sub_question": True,
                    "input": "题型结构为：复合题\n题型名称为：阅读理解\n当前小题题干：...",
                    "output": "题型@阅读理解@阅读理解（综合）;知识点@语篇主题@学校生活",
                },
                source_line=7,
                policy=policy,
                rulebook=rulebook,
            )

        self.assertEqual(route["legacy_type_labels"], ["题型->阅读理解->阅读理解（综合）"])
        self.assertEqual(route["route"]["knowledge_inheritance"], "never")
        self.assertEqual(
            route["route"]["candidate_type_paths"],
            ["题型->阅读理解->阅读选择->细节理解"],
        )
        self.assertIn("legacy_type_deprecated", route["risk_codes"])
        self.assertEqual(route["source_line"], 7)

    def test_router_marks_missing_policy_without_using_historical_type_as_a_route(self):
        self.assertTrue(callable(route_sft_record), "route_sft_record must be implemented")
        self.assertTrue(callable(load_type_rulebook), "load_type_rulebook must be implemented")
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            policy = load_type_routing_policy(write_policy(directory / "policy.json", []))
            teacher_csv = directory / "teacher.csv"
            teacher_csv.write_text(
                "末级知识点,打标解读（标绿的标签，新题不再打）\n"
                "题型->阅读理解->阅读选择->细节理解,小题打此标签\n",
                encoding="utf-8",
            )
            route = route_sft_record(
                {
                    "question_id": "child-1",
                    "parent_id": "parent-1",
                    "is_sub_question": True,
                    "input": "题型结构为：复合题\n题型名称为：阅读理解\n当前小题题干：...",
                    "output": "题型@阅读理解@阅读选择@细节理解",
                },
                source_line=3,
                policy=policy,
                rulebook=load_type_rulebook(teacher_csv),
            )

        self.assertEqual(route["route"]["policy_status"], "unmapped")
        self.assertEqual(route["route"]["candidate_type_paths"], [])
        self.assertIn("unmapped_policy", route["risk_codes"])

    def test_route_cli_writes_routes_and_summary_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = directory / "source.jsonl"
            source.write_text(
                json.dumps(
                    {
                        "question_id": "child-1",
                        "parent_id": "parent-1",
                        "is_sub_question": True,
                        "input": "题型结构为：复合题\n题型名称为：阅读理解\n当前小题题干：...",
                        "output": "题型@阅读理解@阅读选择@细节理解",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            policy = write_policy(
                directory / "policy.json",
                [{**RULE, "policy_status": "approved"}],
            )
            teacher_csv = directory / "teacher.csv"
            teacher_csv.write_text(
                "末级知识点,打标解读（标绿的标签，新题不再打）\n"
                "题型->阅读理解->阅读选择->细节理解,小题打此标签\n",
                encoding="utf-8",
            )
            output = directory / "routes.jsonl"
            report = directory / "report.json"
            script = Path(__file__).resolve().parents[1] / "scripts" / "route_question_types.py"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--input",
                    str(source),
                    "--policy",
                    str(policy),
                    "--teacher-csv",
                    str(teacher_csv),
                    "--output",
                    str(output),
                    "--report",
                    str(report),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                json.loads(report.read_text(encoding="utf-8"))["route_status_counts"],
                {"approved": 1},
            )
            self.assertEqual(len(output.read_text(encoding="utf-8").splitlines()), 1)

    def test_route_cli_refuses_to_overwrite_existing_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = directory / "source.jsonl"
            source.write_text("", encoding="utf-8")
            policy = write_policy(directory / "policy.json", [])
            teacher_csv = directory / "teacher.csv"
            teacher_csv.write_text(
                "末级知识点,打标解读（标绿的标签，新题不再打）\n",
                encoding="utf-8",
            )
            output = directory / "routes.jsonl"
            output.write_text("do not overwrite\n", encoding="utf-8")
            report = directory / "report.json"
            script = Path(__file__).resolve().parents[1] / "scripts" / "route_question_types.py"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--input",
                    str(source),
                    "--policy",
                    str(policy),
                    "--teacher-csv",
                    str(teacher_csv),
                    "--output",
                    str(output),
                    "--report",
                    str(report),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("refusing to overwrite", completed.stderr)
            self.assertEqual(output.read_text(encoding="utf-8"), "do not overwrite\n")


if __name__ == "__main__":
    unittest.main()
