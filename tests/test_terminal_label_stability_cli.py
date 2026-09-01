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
    requests = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers["Content-Length"])
        self.__class__.requests.append(json.loads(self.rfile.read(length)))
        body = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "decision": "keep",
                                    "confidence": "high",
                                    "criterion_evidence": ["题目直接依赖目标知识点"],
                                    "missing_context": [],
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


class TerminalLabelStabilityCliTests(unittest.TestCase):
    def test_packet_builder_cli_writes_definition_variants(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
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
                        "打标解读（标绿的标签，新题不再打）": "原始释义。",
                        "大模型压缩+人工微调的释义": "压缩释义。",
                    }
                )
            overrides = root / "overrides.json"
            overrides.write_text(
                json.dumps(
                    {
                        "schema_version": "knowledge-definition-overrides-v1",
                        "overrides": [
                            {
                                "label": "知识点->词汇->构词法->转化法",
                                "replacement_definition": "覆盖释义；不标派生。",
                                "status": "active_for_experiment",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            migration = root / "migration.json"
            migration.write_text(
                json.dumps(
                    {"schema_version": "knowledge-taxonomy-migration-v1", "rules": []}
                ),
                encoding="utf-8",
            )
            materialized = root / "materialized.jsonl"
            materialized.write_text(
                json.dumps(
                    {
                        "verify_label": "知识点@词汇@构词法@转化法",
                        "question_id": "q1",
                        "parent_id": "q1",
                        "is_sub_question": False,
                        "input": "题型结构为：填空题\n题型名称为：语法填空\n题目题干：water作动词。",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            gold = root / "gold.jsonl"
            gold.write_text(
                json.dumps(
                    {
                        "verify_label": "知识点@词汇@构词法@转化法",
                        "question_id": "q1",
                        "decision": "keep",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            packet = root / "packet.jsonl"
            report = root / "packet.report.json"
            project = Path(__file__).resolve().parents[1]
            builder = project / "scripts" / "build_terminal_label_stability_packet.py"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(builder),
                    "--materialized",
                    str(materialized),
                    "--pseudo-gold",
                    str(gold),
                    "--verify-label",
                    "知识点@词汇@构词法@转化法",
                    "--teacher-csv",
                    str(teacher),
                    "--definition-overrides",
                    str(overrides),
                    "--taxonomy-migration",
                    str(migration),
                    "--output",
                    str(packet),
                    "--report",
                    str(report),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            rows = [json.loads(line) for line in packet.read_text(encoding="utf-8").splitlines()]
            self.assertEqual({row["definition_variant"] for row in rows}, {"D0", "D1", "D2"})

    def test_runner_and_analyzer_keep_gold_out_of_model_payload(self):
        _Handler.requests = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                packet = root / "packet.jsonl"
                packet_row = {
                    "schema_version": "terminal-label-stability-packet-v1",
                    "review_id": "terminal-label-stability-v1:D2:label:q1",
                    "question_id": "q1",
                    "parent_id": "q1",
                    "source_line": 1,
                    "legacy_label": "知识点@词汇@构词法@转化法",
                    "canonical_label": "知识点->词汇->构词法->转化法",
                    "definition_variant": "D2",
                    "definition_text": "词形不变且词性改变。",
                    "question_text": "water在句中用作动词。",
                    "route_key": {
                        "scope": "parent",
                        "declared_type_structure": "填空题",
                        "declared_type_name": "语法填空",
                    },
                    "pseudo_gold_decision": "keep",
                    "split": "locked_test",
                    "split_seed": "seed",
                    "source_review_id": "dynamic:q1",
                }
                packet.write_text(
                    json.dumps(packet_row, ensure_ascii=False) + "\n", encoding="utf-8"
                )
                output = root / "run.jsonl"
                report = root / "run.report.json"
                project = Path(__file__).resolve().parents[1]
                runner = project / "scripts" / "validate_terminal_label_stability.py"
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(runner),
                        "--input",
                        str(packet),
                        "--output",
                        str(output),
                        "--report",
                        str(report),
                        "--endpoint",
                        f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                        "--run-name",
                        "r1",
                        "--concurrency",
                        "1",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                prompt = _Handler.requests[0]["messages"][0]["content"]
                self.assertNotIn("pseudo_gold", prompt)
                self.assertNotIn("填空题", prompt)
                self.assertEqual(
                    _Handler.requests[0]["chat_template_kwargs"], {"enable_thinking": False}
                )
                evidence = json.loads(output.read_text(encoding="utf-8"))
                self.assertEqual(evidence["decision"], "keep")
                self.assertEqual(evidence["run_name"], "r1")
                self.assertEqual(evidence["source_review_id"], "dynamic:q1")

                analysis = root / "analysis.json"
                analyzer = project / "scripts" / "analyze_terminal_label_stability_runs.py"
                analyzed = subprocess.run(
                    [
                        sys.executable,
                        str(analyzer),
                        "--packet",
                        str(packet),
                        "--run",
                        f"r1={output}",
                        "--run",
                        f"r2={output}",
                        "--run",
                        f"r3={output}",
                        "--output",
                        str(analysis),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(analyzed.returncode, 0, analyzed.stderr)
                summary = json.loads(analysis.read_text(encoding="utf-8"))
                group = next(iter(summary["groups"].values()))
                self.assertTrue(group["passes_precision_first_gate"])

                selection = root / "selection.json"
                selector = project / "scripts" / "select_terminal_definition_variants.py"
                selected = subprocess.run(
                    [
                        sys.executable,
                        str(selector),
                        "--analysis",
                        str(analysis),
                        "--split",
                        "locked_test",
                        "--output",
                        str(selection),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(selected.returncode, 0, selected.stderr)
                selected_payload = json.loads(selection.read_text(encoding="utf-8"))
                self.assertEqual(
                    next(iter(selected_payload["labels"].values()))["status"], "selected"
                )
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
