import json

from english_knowledge_tagger.data import load_inference_records


def test_load_inference_records_accepts_question_without_labels(tmp_path):
    path = tmp_path / "incoming.jsonl"
    path.write_text(
        json.dumps({"id": "eng-new-1", "question": "Tom usually ___ breakfast.", "options": ["have", "has"]}) + "\n",
        encoding="utf-8",
    )

    record = load_inference_records(path)[0]

    assert record.id == "eng-new-1"
    assert record.options == ("have", "has")
    assert record.knowledge_points == ()
