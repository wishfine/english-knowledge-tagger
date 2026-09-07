import json
from pathlib import Path

from english_knowledge_tagger.cleanup_unprocessed_label_files import (
    apply_cleanup_plan,
    plan_cleanup,
)


def test_cleanup_deletes_routed_and_renames_remaining_by_label(tmp_path: Path) -> None:
    freeze = tmp_path / "freeze.json"
    freeze.write_text(
        json.dumps(
            {
                "schema_version": "label-pool-freeze-v1",
                "labels": [
                    {
                        "legacy_label": "知识点@词汇@已处理",
                        "target_basename": "次优-001-知识点@词汇@已处理",
                    },
                    {
                        "legacy_label": "知识点@词汇@有问题",
                        "target_basename": "次次优-002-知识点@词汇@有问题",
                    },
                    {
                        "legacy_label": "知识点@词汇@未处理",
                        "target_basename": "次次优-003-知识点@词汇@未处理",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    routing = tmp_path / "routing.json"
    routing.write_text(
        json.dumps(
            {
                "schema_version": "eligible-unprocessed-routing-v1",
                "processed_labels": ["知识点@词汇@已处理"],
                "issue_labels": ["知识点@词汇@有问题"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "未处理-099-知识点@词汇@已处理.jsonl").write_text("a\n", encoding="utf-8")
    (tmp_path / "旧前缀-007-知识点@词汇@有问题.jsonl").write_text("b\n", encoding="utf-8")
    (tmp_path / "知识点@词汇@未处理.jsonl").write_text("c\n", encoding="utf-8")
    (tmp_path / "unrecognized.jsonl").write_text("d\n", encoding="utf-8")

    plan = plan_cleanup(tmp_path, freeze, routing)

    assert plan["counts"] == {"delete": 2, "rename": 1, "unmatched": 1}
    apply_cleanup_plan(tmp_path, plan)

    assert not (tmp_path / "未处理-099-知识点@词汇@已处理.jsonl").exists()
    assert not (tmp_path / "旧前缀-007-知识点@词汇@有问题.jsonl").exists()
    assert (tmp_path / "次次优-003-知识点@词汇@未处理.jsonl").is_file()
    assert (tmp_path / "unrecognized.jsonl").is_file()


def test_cleanup_recognizes_canonical_rendered_filename_alias(tmp_path: Path) -> None:
    freeze = tmp_path / "freeze.json"
    freeze.write_text(
        json.dumps(
            {
                "schema_version": "label-pool-freeze-v1",
                "labels": [
                    {
                        "legacy_label": "知识点@语法词法@动词@情态动词@(don't/doesn't/didn't) have to",
                        "canonical_label": "知识点->词法->动词->情态动词->have to",
                        "target_basename": "次次优-001-知识点@语法词法@动词@情态动词@(don't／doesn't／didn't) have to",
                    },
                    {
                        "legacy_label": "知识点@词汇@dummy",
                        "target_basename": "次次优-002-知识点@词汇@dummy",
                    },
                    {
                        "legacy_label": "知识点@词汇@dummy-issue",
                        "target_basename": "次次优-003-知识点@词汇@dummy-issue",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    routing = tmp_path / "routing.json"
    routing.write_text(
        json.dumps(
            {
                "schema_version": "eligible-unprocessed-routing-v1",
                "processed_labels": ["知识点@词汇@dummy"],
                "issue_labels": ["知识点@词汇@dummy-issue"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "次次优-040-知识点@语法词法@动词@情态动词@have to.jsonl").write_text("x\n", encoding="utf-8")

    plan = plan_cleanup(tmp_path, freeze, routing)

    assert plan["counts"]["rename"] == 1
    assert plan["unmatched_files"] == []
    assert plan["actions"][0]["label"].endswith("(don't/doesn't/didn't) have to")
    assert plan["actions"][0]["target"].startswith("次次优-001-")
