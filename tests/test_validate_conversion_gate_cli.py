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
    requests: list[dict[str, object]] = []

    def do_POST(self):  # noqa: N802 - stdlib hook
        content_length = int(self.headers["Content-Length"])
        self.__class__.requests.append(json.loads(self.rfile.read(content_length)))
        body = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "decision": "non_target",
                                    "confidence": "high",
                                    "source_forms": ["direct"],
                                    "target_forms": ["director"],
                                    "form_unchanged": False,
                                    "pos_or_function_changed": True,
                                    "answer_depends_on_relation": True,
                                    "evidence": "词形发生变化。",
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
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


class ValidateConversionGateCliTests(unittest.TestCase):
    def test_cli_sends_override_definition_and_records_version(self):
        _Handler.requests = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                packet = root / "packet.jsonl"
                packet.write_text(
                    json.dumps(
                        {
                            "schema_version": "conversion-relation-packet-v1",
                            "task_id": "conversion:1",
                            "source_line": 1,
                            "question_id": "q1",
                            "parent_id": "q1",
                            "route_key": {"scope": "parent"},
                            "question_context": "direct → director",
                        },
                        ensure_ascii=False,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                teacher = root / "teacher.csv"
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
                            "末级知识点": "知识点->词汇->构词法->转化法",
                            "打标解读（标绿的标签，新题不再打）": "原始定义。",
                            "大模型压缩+人工微调的释义": "原始定义。",
                        }
                    )
                overrides = root / "overrides.json"
                overrides.write_text(
                    json.dumps(
                        {
                            "schema_version": "knowledge-definition-overrides-v1",
                            "policy_id": "test-v0.1",
                            "overrides": [
                                {
                                    "label": "知识点->词汇->构词法->转化法",
                                    "replacement_definition": "覆盖层定义。",
                                    "status": "active_for_experiment",
                                }
                            ],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                output = root / "evidence.jsonl"
                report = root / "report.json"
                script = Path(__file__).resolve().parents[1] / "scripts" / "validate_conversion_gate.py"

                completed = subprocess.run(
                    [
                        sys.executable,
                        str(script),
                        "--input",
                        str(packet),
                        "--teacher-csv",
                        str(teacher),
                        "--definition-overrides",
                        str(overrides),
                        "--output",
                        str(output),
                        "--report",
                        str(report),
                        "--endpoint",
                        f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                        "--limit",
                        "1",
                        "--concurrency",
                        "1",
                        "--enable-thinking",
                        "true",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )

                self.assertEqual(completed.returncode, 0, completed.stderr)
                evidence = json.loads(output.read_text(encoding="utf-8"))
                report_payload = json.loads(report.read_text(encoding="utf-8"))
                self.assertIn("覆盖层定义。", _Handler.requests[0]["messages"][0]["content"])
                self.assertEqual(evidence["prompt_version"], "conversion-gate-v1-overrides")
                self.assertEqual(evidence["definition_overrides"], str(overrides))
                self.assertEqual(evidence["enable_thinking"], True)
                self.assertEqual(report_payload["definition_overrides"], str(overrides))
                self.assertEqual(report_payload["enable_thinking"], True)
                self.assertEqual(
                    _Handler.requests[0]["chat_template_kwargs"], {"enable_thinking": True}
                )
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
