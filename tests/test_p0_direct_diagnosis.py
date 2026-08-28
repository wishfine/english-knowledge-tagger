import json
from pathlib import Path
import tempfile
import unittest


try:
    from english_knowledge_tagger.p0_direct_diagnosis import (
        build_p0_direct_diagnosis_packets,
    )
    from english_knowledge_tagger.knowledge_taxonomy_migration import (
        KnowledgeTaxonomyAlias,
        KnowledgeTaxonomyMigration,
    )
except ImportError:
    build_p0_direct_diagnosis_packets = None
    KnowledgeTaxonomyAlias = None
    KnowledgeTaxonomyMigration = None


LABEL = "知识点@语法词法@动词@实义动词@及物动词"


def _migration():
    return KnowledgeTaxonomyMigration(
        aliases=(
            KnowledgeTaxonomyAlias(
                rule_id="legacy-grammar-wording-to-morphology",
                source_prefix="知识点->语法词法",
                target_prefix="知识点->词法",
            ),
        )
    )


def _row(
    question_id: str,
    *,
    direct_match: bool,
    should_be: str,
    structure: str = "填空题",
    name: str = "单词拼写",
) -> dict[str, object]:
    return {
        "verify_label": LABEL,
        "question_id": question_id,
        "parent_id": f"parent-{question_id}",
        "is_sub_question": False,
        "input": (
            f"题型结构为：{structure}\n"
            f"题型名称为：{name}\n"
            f"题目题干：{question_id} has an object.\n"
            "题目解析：test explanation\n"
            f"题目答案：{question_id}"
        ),
        "output_all": f"{LABEL};知识点@词汇@固定搭配/句型",
        "llm_match": direct_match,
        "llm_reason": f"reason-{question_id}",
        "llm_should_be": should_be,
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


class P0DirectDiagnosisTests(unittest.TestCase):
    def test_builds_blind_true_and_stratified_false_packets(self):
        self.assertTrue(callable(build_p0_direct_diagnosis_packets))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            input_path = _write_jsonl(
                directory / "verification.jsonl",
                [
                    _row("true-a", direct_match=True, should_be="正确"),
                    _row("true-b", direct_match=True, should_be="正确", name="完成句子"),
                    _row(
                        "false-fixed",
                        direct_match=False,
                        should_be="知识点@词汇@固定搭配/句型;知识点@语法词法@动词@实义动词@及物动词",
                    ),
                    _row(
                        "false-tense",
                        direct_match=False,
                        should_be="知识点@语法词法@动词时态@一般现在时@一般现在时的定义/判定",
                    ),
                    _row(
                        "false-question",
                        direct_match=False,
                        should_be="知识点@语法句法@句子种类@疑问句@一般疑问句",
                        structure="单选题",
                        name="选择题",
                    ),
                    _row(
                        "false-extra",
                        direct_match=False,
                        should_be="知识点@语法词法@动词@助动词@do/does/did作助动词",
                    ),
                    _row("conflict", direct_match=False, should_be="正确"),
                    _row("insufficient", direct_match=False, should_be="无法判断，需补充句子"),
                ],
            )
            true_output = directory / "true.blind.jsonl"
            false_output = directory / "false.blind.jsonl"
            audit_output = directory / "audit.jsonl"

            report = build_p0_direct_diagnosis_packets(
                input_path,
                verify_label=LABEL,
                teacher_definition="只有及物性实际约束答案时保留。",
                migration=_migration(),
                true_output_path=true_output,
                false_output_path=false_output,
                audit_output_path=audit_output,
                false_sample_size=3,
                false_boundary_question_ids=("false-fixed",),
                seed="p0-test-seed",
            )

            true_rows = [json.loads(line) for line in true_output.read_text(encoding="utf-8").splitlines()]
            false_rows = [json.loads(line) for line in false_output.read_text(encoding="utf-8").splitlines()]
            audit_rows = [json.loads(line) for line in audit_output.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(report["direct_true_records"], 2)
        self.assertEqual(report["legacy_taxonomy_label"], "知识点->语法词法->动词->实义动词->及物动词")
        self.assertEqual(report["active_taxonomy_label"], "知识点->词法->动词->实义动词->及物动词")
        self.assertEqual(report["taxonomy_migration_rule_id"], "legacy-grammar-wording-to-morphology")
        self.assertEqual(report["direct_false_records"], 6)
        self.assertEqual(report["contract_conflict_records"], 1)
        self.assertEqual(report["insufficient_records"], 1)
        self.assertEqual(report["selected_false_records"], 3)
        self.assertEqual(len(true_rows), 2)
        self.assertEqual(len(false_rows), 3)
        self.assertEqual(len(audit_rows), 5)
        self.assertEqual({row["question_id"] for row in true_rows}, {"true-a", "true-b"})
        self.assertNotIn("题型结构为：", true_rows[0]["question_context"])
        self.assertNotIn("llm_match", true_rows[0])
        self.assertNotIn("llm_should_be", false_rows[0])
        self.assertEqual(true_rows[0]["teacher_definition"], "只有及物性实际约束答案时保留。")
        self.assertEqual(
            true_rows[0]["active_taxonomy_label"],
            "知识点->词法->动词->实义动词->及物动词",
        )
        self.assertEqual(true_rows[0]["taxonomy_migration_rule_id"], "legacy-grammar-wording-to-morphology")
        self.assertEqual(
            {row["selection_stratum"] for row in audit_rows if row["review_set"] == "false"},
            {"false_route_suggestion", "known_false_boundary"},
        )
        boundary_row = next(row for row in audit_rows if row["question_id"] == "false-fixed")
        self.assertEqual(boundary_row["selection_stratum"], "known_false_boundary")
        self.assertEqual(
            {row["direct_match"] for row in audit_rows if row["review_set"] == "true"},
            {True},
        )
        self.assertTrue(
            all(";" not in family for family in report["selected_false_by_suggestion_family"])
        )

    def test_same_seed_selects_the_same_false_review_ids(self):
        self.assertTrue(callable(build_p0_direct_diagnosis_packets))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            input_path = _write_jsonl(
                directory / "verification.jsonl",
                [
                    _row(
                        f"false-{index}",
                        direct_match=False,
                        should_be="知识点@词汇@固定搭配/句型"
                        if index % 2
                        else "知识点@语法词法@动词时态@一般现在时@一般现在时的定义/判定",
                        name="完成句子" if index % 3 else "单词拼写",
                    )
                    for index in range(8)
                ],
            )
            selected_ids: list[list[str]] = []
            for run in ("one", "two"):
                true_output = directory / f"{run}.true.jsonl"
                false_output = directory / f"{run}.false.jsonl"
                audit_output = directory / f"{run}.audit.jsonl"
                build_p0_direct_diagnosis_packets(
                    input_path,
                    verify_label=LABEL,
                    teacher_definition="definition",
                    migration=_migration(),
                    true_output_path=true_output,
                    false_output_path=false_output,
                    audit_output_path=audit_output,
                    false_sample_size=4,
                    seed="fixed-seed",
                )
                selected_ids.append(
                    [json.loads(line)["review_id"] for line in false_output.read_text(encoding="utf-8").splitlines()]
                )

        self.assertEqual(selected_ids[0], selected_ids[1])


if __name__ == "__main__":
    unittest.main()
