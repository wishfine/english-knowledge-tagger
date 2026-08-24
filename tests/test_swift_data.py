import json

from english_knowledge_tagger.data import QuestionRecord
from english_knowledge_tagger.swift_data import to_swift_sft_row


def test_swift_row_keeps_system_and_question_outside_the_completion():
    row = to_swift_sft_row(
        QuestionRecord(
            id="eng-1",
            question="She ___ to school yesterday.",
            options=("go", "went"),
            answer="went",
            analysis="yesterday 表示过去时间。",
            knowledge_points=("动词时态", "一般过去时"),
        )
    )

    assert set(row) == {"system", "query", "response"}
    assert "She ___ to school yesterday." in row["query"]
    assert json.loads(row["response"]) == {"knowledge_points": ["一般过去时", "动词时态"]}
    assert "knowledge_points" in row["system"]
