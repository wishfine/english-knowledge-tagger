import json
from pathlib import Path
import tempfile
import unittest

try:
    from english_knowledge_tagger.theme_tree_packet import build_theme_tree_packet
except ModuleNotFoundError:
    build_theme_tree_packet = None


LABEL = "知识点@语篇主题@人与社会@互联通讯"


def _source(question_id: str, *, structure: str, name: str) -> dict[str, object]:
    return {
        "verify_label": LABEL,
        "question_id": question_id,
        "parent_id": question_id,
        "is_sub_question": False,
        "input": f"题型结构为：{structure}\n题型名称为：{name}\n题目题干：完整材料{question_id}\n题目解析：解析。",
        "output_all": LABEL,
        "llm_match": False,
        "llm_reason": "x",
        "llm_should_be": "知识点@其他",
    }


def _evidence(question_id: str, decision: str) -> dict[str, object]:
    return {"question_id": question_id, "parent_id": question_id, "decision": decision}


class ThemeTreePacketTests(unittest.TestCase):
    def test_selects_exact_strata_without_emitting_web_decisions_to_tree_tasks(self):
        self.assertTrue(callable(build_theme_tree_packet))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = directory / "source.jsonl"
            evidence = directory / "evidence.jsonl"
            output = directory / "tasks.jsonl"
            audit = directory / "audit.jsonl"
            rows = (
                [_source(f"main-{i}", structure="复合题", name="阅读理解") for i in range(30)]
                + [_source(f"reading-{i}", structure="填空题", name="任务型阅读") for i in range(10)]
                + [_source(f"other-{i}", structure="单选题", name="选择题") for i in range(10)]
                + [_source(f"keep-{i}", structure="复合题", name="阅读理解") for i in range(10)]
            )
            source.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
            evidence_rows = [_evidence(row["question_id"], "keep" if str(row["question_id"]).startswith("keep-") else "remove") for row in rows]
            evidence.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in evidence_rows) + "\n", encoding="utf-8")

            report = build_theme_tree_packet(source, evidence_path=evidence, output_path=output, audit_index_path=audit, seed="theme")
            tasks = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            audit_rows = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(report["selected_records"], 60)
        self.assertEqual(report["selected_by_stratum"], {"keep_control": 10, "main_reading_remove": 30, "other_reading_remove": 10, "other_remove": 10})
        self.assertEqual(len({row["task_id"] for row in tasks}), 60)
        self.assertTrue(all("web_gpt_decision" not in row for row in tasks))
        self.assertEqual({row["web_gpt_decision"] for row in audit_rows}, {"keep", "remove"})


if __name__ == "__main__":
    unittest.main()
