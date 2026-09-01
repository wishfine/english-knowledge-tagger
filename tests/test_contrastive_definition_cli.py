import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest


class _DefinitionHandler(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers["Content-Length"])
        self.__class__.requests.append(json.loads(self.rfile.read(length)))
        definitions = []
        for index in range(1, 4):
            definitions.append(
                {
                    "candidate_id": f"D3-{index}",
                    "positive_criteria": f"必要条件{index}",
                    "neighbor_exclusions": ["排除相邻标签"],
                    "insufficient_rule": "缺信息时 insufficient",
                    "co_label_rule": "允许合理共标",
                    "appearance_dependency_rule": "出现不等于依赖",
                }
            )
        body = json.dumps(
            {"choices": [{"message": {"content": json.dumps({"definitions": definitions}, ensure_ascii=False)}}]},
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


class ContrastiveDefinitionCliTests(unittest.TestCase):
    def test_generate_expand_and_select(self):
        _DefinitionHandler.requests = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _DefinitionHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                project = Path(__file__).resolve().parents[1]
                packet = root / "packet.jsonl"
                rows = []
                for question_id, split, decision, text in (
                    ("q1", "definition_train", "keep", "TRAIN ONLY"),
                    ("q2", "definition_dev", "remove", "DEV SECRET"),
                    ("q3", "locked_test", "keep", "TEST SECRET"),
                ):
                    rows.append(
                        {
                            "schema_version": "terminal-label-stability-packet-v1",
                            "review_id": f"D0:{question_id}",
                            "question_id": question_id,
                            "parent_id": question_id,
                            "source_line": 1,
                            "legacy_label": "知识点@语用@时间@顺序",
                            "canonical_label": "知识点->语用->时间->顺序",
                            "definition_variant": "D0",
                            "definition_text": "原始释义",
                            "question_text": text,
                            "route_key": {"scope": "parent"},
                            "pseudo_gold_decision": decision,
                            "split": split,
                            "split_seed": "seed",
                        }
                    )
                packet.write_text(
                    "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8",
                )
                ambiguity = root / "ambiguity.json"
                ambiguity.write_text(
                    json.dumps(
                        {
                            "labels": [
                                {
                                    "canonical_label": "知识点->语用->时间@顺序".replace("@", "->"),
                                    "confusion_neighbors": [
                                        {"canonical_label": "知识点->语用->时间->时段", "count": 4}
                                    ],
                                }
                            ]
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                definitions = root / "definitions.json"
                generation_report = root / "generation.report.json"
                generated = subprocess.run(
                    [
                        sys.executable,
                        str(project / "scripts" / "generate_contrastive_definitions.py"),
                        "--packet",
                        str(packet),
                        "--ambiguity-manifest",
                        str(ambiguity),
                        "--canonical-label",
                        "知识点->语用->时间->顺序",
                        "--output",
                        str(definitions),
                        "--report",
                        str(generation_report),
                        "--endpoint",
                        f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(generated.returncode, 0, generated.stderr)
                sent_prompt = _DefinitionHandler.requests[0]["messages"][0]["content"]
                self.assertIn("TRAIN ONLY", sent_prompt)
                self.assertNotIn("DEV SECRET", sent_prompt)
                self.assertNotIn("TEST SECRET", sent_prompt)

                dev_packet = root / "dev.jsonl"
                expanded = subprocess.run(
                    [
                        sys.executable,
                        str(project / "scripts" / "expand_contrastive_definition_packet.py"),
                        "--packet",
                        str(packet),
                        "--definitions",
                        str(definitions),
                        "--split",
                        "definition_dev",
                        "--output",
                        str(dev_packet),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(expanded.returncode, 0, expanded.stderr)
                dev_rows = [json.loads(line) for line in dev_packet.read_text(encoding="utf-8").splitlines()]
                self.assertEqual(len(dev_rows), 3)
                self.assertEqual({row["question_id"] for row in dev_rows}, {"q2"})

                analysis = root / "analysis.json"
                analysis.write_text(
                    json.dumps(
                        {
                            "groups": {
                                "知识点->语用->时间->顺序|D3-1|definition_dev": {
                                    "passes_precision_first_gate": True,
                                    "unanimous_keep_precision": 1.0,
                                    "three_run_decision_agreement": 1.0,
                                    "high_confidence_false_positive_rate": 0.0,
                                    "mean_prompt_chars": 100,
                                }
                            }
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                selection = root / "selection.json"
                selected = subprocess.run(
                    [
                        sys.executable,
                        str(project / "scripts" / "select_contrastive_definition.py"),
                        "--analysis",
                        str(analysis),
                        "--definitions",
                        str(definitions),
                        "--canonical-label",
                        "知识点->语用->时间->顺序",
                        "--output",
                        str(selection),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(selected.returncode, 0, selected.stderr)
                payload = json.loads(selection.read_text(encoding="utf-8"))
                self.assertEqual(payload["definition_variant"], "D3-1")
                self.assertIn("正向必要条件", payload["definition_text"])
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
