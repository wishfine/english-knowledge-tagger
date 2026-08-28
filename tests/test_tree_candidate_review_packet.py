import csv
import json
from pathlib import Path
import tempfile
import unittest

try:
    from english_knowledge_tagger.tree_candidate_review_packet import build_tree_candidate_review_packet
except ModuleNotFoundError:
    build_tree_candidate_review_packet = None


LABEL = "知识点->词汇->构词法->转化法"


def _task(task_id: str) -> dict[str, object]:
    return {
        "task_id": task_id,
        "question_id": f"question-{task_id}",
        "parent_id": f"parent-{task_id}",
        "route_key": {"scope": "parent", "declared_type_structure": "单选题", "declared_type_name": "选择题"},
        "historical_label": LABEL,
        "question_context": "题干：text 既可作名词也可作动词。答案：text。",
    }


class TreeCandidateReviewPacketTests(unittest.TestCase):
    def test_joins_task_result_and_rulebook_without_ds_trace(self):
        self.assertTrue(callable(build_tree_candidate_review_packet))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            tasks = directory / "tasks.jsonl"
            audit = directory / "audit.jsonl"
            results = directory / "results.jsonl"
            teacher = directory / "teacher.csv"
            output = directory / "review.jsonl"
            tasks.write_text("\n".join(json.dumps(_task(value), ensure_ascii=False) for value in ("a", "b")) + "\n", encoding="utf-8")
            audit.write_text("\n".join(json.dumps({"task_id": value, "selection_stratum": "control"}) for value in ("a", "b")) + "\n", encoding="utf-8")
            results.write_text(
                "\n".join(
                    json.dumps(row, ensure_ascii=False)
                    for row in (
                        {"task_id": "a", "status": "tree_candidate", "candidate_label": LABEL, "trace": [{"raw_response": "hidden"}]},
                        {"task_id": "b", "status": "budget_exhausted", "candidate_label": None, "trace": [{"raw_response": "hidden"}]},
                    )
                ) + "\n",
                encoding="utf-8",
            )
            with teacher.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=("末级知识点", "打标解读（标绿的标签，新题不再打）", "大模型压缩+人工微调的释义"))
                writer.writeheader()
                writer.writerow({"末级知识点": LABEL, "打标解读（标绿的标签，新题不再打）": "同形转词性。", "大模型压缩+人工微调的释义": "同形转词性。"})

            report = build_tree_candidate_review_packet(tasks, audit_index_path=audit, results_path=results, teacher_csv_path=teacher, output_path=output)
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(report["review_records"], 2)
        self.assertEqual(rows[0]["tree_candidate_definition"], "同形转词性。")
        self.assertEqual(rows[1]["tree_status"], "budget_exhausted")
        self.assertNotIn("trace", rows[0])
        self.assertNotIn("raw_response", json.dumps(rows[0], ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
