from english_knowledge_tagger.training_data import tokenize_completion


class FakeTokenizer:
    eos_token = "<eos>"

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        assert messages == [{"role": "user", "content": "Q"}]
        assert tokenize is True
        assert add_generation_prompt is True
        return [11, 12, 13, 14]

    def __call__(self, text, *, add_special_tokens):
        assert text == '{"knowledge_points":["A"]}<eos>'
        assert add_special_tokens is False
        return {"input_ids": [21, 22]}


def test_completion_labels_mask_every_prompt_token():
    item = tokenize_completion(
        FakeTokenizer(),
        [{"role": "user", "content": "Q"}],
        '{"knowledge_points":["A"]}',
    )

    assert item["input_ids"] == [11, 12, 13, 14, 21, 22]
    assert item["attention_mask"] == [1, 1, 1, 1, 1, 1]
    assert item["labels"] == [-100, -100, -100, -100, 21, 22]


def test_completion_truncation_preserves_the_whole_target():
    item = tokenize_completion(
        FakeTokenizer(),
        [{"role": "user", "content": "Q"}],
        '{"knowledge_points":["A"]}',
        max_length=4,
    )

    assert item["input_ids"] == [13, 14, 21, 22]
    assert item["labels"] == [-100, -100, 21, 22]
