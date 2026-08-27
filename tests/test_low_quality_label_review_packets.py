import json
from pathlib import Path
import tempfile
import unittest

try:
    from english_knowledge_tagger.low_quality_label_review_packets import (
        ConversionTreeT1Quotas,
        build_conversion_tree_t1_packet,
        build_mixed_pos_m1_review_packet,
    )
except ModuleNotFoundError:
    ConversionTreeT1Quotas = None
    build_conversion_tree_t1_packet = None
    build_mixed_pos_m1_review_packet = None


CONVERSION_LABEL = "知识点@词汇@构词法@转化法"
MIXED_POS_LABEL = "知识点@词汇@词汇辨析@词汇辨析（混合词性）"
LEGAL_ROUTE = {
    "scope": "parent",
    "declared_type_structure": "单选题",
    "declared_type_name": "选择题",
}


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def _tree_task(
    task_id: str,
    *,
    trigger: str,
    should_be: str = "正确",
    route: dict[str, str] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "knowledge-tree-task-v1",
        "task_id": task_id,
        "question_id": task_id,
        "parent_id": f"parent-{task_id}",
        "question_context": f"题干：{task_id}",
        "route_key": route or LEGAL_ROUTE,
        "trigger_kinds": [trigger],
        "direct_should_be": should_be,
    }


def _mentor_row(
    question_id: str,
    *,
    llm_match: bool,
    should_be: str,
    route: tuple[str, str, str] = ("parent", "单选题", "选择题"),
) -> dict[str, object]:
    scope, structure, name = route
    return {
        "verify_label": MIXED_POS_LABEL,
        "question_id": question_id,
        "parent_id": f"parent-{question_id}",
        "is_sub_question": scope == "child",
        "input": (
            f"题型结构为：{structure}\n"
            f"题型名称为：{name}\n"
            "题目题干：Example question.\n"
            "题目选项：\nA. another\nB. more\nC. other\nD. others\n"
            "题目解析：Example analysis.\n"
            "题目答案：A"
        ),
        "output_all": f"{MIXED_POS_LABEL};知识点@语法词法@词性辨析",
        "llm_match": llm_match,
        "llm_should_be": should_be,
        "llm_reason": f"reason-{question_id}",
    }


class LowQualityLabelReviewPacketTests(unittest.TestCase):
    def test_conversion_t1_packet_is_stratified_stable_and_tree_routable(self):
        self.assertTrue(callable(build_conversion_tree_t1_packet))
        self.assertIsNotNone(ConversionTreeT1Quotas)
        quotas = ConversionTreeT1Quotas(
            direct_match=3,
            derived=1,
            word_form=1,
            vocabulary=1,
            fixed_phrase=1,
            grammar=1,
            translation=1,
            spelling=1,
            parent_fill=1,
        )
        child_translation = {
            "scope": "child",
            "declared_type_structure": "复合题",
            "declared_type_name": "翻译题",
        }
        child_spelling = {
            "scope": "child",
            "declared_type_structure": "复合题",
            "declared_type_name": "单词拼写",
        }
        parent_fill = {
            "scope": "parent",
            "declared_type_structure": "填空题",
            "declared_type_name": "语法填空",
        }
        rows = [
            _tree_task("same-form", trigger="direct_match_recheck"),
            _tree_task("derived-form", trigger="direct_match_recheck"),
            _tree_task("true-fallback", trigger="direct_match_recheck"),
            _tree_task(
                "derived", trigger="direct_mismatch", should_be="知识点@词汇@构词法@派生法（词根词缀）"
            ),
            _tree_task(
                "word-form", trigger="direct_mismatch", should_be="知识点@词汇@词汇（音/形/义）@名词（短语）的音/形/义"
            ),
            _tree_task(
                "vocabulary", trigger="direct_mismatch", should_be="知识点@词汇@词汇辨析@名词（短语）辨析"
            ),
            _tree_task(
                "fixed", trigger="direct_mismatch", should_be="知识点@词汇@固定搭配/句型"
            ),
            _tree_task(
                "grammar", trigger="direct_mismatch", should_be="知识点@语法词法@主谓一致@语法一致"
            ),
            _tree_task("translation", trigger="direct_mismatch", route=child_translation),
            _tree_task("spelling", trigger="direct_mismatch", route=child_spelling),
            _tree_task("fill", trigger="direct_mismatch", route=parent_fill),
        ]
        boundaries = {
            "known_same_form": ("same-form",),
            "known_derived_or_spelling": ("derived-form",),
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            tasks = _write_jsonl(directory / "tasks.jsonl", rows)
            output_a = directory / "sample-a.jsonl"
            index_a = directory / "index-a.jsonl"
            report = build_conversion_tree_t1_packet(
                tasks,
                output_path=output_a,
                audit_index_path=index_a,
                seed="conversion-t1",
                quotas=quotas,
                boundary_question_ids=boundaries,
            )
            output_b = directory / "sample-b.jsonl"
            index_b = directory / "index-b.jsonl"
            build_conversion_tree_t1_packet(
                tasks,
                output_path=output_b,
                audit_index_path=index_b,
                seed="conversion-t1",
                quotas=quotas,
                boundary_question_ids=boundaries,
            )
            sample_a = [json.loads(line) for line in output_a.read_text(encoding="utf-8").splitlines()]
            sample_b = [json.loads(line) for line in output_b.read_text(encoding="utf-8").splitlines()]
            index = [json.loads(line) for line in index_a.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(report["selected_records"], 11)
        self.assertEqual(len({row["task_id"] for row in sample_a}), 11)
        self.assertEqual([row["task_id"] for row in sample_a], [row["task_id"] for row in sample_b])
        self.assertTrue({"same-form", "derived-form"}.issubset({row["task_id"] for row in sample_a}))
        self.assertNotIn("selection_stratum", sample_a[0])
        self.assertEqual({row["selection_stratum"] for row in index}, {
            "known_same_form",
            "known_derived_or_spelling",
            "direct_match_fallback",
            "derived",
            "word_form",
            "vocabulary",
            "fixed_phrase",
            "grammar",
            "route_translation",
            "route_spelling",
            "route_parent_fill",
        })

    def test_mixed_pos_m1_packet_is_blind_and_stratifies_legal_route_false_rows(self):
        self.assertTrue(callable(build_mixed_pos_m1_review_packet))
        strata = {
            "how": "知识点@语法句法@句子种类@疑问句@特殊疑问句@how类特殊疑问句",
            "fixed": "知识点@词汇@固定搭配/句型",
            "same_pos": "知识点@词汇@词汇辨析@词汇辨析（同词性）",
            "connector": "知识点@词汇@词汇辨析@词汇辨析（连词）",
        }
        rows = [
            _mentor_row("true-1", llm_match=True, should_be="正确"),
            _mentor_row("true-2", llm_match=True, should_be="正确"),
            _mentor_row(
                "illegal-true",
                llm_match=True,
                should_be="正确",
                route=("child", "复合题", "语法选择"),
            ),
        ]
        for stratum, should_be in strata.items():
            rows.extend(
                _mentor_row(f"{stratum}-{index}", llm_match=False, should_be=should_be)
                for index in range(12)
            )
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            input_path = _write_jsonl(directory / "mentor.jsonl", rows)
            blind = directory / "blind.jsonl"
            index = directory / "index.jsonl"
            report = build_mixed_pos_m1_review_packet(
                input_path,
                verify_label=MIXED_POS_LABEL,
                teacher_definition="只标非复合单选。",
                blind_output_path=blind,
                audit_index_path=index,
                seed="mixed-pos-m1",
            )
            review_rows = [json.loads(line) for line in blind.read_text(encoding="utf-8").splitlines()]
            audit_rows = [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(report["legal_true_records"], 2)
        self.assertEqual(report["selected_false_records"], 48)
        self.assertEqual(report["selected_records"], 50)
        self.assertNotIn("illegal-true", {row["question_id"] for row in review_rows})
        self.assertTrue(all("llm_match" not in row and "output_all" not in row for row in review_rows))
        self.assertTrue(all(row["teacher_definition"] == "只标非复合单选。" for row in review_rows))
        self.assertTrue(any(row["direct_match"] is False for row in audit_rows))
        self.assertEqual(
            {row["selection_stratum"] for row in audit_rows},
            {"legal_true", "false_how", "false_fixed_phrase", "false_same_pos", "false_connector"},
        )


if __name__ == "__main__":
    unittest.main()
