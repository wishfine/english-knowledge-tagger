from english_knowledge_tagger.metrics import multilabel_metrics


def test_metrics_reports_exact_match_and_micro_f1():
    scores = multilabel_metrics(
        [["A"], ["B"]],
        [["A"], ["A", "B"]],
    )

    assert scores["example_exact_match"] == 0.5
    assert scores["micro_precision"] == 2 / 3
    assert scores["micro_recall"] == 1.0
    assert scores["micro_f1"] == 0.8


def test_metrics_calculates_macro_f1_across_observed_labels():
    scores = multilabel_metrics(
        [["A"], ["B"]],
        [["A"], ["A", "B"]],
    )

    assert scores["macro_f1"] == (2 / 3 + 1.0) / 2
    assert scores["support"] == 2
