import json
from pathlib import Path
import tempfile
import unittest

try:
    from english_knowledge_tagger.mentor_tree_correction_tasks import (
        build_mentor_tree_correction_tasks,
    )
except ModuleNotFoundError:
    build_mentor_tree_correction_tasks = None


LABEL = "知识点@词汇@构词法@转化法"


def _row(
    question_id: str,
    *,
    llm_match: bool,
    llm_should_be: str,
    input_text: str | None = None,
) -> dict[str, object]:
    return {
        "verify_label": LABEL,
        "question_id": question_id,
        "parent_id": f"parent-{question_id}",
        "is_sub_question": True,
        "input": input_text
        or (
            "题型结构为：复合题\n"
            "题型名称为：翻译题\n"
            "当前小题题干：text 既可作名词也可作动词。\n"
            "当前小题解析：同一词形对应两种词性。\n"
            "当前小题答案：text"
        ),
        "output_all": f"{LABEL};题型@特殊题型@翻译@翻译（词汇短语）",
        "llm_match": llm_match,
        "llm_reason": "判别理由",
        "llm_should_be": llm_should_be,
    }


class MentorTreeCorrectionTaskTests(unittest.TestCase):
    def test_builder_partitions_consistent_rows_into_whole_tree_tasks_and_holds(self):
        self.assertTrue(callable(build_mentor_tree_correction_tasks))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            input_path = directory / "mentor.jsonl"
            rows = [
                _row("true", llm_match=True, llm_should_be="正确"),
                _row(
                    "false",
                    llm_match=False,
                    llm_should_be="知识点@词汇@构词法@派生法（词根词缀）",
                ),
                _row("conflict", llm_match=False, llm_should_be="正确"),
                _row(
                    "insufficient",
                    llm_match=False,
                    llm_should_be="根据现有信息无法确定具体标签，需补充题目内容。",
                ),
            ]
            input_path.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                encoding="utf-8",
            )
            tasks_path = directory / "tasks.jsonl"
            holds_path = directory / "holds.jsonl"

            report = build_mentor_tree_correction_tasks(
                input_path,
                verify_label=LABEL,
                output_path=tasks_path,
                hold_output_path=holds_path,
            )

            tasks = [json.loads(line) for line in tasks_path.read_text(encoding="utf-8").splitlines()]
            holds = [json.loads(line) for line in holds_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(report["input_records"], 4)
        self.assertEqual(report["tasks"], 2)
        self.assertEqual(report["holds"], 2)
        self.assertEqual(tasks[0]["trigger_kinds"], ["direct_match_recheck"])
        self.assertEqual(tasks[1]["trigger_kinds"], ["direct_mismatch"])
        self.assertEqual(tasks[0]["allowed_knowledge_prefixes"], ["知识点"])
        self.assertEqual(tasks[0]["knowledge_policy"], "optional")
        self.assertNotIn("题型结构为：", tasks[0]["question_context"])
        self.assertNotIn("题型名称为：", tasks[0]["question_context"])
        self.assertEqual(tasks[1]["triggers"][0]["direct_should_be"], "知识点@词汇@构词法@派生法（词根词缀）")
        self.assertEqual(
            [row["hold_reason"] for row in holds],
            ["direct_contract_conflict", "direct_insufficient"],
        )


if __name__ == "__main__":
    unittest.main()
