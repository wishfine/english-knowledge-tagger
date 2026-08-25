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

    def do_POST(self):  # noqa: N802 - stdlib hook name
        content_length = int(self.headers["Content-Length"])
        self.__class__.requests.append(json.loads(self.rfile.read(content_length)))
        body = json.dumps(
            {
                "id": "chatcmpl-cli-test",
                "model": "ds-v4-flash",
                "choices": [
                    {"message": {"content": "新知识树@语法词法@名词@名词的数"}}
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


class LabelCandidatesCliTests(unittest.TestCase):
    def test_cli_writes_review_candidates_without_mutating_source_input(self):
        _Handler.requests = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                directory = Path(temp_dir)
                source = directory / "review_packet.jsonl"
                source.write_text(
                    json.dumps(
                        {
                            "question_id": "child-1",
                            "parent_id": "parent-1",
                            "is_sub_question": True,
                            "input": "题目答案：Japanese; Englishmen; Germans。解析：考查名词的数。",
                            "output": "知识点@词汇@词汇（音/形/义）",
                        },
                        ensure_ascii=False,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                output = directory / "candidates.jsonl"
                script = Path(__file__).resolve().parents[1] / "scripts" / "label_candidates.py"
                endpoint = f"http://127.0.0.1:{server.server_port}/v1/chat/completions"

                completed = subprocess.run(
                    [
                        sys.executable,
                        str(script),
                        "--input",
                        str(source),
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
                self.assertEqual(row["question_id"], "child-1")
                self.assertEqual(row["candidate_labels"], ["新知识树@语法词法@名词@名词的数"])
                self.assertEqual(row["status"], "candidate")
                self.assertEqual(row["original_output"], "知识点@词汇@词汇（音/形/义）")
                self.assertIn("考查名词的数", _Handler.requests[0]["messages"][0]["content"])
        finally:
            server.shutdown()
            server.server_close()

    def test_cli_does_not_reuse_a_previous_row_when_later_json_is_invalid(self):
        _Handler.requests = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                directory = Path(temp_dir)
                source = directory / "review_packet.jsonl"
                source.write_text(
                    json.dumps({"question_id": "child-1", "input": "题目解析：考查名词。"})
                    + "\nnot-json\n",
                    encoding="utf-8",
                )
                output = directory / "candidates.jsonl"
                script = Path(__file__).resolve().parents[1] / "scripts" / "label_candidates.py"
                endpoint = f"http://127.0.0.1:{server.server_port}/v1/chat/completions"

                completed = subprocess.run(
                    [
                        sys.executable,
                        str(script),
                        "--input",
                        str(source),
                        "--output",
                        str(output),
                        "--endpoint",
                        endpoint,
                        "--limit",
                        "2",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )

                rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(rows[1]["status"], "error")
                self.assertIsNone(rows[1]["question_id"])
        finally:
            server.shutdown()
            server.server_close()
