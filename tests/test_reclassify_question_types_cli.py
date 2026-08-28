import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from english_knowledge_tagger.type_reclassification import SAMPLE_SCHEMA_VERSION


def make_stream_handler(requests):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - stdlib hook
            length = int(self.headers["Content-Length"])
            requests.append(json.loads(self.rfile.read(length)))
            chunks = (
                {"id": "chatcmpl-stream", "model": "DeepSeek-V4-Flash", "choices": [{"delta": {"role": "assistant"}}]},
                {"id": "chatcmpl-stream", "model": "DeepSeek-V4-Flash", "choices": [{"delta": {"content": "题型@词句运用@"}}]},
                {"id": "chatcmpl-stream", "model": "DeepSeek-V4-Flash", "choices": [{"delta": {"content": "单词拼写"}}]},
            )
            body = "".join(
                f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n" for chunk in chunks
            ) + "data: [DONE]\n\n"
            encoded = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *_args):
            return

    return Handler


def sample_row(question_id):
    return {
        "schema_version": SAMPLE_SCHEMA_VERSION,
        "review_id": f"question-type-classifier-v1:{question_id}:{question_id}",
        "source_path": "source.jsonl",
        "source_line": question_id,
        "question_id": str(question_id),
        "parent_id": str(question_id),
        "is_sub_question": False,
        "sampled_type_labels": ["题型@旧分类"],
        "current_type_labels": ["题型@旧分类"],
        "instruction": "旧 instruction 不应发送",
        "input": "题型结构为：填空题\n题型名称为：单词拼写\n题目题干：The E____ is our home.",
        "output": "题型@旧分类",
    }


class ReclassifyQuestionTypesCliTests(unittest.TestCase):
    def test_run_uses_both_streaming_endpoints_and_sanitizes_input(self):
        first_requests = []
        second_requests = []
        first = ThreadingHTTPServer(("127.0.0.1", 0), make_stream_handler(first_requests))
        second = ThreadingHTTPServer(("127.0.0.1", 0), make_stream_handler(second_requests))
        threads = [
            threading.Thread(target=server.serve_forever, daemon=True)
            for server in (first, second)
        ]
        for thread in threads:
            thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                directory = Path(temp_dir)
                packet = directory / "sample.jsonl"
                packet.write_text(
                    "".join(
                        json.dumps(sample_row(question_id), ensure_ascii=False) + "\n"
                        for question_id in (1, 2)
                    ),
                    encoding="utf-8",
                )
                prompt = directory / "prompt.txt"
                prompt.write_text("只输出最终题型标签。\n", encoding="utf-8")
                output = directory / "results.jsonl"
                report = directory / "report.json"
                script = Path(__file__).resolve().parents[1] / "scripts" / "reclassify_question_types.py"
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(script),
                        "run",
                        "--input", str(packet),
                        "--output", str(output),
                        "--report", str(report),
                        "--prompt", str(prompt),
                        "--endpoint", f"http://127.0.0.1:{first.server_port}/v1/chat/completions",
                        "--endpoint", f"http://127.0.0.1:{second.server_port}/v1/chat/completions",
                        "--per-endpoint-concurrency", "1",
                        "--limit", "2",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                results = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
                report_payload = json.loads(report.read_text(encoding="utf-8"))

            self.assertEqual(len(first_requests), 1)
            self.assertEqual(len(second_requests), 1)
            self.assertTrue(first_requests[0]["stream"])
            self.assertTrue(second_requests[0]["stream"])
            for request in first_requests + second_requests:
                content = request["messages"][0]["content"]
                self.assertNotIn("题型结构为", content)
                self.assertNotIn("题型名称为", content)
                self.assertNotIn("旧 instruction", content)
            self.assertEqual(
                {row["predicted_type_label"] for row in results},
                {"题型@词句运用@单词拼写"},
            )
            self.assertEqual(report_payload["candidate"], 2)
            self.assertTrue(report_payload["stream"])
            self.assertEqual(report_payload["total_concurrency"], 2)
        finally:
            first.shutdown()
            first.server_close()
            second.shutdown()
            second.server_close()


if __name__ == "__main__":
    unittest.main()
