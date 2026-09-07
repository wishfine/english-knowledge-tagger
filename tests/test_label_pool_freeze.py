from pathlib import Path

from english_knowledge_tagger.label_pool_freeze import build_label_pool_freeze


def _write_fixture(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "# status",
                "| # | 历史标签 | canonical | DS | Wilson | True | False | 当前状态 | 来源 | 下一步 |",
                "|---:|---|---|---:|---:|---|---|---|---|---|",
                "| 1 | 知识点@词汇@高 | 知识点->词汇->高 | 80/100 = 80.0% | 70.00% | 12/12 = 100.0% | 0/1 | 终判完成，训练候选（未发布） | x | y |",
                "| 2 | 知识点@词汇@B | 知识点->词汇->B | 60/100 = 60.0% | 55.00% | 12/12 = 100.0% | 0/1 | 待处理：未通过快速池门禁 | x | y |",
                "| 3 | 知识点@词汇@H | 知识点->词汇->H | 80/100 = 80.0% | 70.00% | 11/12 = 91.7% | 0/1 | 待处理：未通过快速池门禁 | x | y |",
                "| 4 | 知识点@词汇@排除 | 知识点->词汇->排除 | 80/100 = 80.0% | 75.00% | 12/12 = 100.0% | 0/1 | 已完成终判，但排除出优质池 | x | y |",
                "| 5 | 知识点@词汇@剩余 | 知识点->词汇->剩余 | 40/100 = 40.0% | 35.00% | 10/12 = 83.3% | 0/1 | 待处理：未通过快速池门禁 | x | y |",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_freeze_assigns_pools_and_stable_pool_local_names(tmp_path: Path) -> None:
    status = tmp_path / "status.md"
    low = tmp_path / "low.md"
    output = tmp_path / "freeze.json"
    _write_fixture(status)
    low.write_text(
        "| # | 标签 | DS | 状态 | 根因 | 实验 | 门禁 |\n"
        "|---:|---|---:|---|---|---|---|\n"
        "| 1 | `知识点@词汇@低` | 1/1 | hold | x | y | z |\n",
        encoding="utf-8",
    )

    payload = build_label_pool_freeze(
        status_ledger=status,
        low_quality_ledger=low,
        output_json=output,
        output_markdown=None,
        expected_label_count=6,
    )

    assert payload["pool_counts"] == {"优质": 2, "次优": 2, "劣质": 1, "次次优": 1}
    records = {row["legacy_label"]: row for row in payload["labels"]}
    assert records["知识点@词汇@高"]["pool"] == "优质"
    assert records["知识点@词汇@B"]["pool"] == "次优"
    assert records["知识点@词汇@H"]["pool"] == "次优"
    assert records["知识点@词汇@排除"]["pool"] == "优质"
    assert records["知识点@词汇@低"]["pool"] == "劣质"
    assert records["知识点@词汇@剩余"]["pool"] == "次次优"

    assert records["知识点@词汇@B"]["pool_index"] == 1
    assert records["知识点@词汇@H"]["pool_index"] == 2
    assert records["知识点@词汇@B"]["target_filename"].startswith("次优-001-")
    assert output.exists()
