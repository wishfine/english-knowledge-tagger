from pathlib import Path
import unittest

from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook
from english_knowledge_tagger.terminal_label_calibration_policy import (
    load_terminal_label_calibration_policy,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY = PROJECT_ROOT / "configs" / "terminal_label_calibration_policies" / "mentor-direct-v1-preliminary-20260827.json"
RULEBOOK = PROJECT_ROOT / "data" / "rulebooks" / "初中英语知识点题型方法释义.csv"
EXPECTED_RULES = (
    (
        "知识点->词汇->词汇辨析->名词（短语）辨析",
        {"retain": 12, "remove": 0, "uncertain": 0},
        {"retain": 1, "remove": 10, "uncertain": 1},
    ),
    (
        "知识点->词汇->词汇辨析->副词（短语）辨析",
        {"retain": 12, "remove": 0, "uncertain": 0},
        {"retain": 1, "remove": 10, "uncertain": 1},
    ),
    (
        "知识点->词汇->词汇辨析->动词（短语）辨析",
        {"retain": 12, "remove": 0, "uncertain": 0},
        {"retain": 1, "remove": 11, "uncertain": 0},
    ),
    (
        "知识点->词汇->词汇辨析->形容词（短语）辨析",
        {"retain": 12, "remove": 0, "uncertain": 0},
        {"retain": 3, "remove": 9, "uncertain": 0},
    ),
)


class TerminalLabelCalibrationPolicyConfigTests(unittest.TestCase):
    def test_preliminary_policy_releases_only_positive_lexical_pos_discrimination_evidence(self):
        policy = load_terminal_label_calibration_policy(POLICY, rulebook=load_knowledge_rulebook(RULEBOOK))
        for label, positive_audit, negative_audit in EXPECTED_RULES:
            with self.subTest(label=label):
                rule = policy.for_label(label)

                self.assertEqual(rule.prompt_version, "mentor-direct-v1")
                self.assertEqual(rule.positive_disposition, "silver_label_candidate")
                self.assertEqual(rule.negative_disposition, "hold")
                self.assertEqual(rule.calibration_stage, "screened_12")
                self.assertEqual(rule.positive_audit.retain, positive_audit["retain"])
                self.assertEqual(rule.positive_audit.remove, positive_audit["remove"])
                self.assertEqual(rule.positive_audit.uncertain, positive_audit["uncertain"])
                self.assertEqual(rule.negative_audit.retain, negative_audit["retain"])
                self.assertEqual(rule.negative_audit.remove, negative_audit["remove"])
                self.assertEqual(rule.negative_audit.uncertain, negative_audit["uncertain"])


if __name__ == "__main__":
    unittest.main()
