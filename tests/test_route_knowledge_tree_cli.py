import csv
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest


class _Handler(BaseHTTPRequestHandler):
    choices = ["知识点->词法", "知识点->词法->冠词", "知识点->词法->冠词->a/an的区别"]
    requests: list[dict[str, object]] = []

    def do_POST(self):  # noqa: N802 - stdlib hook
        content_length = int(self.headers["Content-Length"])
        self.__class__.requests.append(json.loads(self.rfile.read(content_length)))
        choice = self.__class__.choices[len(self.__class__.requests) - 1]
        body = json.dumps(
            {
                "id": "tree-choice",
                "model": "ds-v4-flash",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "choice": choice,
                                    "candidate_coverage": "covered",
                                    "evidence": "umbrella",
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
            },
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


class RouteKnowledgeTreeCliTests(unittest.TestCase):
    def test_cli_routes_one_task_with_a_replayable_three_step_trace(self):
        _Handler.requests = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                directory = Path(temp_dir)
                task = directory / "tasks.jsonl"
                task.write_text(
                    json.dumps(
                        {
                            "task_id": "kp-tree:child-1",
                            "source_line": 1,
                            "question_context": "题干：It is ___ umbrella. 答案：an。",
                            "allowed_knowledge_prefixes": ["知识点->词法"],
                            "trigger_kinds": ["add_missing_required"],
                        },
                        ensure_ascii=False,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                teacher = directory / "teacher.csv"
                with teacher.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(
                        handle,
                        fieldnames=(
                            "末级知识点",
                            "打标解读（标绿的标签，新题不再打）",
                            "大模型压缩+人工微调的释义",
                        ),
                    )
                    writer.writeheader()
                    writer.writerow(
                        {
                            "末级知识点": "知识点->词法->冠词->a/an的区别",
                            "打标解读（标绿的标签，新题不再打）": "按发音选择 a/an。",
                            "大模型压缩+人工微调的释义": "按发音选择 a/an。",
                        }
                    )
                output = directory / "results.jsonl"
                report = directory / "timing.report.json"
                script = Path(__file__).resolve().parents[1] / "scripts" / "route_knowledge_tree.py"

                completed = subprocess.run(
                    [
                        sys.executable,
                        str(script),
                        "--input",
                        str(task),
                        "--teacher-csv",
                        str(teacher),
                        "--output",
                        str(output),
                        "--report",
                        str(report),
                        "--endpoint",
                        f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                        "--limit",
                        "1",
                        "--terminal-definition-mode",
                        "none",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )

                row = json.loads(output.read_text(encoding="utf-8"))
                timing = json.loads(report.read_text(encoding="utf-8"))
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(row["status"], "tree_candidate")
                self.assertEqual(row["candidate_label"], "知识点->词法->冠词->a/an的区别")
                self.assertEqual(len(row["trace"]), 3)
                self.assertEqual(row["terminal_definition_mode"], "none")
                self.assertEqual(len(_Handler.requests), 3)
                self.assertNotIn("按发音选择 a/an。", _Handler.requests[-1]["messages"][0]["content"])
                self.assertEqual(timing["processed"], 1)
                self.assertGreaterEqual(timing["task_elapsed_ms"]["p50"], 0)
                self.assertEqual(
                    {node["parent_path"] for node in timing["nodes"]},
                    {"知识点", "知识点->词法", "知识点->词法->冠词"},
                )
        finally:
            server.shutdown()
            server.server_close()

    def test_cli_applies_definition_overrides_to_terminal_prompt(self):
        _Handler.requests = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                directory = Path(temp_dir)
                task = directory / "tasks.jsonl"
                task.write_text(
                    json.dumps(
                        {
                            "task_id": "kp-tree:child-override",
                            "source_line": 1,
                            "question_context": "题干：It is ___ umbrella. 答案：an。",
                            "allowed_knowledge_prefixes": ["知识点->词法"],
                            "trigger_kinds": ["add_missing_required"],
                        },
                        ensure_ascii=False,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                teacher = directory / "teacher.csv"
                with teacher.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(
                        handle,
                        fieldnames=(
                            "末级知识点",
                            "打标解读（标绿的标签，新题不再打）",
                            "大模型压缩+人工微调的释义",
                        ),
                    )
                    writer.writeheader()
                    writer.writerow(
                        {
                            "末级知识点": "知识点->词法->冠词->a/an的区别",
                            "打标解读（标绿的标签，新题不再打）": "原始定义。",
                            "大模型压缩+人工微调的释义": "原始定义。",
                        }
                    )
                overrides = directory / "overrides.json"
                overrides.write_text(
                    json.dumps(
                        {
                            "schema_version": "knowledge-definition-overrides-v1",
                            "overrides": [
                                {
                                    "label": "知识点->词法->冠词->a/an的区别",
                                    "replacement_definition": "覆盖层定义。",
                                    "status": "active_for_experiment",
                                }
                            ],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                output = directory / "results.jsonl"
                script = Path(__file__).resolve().parents[1] / "scripts" / "route_knowledge_tree.py"
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(script),
                        "--input",
                        str(task),
                        "--teacher-csv",
                        str(teacher),
                        "--definition-overrides",
                        str(overrides),
                        "--output",
                        str(output),
                        "--endpoint",
                        f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                        "--limit",
                        "1",
                        "--terminal-definition-mode",
                        "compressed",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn("覆盖层定义。", _Handler.requests[-1]["messages"][0]["content"])
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
