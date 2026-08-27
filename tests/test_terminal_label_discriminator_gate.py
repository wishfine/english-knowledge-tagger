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
    from english_knowledge_tagger.terminal_label_discriminator_gate import (
        gate_terminal_label_discriminator,
    )
except ModuleNotFoundError:
    load_knowledge_rulebook = None
    load_terminal_label_calibration_policy = None
    gate_terminal_label_discriminator = None


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
        for label in (LABEL_A, LABEL_B):
            writer.writerow(
                {
                    "末级知识点": label,
                    "打标解读（标绿的标签，新题不再打）": label,
                    "大模型压缩+人工微调的释义": label,
                }
            )
    return path


def write_policy(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "terminal-label-calibration-policy-v1",
                "labels": [
                    {
                        "canonical_label": LABEL_A,
                        "prompt_version": "direct-label-v1",
                        "positive_disposition": "silver_label_candidate",
                        "negative_disposition": "hold",
                        "calibration_stage": "screened_12",
                        "audit": {
                            "positive": {"retain": 12, "remove": 0, "uncertain": 0},
                            "negative": {"retain": 0, "remove": 12, "uncertain": 0},
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def evidence(
    *,
    review_id: str,
    question_id: str,
    canonical_label: str,
    llm_match: bool,
    is_sub_question: bool = True,
    status: str = "candidate",
) -> dict[str, object]:
    return {
        "schema_version": "terminal-label-discriminator-evidence-v1",
        "review_id": review_id,
        "question_id": question_id,
        "parent_id": "100",
        "source_line": int(question_id),
        "is_sub_question": is_sub_question,
        "legacy_label": canonical_label,
        "canonical_label": canonical_label,
        "llm_match": llm_match,
        "status": status,
        "model": "ds-v4-flash",
        "prompt_version": "direct-label-v1",
        "route_key": {
            "declared_type_structure": "复合题",
            "declared_type_name": "语法选择",
        },
    }


class TerminalLabelDiscriminatorGateTests(unittest.TestCase):
    def _policy_and_rulebook(self, directory: Path):
        rulebook = load_knowledge_rulebook(write_rulebook(directory / "rulebook.csv"))
        policy = load_terminal_label_calibration_policy(
            write_policy(directory / "policy.json"), rulebook=rulebook
        )
        return policy, rulebook

    def test_releases_only_explicitly_calibrated_positive_evidence(self):
        self.assertTrue(callable(gate_terminal_label_discriminator))
        with tempfile.TemporaryDirectory() as temp_dir:
            policy, rulebook = self._policy_and_rulebook(Path(temp_dir))
            result = gate_terminal_label_discriminator(
                [
                    evidence(
                        review_id="a-true", question_id="101", canonical_label=LABEL_A, llm_match=True
                    ),
                    evidence(
                        review_id="a-false", question_id="102", canonical_label=LABEL_A, llm_match=False
                    ),
                    evidence(
                        review_id="b-true", question_id="103", canonical_label=LABEL_B, llm_match=True
                    ),
                ],
                policy=policy,
                rulebook=rulebook,
            )

        self.assertEqual([row["review_id"] for row in result.silver], ["a-true"])
        self.assertEqual(result.silver[0]["disposition"], "silver_label_candidate")
        self.assertEqual(result.hold[0]["disposition_reason"], "policy_negative_hold")
        self.assertEqual(result.hold[1]["disposition_reason"], "policy_positive_hold")
        self.assertEqual(result.report["counts"], {
            "silver_label_candidate": 1,
            "relabel_candidate": 0,
            "hold": 2,
        })
        self.assertEqual(result.silver[0]["scope"], "child")

    def test_releases_negative_only_when_the_explicit_policy_allows_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            rulebook = load_knowledge_rulebook(write_rulebook(directory / "rulebook.csv"))
            policy_path = write_policy(directory / "policy.json")
            payload = json.loads(policy_path.read_text(encoding="utf-8"))
            payload["labels"][0]["negative_disposition"] = "relabel_candidate"
            payload["labels"][0]["audit"]["negative"] = {
                "retain": 0,
                "remove": 12,
                "uncertain": 0,
            }
            policy_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            policy = load_terminal_label_calibration_policy(policy_path, rulebook=rulebook)
            result = gate_terminal_label_discriminator(
                [
                    evidence(
                        review_id="a-false", question_id="102", canonical_label=LABEL_A, llm_match=False
                    )
                ],
                policy=policy,
                rulebook=rulebook,
            )

        self.assertEqual([row["review_id"] for row in result.relabel], ["a-false"])
        self.assertEqual(result.relabel[0]["disposition"], "relabel_candidate")

    def test_rejects_conflicting_duplicate_question_label_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            policy, rulebook = self._policy_and_rulebook(Path(temp_dir))
            with self.assertRaisesRegex(ValueError, "conflicting duplicate"):
                gate_terminal_label_discriminator(
                    [
                        evidence(
                            review_id="first", question_id="101", canonical_label=LABEL_A, llm_match=True
                        ),
                        evidence(
                            review_id="second", question_id="101", canonical_label=LABEL_A, llm_match=False
                        ),
                    ],
                    policy=policy,
                    rulebook=rulebook,
                )

    def test_holds_error_evidence_without_requiring_a_boolean_match(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            policy, rulebook = self._policy_and_rulebook(Path(temp_dir))
            error_row = evidence(
                review_id="service-error", question_id="101", canonical_label=LABEL_A, llm_match=True
            )
            error_row["status"] = "error"
            error_row["llm_match"] = None
            result = gate_terminal_label_discriminator([error_row], policy=policy, rulebook=rulebook)

        self.assertEqual(result.silver, ())
        self.assertEqual(result.relabel, ())
        self.assertEqual(result.hold[0]["disposition_reason"], "discriminator_status_error")

    def test_holds_positive_evidence_when_the_prompt_version_was_not_calibrated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            policy, rulebook = self._policy_and_rulebook(Path(temp_dir))
            final_prompt_evidence = evidence(
                review_id="different-prompt", question_id="101", canonical_label=LABEL_A, llm_match=True
            )
            final_prompt_evidence["prompt_version"] = "final-label-discriminator-v1"
            result = gate_terminal_label_discriminator(
                [final_prompt_evidence], policy=policy, rulebook=rulebook
            )

        self.assertEqual(result.silver, ())
        self.assertEqual(result.hold[0]["disposition_reason"], "calibration_prompt_version_mismatch")


if __name__ == "__main__":
    unittest.main()
