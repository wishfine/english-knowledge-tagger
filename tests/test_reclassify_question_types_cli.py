import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from english_knowledge_tagger.type_reclassification import (
    PROMPT_VERSION,
    SAMPLE_SCHEMA_VERSION,
)


def discovery_payload():
    return {
        "candidate_type_label": "单词拼写",
        "task_mechanism": "根据首字母、中文提示和句意填写完整单词",
        "key_evidence": ["空格同时提供首字母和中文提示"],
        "information_sufficiency": "sufficient",
        "confidence": 0.98,
    }


def make_stream_handler(requests):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - stdlib hook
            length = int(self.headers["Content-Length"])
            requests.append(json.loads(self.rfile.read(length)))
            content = json.dumps(discovery_payload(), ensure_ascii=False)
            split_at = len(content) // 2
            chunks = (
                {"id": "chatcmpl-stream", "model": "DeepSeek-V4-Flash", "choices": [{"delta": {"role": "assistant"}}]},
                {"id": "chatcmpl-stream", "model": "DeepSeek-V4-Flash", "choices": [{"delta": {"content": content[:split_at]}}]},
                {"id": "chatcmpl-stream", "model": "DeepSeek-V4-Flash", "choices": [{"delta": {"content": content[split_at:]}}]},
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


def sample_row(
    question_id, type_label="题型@旧分类", instruction="旧 instruction 不应发送"
):
    return {
        "schema_version": SAMPLE_SCHEMA_VERSION,
        "review_id": f"question-type-discovery-v1:{question_id}:{question_id}",
        "source_path": "source.jsonl",
        "source_line": question_id,
        "question_id": str(question_id),
        "parent_id": str(question_id),
        "is_sub_question": False,
        "sampled_type_labels": [type_label],
        "current_type_labels": [type_label],
        "instruction": instruction,
        "input": (
            "题型结构为：填空题\n"
            "题型名称为：单词拼写\n"
            "题目题干：The E____ is our home.\n\n"
            "根据以上信息，当前题目所属的题型方法类目和知识点类目为："
        ),
        "output": "题型@旧分类",
    }


class ReclassifyQuestionTypesCliTests(unittest.TestCase):
    def test_run_rejects_sub_question_before_requesting_service(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            packet = directory / "sample.jsonl"
            row = sample_row(1)
            row["is_sub_question"] = True
            packet.write_text(
                json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            script = (
                Path(__file__).resolve().parents[1]
                / "scripts"
                / "reclassify_question_types.py"
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "run",
                    "--input",
                    str(packet),
                    "--type-label",
                    "题型@旧分类",
                    "--output",
                    str(directory / "results.jsonl"),
                    "--endpoint",
                    "http://127.0.0.1:1/v1/chat/completions",
                    "--limit",
                    "1",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("only is_sub_question=false is eligible", completed.stderr)

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
                        json.dumps(row, ensure_ascii=False) + "\n"
                        for row in (
                            sample_row(0, "题型@其他分类"),
                            sample_row(1),
                            sample_row(2, instruction="另一 instruction 也不应发送"),
                        )
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
                        "--type-label", "题型@旧分类",
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
                resumed = subprocess.run(
                    [*completed.args, "--resume"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(resumed.returncode, 0, resumed.stderr)
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
                self.assertNotIn("根据以上信息", content)
                self.assertNotIn("旧 instruction", content)
                self.assertNotIn("另一 instruction", content)
            self.assertEqual(
                {row["candidate_type_label"] for row in results},
                {"单词拼写"},
            )
            self.assertTrue(
                all(
                    set(row)
                    == {
                        "question_id",
                        "source_line",
                        "input",
                        "candidate_type_label",
                        "task_mechanism",
                        "key_evidence",
                        "information_sufficiency",
                        "confidence",
                        "status",
                    }
                    for row in results
                )
            )
            self.assertTrue(all(len(row["key_evidence"]) == 1 for row in results))
            self.assertTrue(all("题型结构为" not in row["input"] for row in results))
            self.assertTrue(all("题型名称为" not in row["input"] for row in results))
            self.assertTrue(all("根据以上信息" not in row["input"] for row in results))
            self.assertEqual(report_payload["source_path"], "source.jsonl")
            self.assertEqual(
                report_payload["source_instructions"],
                [
                    {"instruction": "另一 instruction 也不应发送", "record_count": 1},
                    {"instruction": "旧 instruction 不应发送", "record_count": 1},
                ],
            )
            self.assertEqual(report_payload["current_type_label"], "题型@旧分类")
            self.assertEqual(report_payload["sample_path"], str(packet))
            self.assertEqual(report_payload["result_path"], str(output))
            self.assertEqual(report_payload["classifier_prompt_path"], str(prompt))
            self.assertEqual(report_payload["sample_count"], 2)
            self.assertEqual(report_payload["total_processed"], 2)
            self.assertEqual(report_payload["candidate"], 2)
            self.assertEqual(report_payload["error"], 0)
            self.assertEqual(report_payload["candidate_type_counts"], {"单词拼写": 2})
            self.assertEqual(
                report_payload["information_sufficiency_counts"], {"sufficient": 2}
            )
            self.assertTrue(report_payload["stream"])
            self.assertEqual(report_payload["max_tokens"], 512)
            self.assertTrue(all(request["max_tokens"] == 512 for request in first_requests + second_requests))
        finally:
            first.shutdown()
            first.server_close()
            second.shutdown()
            second.server_close()


if __name__ == "__main__":
    unittest.main()
