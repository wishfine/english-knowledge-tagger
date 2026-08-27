import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest

from test_final_label_discriminator import LABEL, write_json, write_migration, write_rulebook


class _Handler(BaseHTTPRequestHandler):
    requests: list[dict[str, object]] = []

    def do_POST(self):  # noqa: N802 - stdlib hook
        content_length = int(self.headers["Content-Length"])
        self.__class__.requests.append(json.loads(self.rfile.read(content_length)))
        body = json.dumps(
            {
                "id": "chatcmpl-final-label",
                "model": "ds-v4-flash",
                "choices": [
                    {
                        "message": {
                            "content": '{"match":true,"confidence":"high","reason":"名词选项构成必要辨析。"}'
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
        "schema_version": "final-label-discriminator-packet-v1",
        "review_id": "final-label-discriminator-v1:1:target",
        "source_line": 1,
        "question_id": "101",
        "parent_id": "100",
        "is_sub_question": False,
        "route_key": {
            "scope": "parent",
            "declared_type_structure": "单选题",
            "declared_type_name": "选择题",
        },
        "verify_label": LABEL,
        "question_text": "题目题干：Choose the right noun.\n题目选项：A. book B. run",
    }


class ValidateFinalLabelDiscriminatorCliTests(unittest.TestCase):
    def test_cli_writes_gate_compatible_unanchored_evidence(self):
        _Handler.requests = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                directory = Path(temp_dir)
                packet = directory / "packet.jsonl"
                packet.write_text(json.dumps(packet_row(), ensure_ascii=False) + "\n", encoding="utf-8")
                definitions = write_json(
                    directory / "definitions.json", {LABEL: {"definition": "仅非复合单选中的名词辨析。"}}
                )
                output = directory / "evidence.jsonl"
                script = Path(__file__).resolve().parents[1] / "scripts" / "validate_final_label_discriminator.py"
                endpoint = f"http://127.0.0.1:{server.server_port}/v1/chat/completions"
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(script),
                        "--input",
                        str(packet),
                        "--label-definitions",
                        str(definitions),
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
            self.assertEqual(evidence["prompt_version"], "final-label-discriminator-v1")
            self.assertEqual(evidence["confidence"], "high")
            self.assertNotIn("output_all", evidence)
            self.assertEqual(_Handler.requests[0]["temperature"], 0)
            self.assertEqual(_Handler.requests[0]["max_tokens"], 512)
            self.assertEqual(_Handler.requests[0]["chat_template_kwargs"], {"enable_thinking": False})
            content = _Handler.requests[0]["messages"][0]["content"]
            self.assertNotIn("题型结构为", content)
            self.assertNotIn("题型名称为", content)
            self.assertNotIn("当前题目打的全部标签", content)
        finally:
            server.shutdown()
            server.server_close()

    def test_cli_requires_limit_or_allow_full(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            packet = directory / "packet.jsonl"
            packet.write_text(json.dumps(packet_row(), ensure_ascii=False) + "\n", encoding="utf-8")
            definitions = write_json(
                directory / "definitions.json", {LABEL: {"definition": "仅非复合单选中的名词辨析。"}}
            )
            script = Path(__file__).resolve().parents[1] / "scripts" / "validate_final_label_discriminator.py"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--input",
                    str(packet),
                    "--label-definitions",
                    str(definitions),
                    "--teacher-csv",
                    str(write_rulebook(directory / "rulebook.csv")),
                    "--taxonomy-migration",
                    str(write_migration(directory / "migration.json")),
                    "--output",
                    str(directory / "evidence.jsonl"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("--allow-full", completed.stderr)


if __name__ == "__main__":
    unittest.main()
