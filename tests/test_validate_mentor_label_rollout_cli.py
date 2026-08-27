import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest

from test_mentor_direct_rollout import LABEL, definitions, write_json, write_migration, write_rulebook


class _Handler(BaseHTTPRequestHandler):
    requests: list[dict[str, object]] = []

    def do_POST(self):  # noqa: N802 - stdlib hook
        content_length = int(self.headers["Content-Length"])
        self.__class__.requests.append(json.loads(self.rfile.read(content_length)))
        body = json.dumps(
            {
                "id": "chatcmpl-mentor-direct",
                "model": "ds-v4-flash",
                "choices": [
                    {
                        "message": {
                            "content": '{"reason":"名词单选","match":true,"should_be":"正确"}'
                        }
                    }
                ],
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


def packet_row() -> dict[str, object]:
    return {
        "schema_version": "mentor-label-rollout-packet-v1",
        "review_id": "mentor-direct-v1:1:target",
        "source_line": 1,
        "question_id": "101",
        "parent_id": "100",
        "is_sub_question": True,
        "verify_label": LABEL,
        "instruction": "给题目打标",
        "input": "题型名称为：词汇单选\n题目题干：book",
        "output_all": LABEL,
    }


class ValidateMentorLabelRolloutCliTests(unittest.TestCase):
    def test_cli_writes_gate_compatible_evidence_with_the_calibrated_payload_settings(self):
        _Handler.requests = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                directory = Path(temp_dir)
                packet = directory / "packet.jsonl"
                packet.write_text(json.dumps(packet_row(), ensure_ascii=False) + "\n", encoding="utf-8")
                definitions_path = write_json(directory / "definitions.json", definitions())
                output = directory / "evidence.jsonl"
                script = Path(__file__).resolve().parents[1] / "scripts" / "validate_mentor_label_rollout.py"
                endpoint = f"http://127.0.0.1:{server.server_port}/v1/chat/completions"
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(script),
                        "--input",
                        str(packet),
                        "--label-definitions",
                        str(definitions_path),
                        "--teacher-csv",
                        str(write_rulebook(directory / "rulebook.csv")),
                        "--taxonomy-migration",
                        str(write_migration(directory / "migration.json")),
                        "--output",
                        str(output),
                        "--endpoint",
                        endpoint,
                        "--limit",
                        "1",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                evidence = json.loads(output.read_text(encoding="utf-8"))

            self.assertTrue(evidence["llm_match"])
            self.assertEqual(evidence["status"], "candidate")
            self.assertEqual(evidence["prompt_version"], "mentor-direct-v1")
            self.assertEqual(_Handler.requests[0]["temperature"], 0.1)
            self.assertEqual(_Handler.requests[0]["max_tokens"], 512)
            self.assertEqual(_Handler.requests[0]["chat_template_kwargs"], {"enable_thinking": False})
            self.assertNotIn("题型名称为", _Handler.requests[0]["messages"][0]["content"])
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
