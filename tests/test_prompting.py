import json

import pytest

from english_knowledge_tagger.data import QuestionRecord
from english_knowledge_tagger.parsing import ResponseParseError, parse_response
from english_knowledge_tagger.prompting import build_messages, canonical_response


def sample_record():
    return QuestionRecord(
        id="eng-1",
        question="She ___ to school yesterday.",
        options=("go", "goes", "went"),
        answer="went",
        analysis="yesterday 表示过去时间。",
        knowledge_points=("一般过去时", "动词时态"),
    )


def test_build_messages_includes_all_model_visible_question_fields():
    messages = build_messages(sample_record())

    assert [message["role"] for message in messages] == ["system", "user"]
    assert "She ___ to school yesterday." in messages[1]["content"]
    assert "goes" in messages[1]["content"]
    assert "went" in messages[1]["content"]
    assert "yesterday 表示过去时间。" in messages[1]["content"]


def test_canonical_response_sorts_and_deduplicates_labels():
    payload = json.loads(canonical_response(["动词时态", "一般过去时", "动词时态"]))

    assert payload == {"knowledge_points": ["一般过去时", "动词时态"]}


def test_parse_response_filters_unknown_labels_and_sorts_known_labels():
    result = parse_response(
        '模型回答：{"knowledge_points":["未知", "动词时态", "动词时态"]}',
        {"动词时态"},
    )

    assert result == ["动词时态"]


def test_parse_response_rejects_a_non_json_or_wrong_shape_response():
    with pytest.raises(ResponseParseError, match="knowledge_points"):
        parse_response('{"labels":["动词时态"]}', {"动词时态"})
