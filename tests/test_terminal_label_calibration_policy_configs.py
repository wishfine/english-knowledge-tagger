from pathlib import Path
import unittest

from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook
from english_knowledge_tagger.terminal_label_calibration_policy import (
    load_terminal_label_calibration_policy,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY = PROJECT_ROOT / "configs" / "terminal_label_calibration_policies" / "mentor-direct-v1-preliminary-20260827.json"
RULEBOOK = PROJECT_ROOT / "data" / "rulebooks" / "初中英语知识点题型方法释义.csv"
LABEL = "知识点->词汇->词汇辨析->名词（短语）辨析"


class TerminalLabelCalibrationPolicyConfigTests(unittest.TestCase):
    def test_first_preliminary_policy_releases_only_positive_noun_discrimination_evidence(self):
        policy = load_terminal_label_calibration_policy(POLICY, rulebook=load_knowledge_rulebook(RULEBOOK))
        rule = policy.for_label(LABEL)

        self.assertEqual(rule.positive_disposition, "silver_label_candidate")
        self.assertEqual(rule.negative_disposition, "hold")
        self.assertEqual(rule.calibration_stage, "screened_12")
        self.assertEqual(rule.positive_audit.retain, 12)
        self.assertEqual(rule.positive_audit.remove, 0)
        self.assertEqual(rule.negative_audit.uncertain, 1)


if __name__ == "__main__":
    unittest.main()
