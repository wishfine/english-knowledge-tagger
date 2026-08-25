import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest


class _Handler(BaseHTTPRequestHandler):
    requests: list[dict[str, object]] = []

    def do_POST(self):  # noqa: N802 - stdlib hook
        content_length = int(self.headers["Content-Length"])
        self.__class__.requests.append(json.loads(self.rfile.read(content_length)))
        body = json.dumps(
            {
                "id": "chatcmpl-knowledge-validation",
                "model": "ds-v4-flash",
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"verdict":"keep","best_label":"知识点->词法->冠词->a/an的区别",'
                                '"evidence":"umbrella 以元音音素开头。","reason":"与目标释义一致。"}'
                            )
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


def validation_item() -> dict[str, object]:
    return {
        "review_id": "kp-validation:child-1:a-an",
        "question_id": "child-1",
        "parent_id": "parent-1",
        "is_sub_question": True,
        "question_context": "题干：It is ___ umbrella. 答案：an。解析：考查 a/an。",
        "legacy_label": "知识点->词法->冠词->a/an的区别",
        "taxonomy_status": "known",
        "target_definition": "按读音选择 a/an。",
        "alternative_labels": [
            {"label": "知识点->词法->冠词->the的用法", "definition": "判断是否使用 the。"}
        ],
        "candidate_pool": {"max_output_labels": 3},
    }


class ValidateKnowledgeLabelsCliTests(unittest.TestCase):
    def test_cli_writes_candidate_verdict_without_mutating_packet(self):
        _Handler.requests = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                directory = Path(temp_dir)
                packet = directory / "packet.jsonl"
                original_text = json.dumps(validation_item(), ensure_ascii=False) + "\n"
                packet.write_text(original_text, encoding="utf-8")
                output = directory / "verdicts.jsonl"
                script = Path(__file__).resolve().parents[1] / "scripts" / "validate_knowledge_labels.py"
                endpoint = f"http://127.0.0.1:{server.server_port}/v1/chat/completions"

                completed = subprocess.run(
                    [
                        sys.executable,
                        str(script),
                        "--input",
                        str(packet),
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
                row = json.loads(output.read_text(encoding="utf-8"))
                self.assertEqual(row["validation"]["verdict"], "keep")
                self.assertEqual(row["status"], "candidate")
                self.assertEqual(packet.read_text(encoding="utf-8"), original_text)
                self.assertIn("待验证历史标签", _Handler.requests[0]["messages"][0]["content"])
        finally:
            server.shutdown()
            server.server_close()

    def test_cli_refuses_existing_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            packet = directory / "packet.jsonl"
            packet.write_text(json.dumps(validation_item(), ensure_ascii=False) + "\n", encoding="utf-8")
            output = directory / "verdicts.jsonl"
            output.write_text("do not overwrite\n", encoding="utf-8")
            script = Path(__file__).resolve().parents[1] / "scripts" / "validate_knowledge_labels.py"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--input",
                    str(packet),
                    "--output",
                    str(output),
                    "--limit",
                    "1",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("refusing to overwrite", completed.stderr)
            self.assertEqual(output.read_text(encoding="utf-8"), "do not overwrite\n")


if __name__ == "__main__":
    unittest.main()
