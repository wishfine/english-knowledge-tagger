import json
from pathlib import Path

from english_knowledge_tagger.rename_pool_label_files import (
    apply_rename_plan,
    plan_renames,
)


def test_plan_and_apply_renames_by_label_not_old_index(tmp_path: Path) -> None:
    manifest = tmp_path / "freeze.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "label-pool-freeze-v1",
                "labels": [
                    {
                        "legacy_label": "知识点@语法词法@动词时态@一般过去时@动词过去式变化规则",
                        "target_basename": "次优-044-知识点@语法词法@动词时态@一般过去时@动词过去式变化规则",
                    },
                    {
                        "legacy_label": "知识点@语法词法@形容词与副词@副词的用法@副词修饰副词",
                        "target_basename": "次次优-049-知识点@语法词法@形容词与副词@副词的用法@副词修饰副词",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "次优-003-知识点@语法词法@动词时态@一般过去时@动词过去式变化规则.jsonl").write_text("a\n")
    (tmp_path / "次次优-004-知识点@语法词法@形容词与副词@副词的用法@副词修饰副词.jsonl").write_text("b\n")

    plan = plan_renames(tmp_path, manifest)

    assert [item["source"] for item in plan] == [
        "次优-003-知识点@语法词法@动词时态@一般过去时@动词过去式变化规则.jsonl",
        "次次优-004-知识点@语法词法@形容词与副词@副词的用法@副词修饰副词.jsonl",
    ]
    assert plan[0]["target"] == "次优-044-知识点@语法词法@动词时态@一般过去时@动词过去式变化规则.jsonl"
    assert plan[1]["target"] == "次次优-049-知识点@语法词法@形容词与副词@副词的用法@副词修饰副词.jsonl"

    applied = apply_rename_plan(tmp_path, plan)

    assert applied == plan
    assert (tmp_path / plan[0]["target"]).is_file()
    assert (tmp_path / plan[1]["target"]).is_file()
    assert not (tmp_path / plan[0]["source"]).exists()
    assert not (tmp_path / plan[1]["source"]).exists()

