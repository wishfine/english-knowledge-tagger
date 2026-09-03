import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


LABEL = "知识点@词汇@词汇辨析@名词（短语）辨析"
CANONICAL = "知识点->词汇->词汇辨析->名词（短语）辨析"


def write_rulebook(path: Path) -> Path:
    path.write_text(
        "末级知识点,打标解读（标绿的标签，新题不再打）,大模型压缩+人工微调的释义\n"
        f"{CANONICAL},名词辨析,名词辨析\n",
        encoding="utf-8",
    )
    return path


def write_migration(path: Path) -> Path:
    path.write_text(
        json.dumps({"schema_version": "knowledge-taxonomy-migration-v1", "rules": []}),
        encoding="utf-8",
    )
    return path


def source_row(question_id: str = "q1", output: str | None = None) -> dict[str, object]:
    return {
        "question_id": question_id,
        "parent_id": question_id,
        "is_sub_question": False,
        "input": "题目题干：Choose the correct noun.",
        "output": output or LABEL,
    }


def evidence_row(
    question_id: str = "q1",
    *,
    match: bool = True,
    confidence: str = "high",
    precheck_status: str | None = None,
    llm_input_status: str | None = None,
) -> dict[str, object]:
    row = {
        "schema_version": "terminal-label-discriminator-evidence-v1",
        "review_id": f"final-label-discriminator-v1:{question_id}:{LABEL}",
        "question_id": question_id,
        "parent_id": question_id,
        "source_line": 1,
        "is_sub_question": False,
        "legacy_label": LABEL,
        "canonical_label": CANONICAL,
        "llm_match": match,
        "status": "candidate",
        "model": "DeepSeek-V4-Flash",
        "prompt_version": "final-label-discriminator-v1",
        "confidence": confidence,
        "reason": "题目直接考查名词辨析。",
    }
    if precheck_status is not None:
        row["input_precheck"] = {
            "status": precheck_status,
            "reason": "测试状态",
        }
    if llm_input_status is not None:
        row["llm_input_status"] = llm_input_status
    return row


class FinalQualitySnapshotTests(unittest.TestCase):
    def test_complete_positive_evidence_promotes_source_row_and_records_summary(self):
        from english_knowledge_tagger.final_quality_snapshot import build_final_quality_snapshot

        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            run_dir = directory / "run"
            label_dir = run_dir / "labels" / "slug"
            label_dir.mkdir(parents=True)
            (label_dir / "evidence.jsonl").write_text(
                json.dumps(evidence_row(), ensure_ascii=False) + "\n", encoding="utf-8"
            )
            source = directory / "source.jsonl"
            source.write_text(json.dumps(source_row(), ensure_ascii=False) + "\n", encoding="utf-8")
            rulebook = write_rulebook(directory / "rulebook.csv")
            migration = write_migration(directory / "migration.json")
            output = directory / "snapshot"

            report = build_final_quality_snapshot(
                run_dir=run_dir,
                source_path=source,
                output_dir=output,
                excluded_labels=(),
                teacher_csv=rulebook,
                taxonomy_migration=migration,
            )

            candidate_rows = [json.loads(line) for line in (output / "question_candidates.jsonl").read_text().splitlines()]
            holds = (output / "holds.jsonl").read_text(encoding="utf-8")

        self.assertEqual(report["source_records"], 1)
        self.assertEqual(report["question_candidates"], 1)
        self.assertEqual(report["holds"], 0)
        self.assertEqual(candidate_rows[0]["source_record"]["question_id"], "q1")
        self.assertEqual(holds, "")

    def test_excluded_label_and_false_or_error_evidence_are_holds(self):
        from english_knowledge_tagger.final_quality_snapshot import build_final_quality_snapshot

        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            run_dir = directory / "run"
            label_dir = run_dir / "labels" / "slug"
            label_dir.mkdir(parents=True)
            rows = [evidence_row("q1", match=False), evidence_row("q2", match=True, confidence="low")]
            (label_dir / "evidence.jsonl").write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8"
            )
            source = directory / "source.jsonl"
            source.write_text(
                "\n".join((json.dumps(source_row("q1"), ensure_ascii=False), json.dumps(source_row("q2"), ensure_ascii=False)))
                + "\n",
                encoding="utf-8",
            )
            output = directory / "snapshot"
            report = build_final_quality_snapshot(
                run_dir=run_dir,
                source_path=source,
                output_dir=output,
                excluded_labels=(LABEL,),
                teacher_csv=write_rulebook(directory / "rulebook.csv"),
                taxonomy_migration=write_migration(directory / "migration.json"),
            )
            hold_rows = [json.loads(line) for line in (output / "holds.jsonl").read_text().splitlines()]

        self.assertEqual(report["question_candidates"], 0)
        self.assertEqual(report["holds"], 2)
        self.assertEqual({row["hold_reason"] for row in hold_rows}, {"label_excluded"})

    def test_cli_writes_report_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            run_dir = directory / "run"
            label_dir = run_dir / "labels" / "slug"
            label_dir.mkdir(parents=True)
            (label_dir / "evidence.jsonl").write_text(json.dumps(evidence_row(), ensure_ascii=False) + "\n", encoding="utf-8")
            source = directory / "source.jsonl"
            source.write_text(json.dumps(source_row(), ensure_ascii=False) + "\n", encoding="utf-8")
            output = directory / "snapshot"
            script = Path(__file__).resolve().parents[1] / "scripts" / "build_final_quality_snapshot.py"
            common = [
                sys.executable, str(script), "--run-dir", str(run_dir), "--source", str(source),
                "--teacher-csv", str(write_rulebook(directory / "rulebook.csv")),
                "--taxonomy-migration", str(write_migration(directory / "migration.json")),
                "--output-dir", str(output),
            ]
            first = subprocess.run(common, capture_output=True, text=True, check=False)
            second = subprocess.run(common, capture_output=True, text=True, check=False)

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn('"question_candidates": 1', first.stdout)
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("refusing to overwrite", second.stderr)

    def test_multiple_run_dirs_are_joined_without_copying_evidence(self):
        from english_knowledge_tagger.final_quality_snapshot import build_final_quality_snapshot

        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            run_one = directory / "run-one" / "labels" / "one"
            run_two = directory / "run-two" / "labels" / "two"
            run_one.mkdir(parents=True)
            run_two.mkdir(parents=True)
            (run_one / "evidence.jsonl").write_text(
                json.dumps(evidence_row("q1"), ensure_ascii=False) + "\n", encoding="utf-8"
            )
            (run_two / "evidence.jsonl").write_text(
                json.dumps(evidence_row("q2"), ensure_ascii=False) + "\n", encoding="utf-8"
            )
            source = directory / "source.jsonl"
            source.write_text(
                "\n".join(
                    json.dumps(source_row(question_id), ensure_ascii=False)
                    for question_id in ("q1", "q2")
                )
                + "\n",
                encoding="utf-8",
            )
            output = directory / "snapshot"
            report = build_final_quality_snapshot(
                run_dirs=(run_one.parents[1], run_two.parents[1]),
                source_path=source,
                output_dir=output,
                excluded_labels=(),
                teacher_csv=write_rulebook(directory / "rulebook.csv"),
                taxonomy_migration=write_migration(directory / "migration.json"),
            )

        self.assertEqual(report["run_dirs"], [str(run_one.parents[1]), str(run_two.parents[1])])
        self.assertEqual(report["evidence_records"], 2)
        self.assertEqual(report["question_candidates"], 2)

    def test_incomplete_positive_evidence_is_held_but_analysis_supported_is_kept(self):
        from english_knowledge_tagger.final_quality_snapshot import build_final_quality_snapshot

        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            run_dir = directory / "run"
            label_dir = run_dir / "labels" / "slug"
            label_dir.mkdir(parents=True)
            evidence_rows = [
                evidence_row("q1", precheck_status="insufficient", llm_input_status="insufficient"),
                evidence_row("q2", precheck_status="analysis_supported", llm_input_status="analysis_supported"),
            ]
            (label_dir / "evidence.jsonl").write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in evidence_rows) + "\n",
                encoding="utf-8",
            )
            source = directory / "source.jsonl"
            source.write_text(
                "\n".join(json.dumps(source_row(question_id), ensure_ascii=False) for question_id in ("q1", "q2"))
                + "\n",
                encoding="utf-8",
            )
            output = directory / "snapshot"
            report = build_final_quality_snapshot(
                run_dir=run_dir,
                source_path=source,
                output_dir=output,
                excluded_labels=(),
                teacher_csv=write_rulebook(directory / "rulebook.csv"),
                taxonomy_migration=write_migration(directory / "migration.json"),
            )
            candidate_rows = [json.loads(line) for line in (output / "question_candidates.jsonl").read_text().splitlines()]
            hold_rows = [json.loads(line) for line in (output / "holds.jsonl").read_text().splitlines()]

        self.assertEqual(report["question_candidates"], 1)
        self.assertEqual(report["holds"], 1)
        self.assertEqual(candidate_rows[0]["question_id"], "q2")
        self.assertEqual(hold_rows[0]["hold_reason"], "input_insufficient")


if __name__ == "__main__":
    unittest.main()
