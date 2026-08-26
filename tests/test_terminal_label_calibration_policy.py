import csv
import json
from pathlib import Path
import tempfile
import unittest

try:
    from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook
    from english_knowledge_tagger.terminal_label_calibration_policy import (
        load_terminal_label_calibration_policy,
    )
except ModuleNotFoundError:
    load_knowledge_rulebook = None
    load_terminal_label_calibration_policy = None


HEADERS = (
    "末级知识点",
    "打标解读（标绿的标签，新题不再打）",
    "大模型压缩+人工微调的释义",
)
LABEL_A = "知识点->词法->冠词->a/an的区别"
LABEL_B = "知识点->词法->冠词->the的用法"


def write_rulebook(path: Path) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(
            [
                {
                    "末级知识点": LABEL_A,
                    "打标解读（标绿的标签，新题不再打）": "a/an",
                    "大模型压缩+人工微调的释义": "a/an",
                },
                {
                    "末级知识点": LABEL_B,
                    "打标解读（标绿的标签，新题不再打）": "the",
                    "大模型压缩+人工微调的释义": "the",
                },
            ]
        )
    return path


def write_policy(path: Path, labels: list[dict[str, object]]) -> Path:
    path.write_text(
        json.dumps(
            {"schema_version": "terminal-label-calibration-policy-v1", "labels": labels},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


class TerminalLabelCalibrationPolicyTests(unittest.TestCase):
    def test_sparse_policy_releases_only_explicitly_reviewed_positive_labels(self):
        self.assertTrue(callable(load_terminal_label_calibration_policy))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            policy = load_terminal_label_calibration_policy(
                write_policy(
                    directory / "policy.json",
                    [
                        {
                            "canonical_label": LABEL_A,
                            "positive_disposition": "silver_label_candidate",
                            "negative_disposition": "hold",
                            "calibration_stage": "screened_12",
                            "audit": {
                                "positive": {"retain": 12, "remove": 0, "uncertain": 0},
                                "negative": {"retain": 2, "remove": 8, "uncertain": 2},
                            },
                        }
                    ],
                ),
                rulebook=load_knowledge_rulebook(write_rulebook(directory / "rulebook.csv")),
            )

        self.assertEqual(policy.for_label(LABEL_A).positive_disposition, "silver_label_candidate")
        self.assertEqual(policy.for_label(LABEL_A).negative_disposition, "hold")
        self.assertEqual(policy.for_label(LABEL_B).positive_disposition, "hold")
        self.assertEqual(policy.for_label(LABEL_B).calibration_stage, "unreviewed")

    def test_policy_rejects_positive_silver_release_with_a_reviewed_false_positive(self):
        self.assertTrue(callable(load_terminal_label_calibration_policy))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            with self.assertRaisesRegex(ValueError, "positive.*remove"):
                load_terminal_label_calibration_policy(
                    write_policy(
                        directory / "policy.json",
                        [
                            {
                                "canonical_label": LABEL_A,
                                "positive_disposition": "silver_label_candidate",
                                "negative_disposition": "hold",
                                "calibration_stage": "screened_12",
                                "audit": {
                                    "positive": {"retain": 11, "remove": 1, "uncertain": 0},
                                    "negative": {"retain": 0, "remove": 0, "uncertain": 0},
                                },
                            }
                        ],
                    ),
                    rulebook=load_knowledge_rulebook(write_rulebook(directory / "rulebook.csv")),
                )


if __name__ == "__main__":
    unittest.main()
