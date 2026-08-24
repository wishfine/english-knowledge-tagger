import json

import pytest

from english_knowledge_tagger.data import (
    DataContractError,
    content_hash,
    load_records,
    load_taxonomy,
    split_records,
)


def write_jsonl(tmp_path, records):
    path = tmp_path / "records.jsonl"
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )
    return path


def test_load_taxonomy_requires_unique_nonempty_labels(tmp_path):
    taxonomy_path = tmp_path / "taxonomy.json"
    taxonomy_path.write_text('{"knowledge_points": ["时态", "语态"]}', encoding="utf-8")

    assert load_taxonomy(taxonomy_path) == frozenset({"时态", "语态"})


def test_load_records_rejects_labels_outside_taxonomy(tmp_path):
    path = write_jsonl(
        tmp_path,
        [{"id": "eng-1", "question": "She went home.", "knowledge_points": ["未知"]}],
    )

    with pytest.raises(DataContractError, match="not in taxonomy"):
        load_records(path, {"一般过去时"})


def test_content_hash_normalizes_equivalent_question_text(tmp_path):
    records = load_records(
        write_jsonl(
            tmp_path,
            [
                {
                    "id": "eng-1",
                    "question": "She\u3000went  home.",
                    "knowledge_points": ["一般过去时"],
                },
                {
                    "id": "eng-2",
                    "question": "She went home.",
                    "knowledge_points": ["一般过去时"],
                },
            ],
        ),
        {"一般过去时"},
    )

    assert content_hash(records[0]) == content_hash(records[1])


def test_split_keeps_duplicate_question_content_in_one_partition(tmp_path):
    taxonomy = {"一般过去时", "动词时态"}
    records = load_records(
        write_jsonl(
            tmp_path,
            [
                {"id": "a", "question": "She went home.", "knowledge_points": ["一般过去时"]},
                {"id": "b", "question": "She went home.", "knowledge_points": ["动词时态"]},
                {"id": "c", "question": "He is home.", "knowledge_points": ["动词时态"]},
                {"id": "d", "question": "They are home.", "knowledge_points": ["动词时态"]},
            ],
        ),
        taxonomy,
    )

    train, validation = split_records(records, validation_ratio=0.5, seed=42)
    train_ids = {record.id for record in train}
    validation_ids = {record.id for record in validation}

    assert {"a", "b"} <= train_ids or {"a", "b"} <= validation_ids
    assert not (train_ids & validation_ids)
    assert train_ids | validation_ids == {"a", "b", "c", "d"}
