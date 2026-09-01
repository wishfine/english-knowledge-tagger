import csv
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import unittest


class _LeafHandler(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers["Content-Length"])
        payload = json.loads(self.rfile.read(length))
        self.__class__.requests.append(payload)
        prompt = payload["messages"][0]["content"]
        choice = re.search(r"(?m)^- (知识点->[^\n]+)$", prompt).group(1)
        body = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"choice": choice, "evidence": "候选直接解释答案"},
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


class DynamicLeafCliTests(unittest.TestCase):
    def test_build_and_run_sibling_resolver(self):
        _LeafHandler.requests = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _LeafHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                project = Path(__file__).resolve().parents[1]
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
                    for label, definition in (
                        ("知识点->语用->时间->顺序", "事件先后"),
                        ("知识点->语用->时间->时段", "持续时间"),
                    ):
                        writer.writerow(
                            {
                                "末级知识点": label,
                                "打标解读（标绿的标签，新题不再打）": definition,
                                "大模型压缩+人工微调的释义": definition,
                            }
                        )
                packet = root / "stability.jsonl"
                packet_row = {
                    "schema_version": "terminal-label-stability-packet-v1",
                    "review_id": "D1:q1",
                    "question_id": "q1",
                    "parent_id": "q1",
                    "source_line": 1,
                    "legacy_label": "知识点@语用@时间@顺序",
                    "canonical_label": "知识点->语用->时间->顺序",
                    "definition_variant": "D1",
                    "definition_text": "事件先后",
                    "question_text": "How long did it take?",
                    "route_key": {"scope": "parent"},
                    "pseudo_gold_decision": "remove",
                    "split": "locked_test",
                    "split_seed": "seed",
                }
                packet.write_text(json.dumps(packet_row, ensure_ascii=False) + "\n", encoding="utf-8")
                direct = root / "direct.jsonl"
                direct.write_text(
                    json.dumps(
                        {
                            "review_id": "D1:q1",
                            "decision": "non_target",
                            "confidence": "high",
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                ambiguity = root / "ambiguity.json"
                ambiguity.write_text(
                    json.dumps(
                        {
                            "labels": [
                                {
                                    "canonical_label": "知识点->语用->时间->顺序",
                                    "confusion_neighbors": [
                                        {"canonical_label": "知识点->语用->时间->时段", "count": 5}
                                    ],
                                }
                            ]
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                selection = root / "selection.json"
                selection.write_text(
                    json.dumps(
                        {
                            "labels": {
                                "知识点->语用->时间->顺序": {
                                    "status": "selected",
                                    "definition_variant": "D1",
                                }
                            }
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                tasks = root / "tasks.jsonl"
                holds = root / "holds.jsonl"
                task_report = root / "tasks.report.json"
                built = subprocess.run(
                    [
                        sys.executable,
                        str(project / "scripts" / "build_dynamic_leaf_tasks.py"),
                        "--packet",
                        str(packet),
                        "--direct-run",
                        f"r1={direct}",
                        "--direct-run",
                        f"r2={direct}",
                        "--direct-run",
                        f"r3={direct}",
                        "--ambiguity-manifest",
                        str(ambiguity),
                        "--definition-selection",
                        str(selection),
                        "--output",
                        str(tasks),
                        "--hold-output",
                        str(holds),
                        "--report",
                        str(task_report),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(built.returncode, 0, built.stderr)
                self.assertEqual(len(tasks.read_text(encoding="utf-8").splitlines()), 1)

                evidence = root / "evidence.jsonl"
                run_report = root / "run.report.json"
                ran = subprocess.run(
                    [
                        sys.executable,
                        str(project / "scripts" / "validate_dynamic_leaf_routing.py"),
                        "--input",
                        str(tasks),
                        "--teacher-csv",
                        str(teacher),
                        "--output",
                        str(evidence),
                        "--report",
                        str(run_report),
                        "--endpoint",
                        f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                        "--mode",
                        "siblings",
                        "--run-name",
                        "s1",
                        "--concurrency",
                        "1",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(ran.returncode, 0, ran.stderr)
                result = json.loads(evidence.read_text(encoding="utf-8"))
                self.assertEqual(result["status"], "candidate")
                self.assertEqual(result["candidate_label"], "知识点->语用->时间->时段")
                self.assertEqual(result["mode"], "siblings")
                self.assertEqual(
                    _LeafHandler.requests[0]["chat_template_kwargs"], {"enable_thinking": False}
                )
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
