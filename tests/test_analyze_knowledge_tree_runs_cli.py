import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


def _run_row(mode: str) -> dict[str, object]:
    return {
        "task_id": "replace-1",
        "status": "tree_candidate",
        "candidate_label": "知识点->词法->冠词->a/an的区别",
        "terminal_definition_mode": mode,
        "trigger_kinds": ["replace"],
        "trace": [],
    }


class AnalyzeKnowledgeTreeRunsCliTests(unittest.TestCase):
    def test_cli_summarizes_three_runs_for_each_definition_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            arguments: list[str] = []
            for option, mode, prefix in (
                ("--with-definitions", "compressed", "compressed"),
                ("--without-definitions", "none", "none"),
            ):
                for index in (1, 2, 3):
                    path = directory / f"{prefix}-{index}.jsonl"
                    path.write_text(json.dumps(_run_row(mode), ensure_ascii=False) + "\n", encoding="utf-8")
                    arguments.extend([option, f"{prefix}-{index}={path}"])
            output = directory / "report.json"
            script = Path(__file__).resolve().parents[1] / "scripts" / "analyze_knowledge_tree_runs.py"

            completed = subprocess.run(
                [sys.executable, str(script), *arguments, "--output", str(output)],
                check=False,
                capture_output=True,
                text=True,
            )

            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(report["groups"]["compressed"]["common_tasks"], 1)
            self.assertEqual(report["groups"]["none"]["replace"]["all_three_candidate_agreement"], 1.0)


if __name__ == "__main__":
    unittest.main()
