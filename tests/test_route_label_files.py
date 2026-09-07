import json
from pathlib import Path

from english_knowledge_tagger.route_label_files import apply_route_plan, plan_routes
from english_knowledge_tagger.route_label_files import _routing_labels


def test_route_plan_moves_processed_and_issue_labels_by_embedded_label(tmp_path: Path) -> None:
    source = tmp_path / "source"
    processed = tmp_path / "processed"
    issue = tmp_path / "issue"
    source.mkdir()
    processed.mkdir()
    issue.mkdir()
    manifest = tmp_path / "freeze.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "label-pool-freeze-v1",
                "labels": [
                    {
                        "legacy_label": "知识点@词汇@A",
                        "target_basename": "优质-001-知识点@词汇@A",
                    },
                    {
                        "legacy_label": "知识点@词汇@B",
                        "target_basename": "次优-002-知识点@词汇@B",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (source / "次优-099-知识点@词汇@A.jsonl").write_text("a\n", encoding="utf-8")
    (source / "次次优-004-知识点@词汇@B.jsonl").write_text("b\n", encoding="utf-8")

    plan = plan_routes(
        source_dir=source,
        processed_dir=processed,
        issue_dir=issue,
        manifest_path=manifest,
        processed_labels=["知识点@词汇@A"],
        issue_labels=["知识点@词汇@B"],
    )

    assert [item["label"] for item in plan] == ["知识点@词汇@A", "知识点@词汇@B"]
    assert plan[0]["target"] == str(processed / "优质-001-知识点@词汇@A.jsonl")
    assert plan[1]["target"] == str(issue / "次优-002-知识点@词汇@B.jsonl")

    apply_route_plan(plan)

    assert (processed / "优质-001-知识点@词汇@A.jsonl").is_file()
    assert (issue / "次优-002-知识点@词汇@B.jsonl").is_file()
    assert not list(source.glob("*.jsonl"))


def test_routing_manifest_accepts_eligible_unprocessed_schema(tmp_path: Path) -> None:
    routing = tmp_path / "routing.json"
    routing.write_text(
        json.dumps(
            {
                "schema_version": "eligible-unprocessed-routing-v1",
                "processed_labels": ["知识点@词汇@A"],
                "issue_labels": ["知识点@词汇@B"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    processed, issue = _routing_labels(routing)

    assert processed == ["知识点@词汇@A"]
    assert issue == ["知识点@词汇@B"]
