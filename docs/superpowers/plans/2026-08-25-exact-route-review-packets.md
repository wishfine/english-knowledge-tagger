# Exact Route Review Packet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow every data-cleaning and tree-routing experiment to draw a stable blind sample from one exact `scope × 题型结构 × 题型名称` route.

**Architecture:** Extend the existing streaming type-review sampler with an optional exact target key. It preserves the existing all-route behavior when no target is supplied; when supplied, only matching records are retained in its bounded stable sample and the report declares the target and match count. The CLI requires all three route fields together to prevent an accidental broad partial match.

**Tech Stack:** Python 3 standard library, JSONL, `unittest`.

## Global Constraints

- Matching remains exact; no name substring, wildcard or parent-label fallback is permitted.
- Default output remains blind and hides legacy labels.
- Sampling is deterministic for a fixed source, route and `per_route`.
- Existing all-route commands and output schema remain backward compatible.
- Source JSONL stays read-only and output refuses overwrite.

---

### Task 1: Add an exact route filter to the sampler

**Files:**

- Modify: `english_knowledge_tagger/type_review_packet.py`
- Test: `tests/test_type_review_packet.py`

**Interfaces:**

```python
RouteKey = tuple[str, str, str]

def build_type_review_packet(
    input_path: Path, *, output_path: Path, per_route: int = 5,
    include_legacy_labels: bool = False, target_route: RouteKey | None = None,
) -> dict[str, Any]: ...
```

When `target_route` is supplied, report `target_route` as an object, `matched_records`, `route_groups=1` if non-empty, and only write rows whose route key equals it.

- [x] **Step 1: Write the failing filter test**

```python
report = build_type_review_packet(source, output_path=packet, per_route=2,
                                  target_route=("child", "复合题", "语法选择"))
rows = read_jsonl(packet)
self.assertEqual(report["matched_records"], 2)
self.assertEqual({tuple(row["route_key"].values()) for row in rows}, {("child", "复合题", "语法选择")})
```

- [x] **Step 2: Verify red**

Run: `.venv/bin/python -m pytest tests/test_type_review_packet.py -v`

Expected: FAIL because `target_route` is not an accepted argument.

- [x] **Step 3: Implement exact filtering and report fields**

```python
if target_route is not None and key != target_route:
    continue
if target_route is not None:
    report["target_route"] = {"scope": target_route[0], ...}
    report["matched_records"] = route_counts[_route_key_text(target_route)]
```

- [x] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_type_review_packet.py -v`

Expected: PASS.

### Task 2: Expose exact-route invocation and document the pipeline stage

**Files:**

- Modify: `scripts/sample_type_review_packet.py`
- Modify: `docs/type-policy-mapping.md`
- Modify: `docs/superpowers/plans/2026-08-25-exact-route-review-packets.md`
- Test: `tests/test_type_review_packet.py`

**Interfaces:** CLI accepts all-or-none `--scope`, `--declared-type-structure`, `--declared-type-name`; a partial key is a parser error. Documentation gives the grammar-selection route command and says to freeze its packet before flat/tree ablations.

- [x] **Step 1: Write the failing CLI test**

```python
completed = subprocess.run([... , "--scope", "child"], capture_output=True, text=True)
self.assertNotEqual(completed.returncode, 0)
self.assertIn("must be supplied together", completed.stderr)
```

- [x] **Step 2: Verify red**

Run: `.venv/bin/python -m pytest tests/test_type_review_packet.py -v`

Expected: FAIL because the CLI treats route arguments as unknown.

- [x] **Step 3: Implement CLI validation and documentation**

```python
route_values = (args.scope, args.declared_type_structure, args.declared_type_name)
if any(route_values) and not all(route_values):
    parser.error("--scope, --declared-type-structure and --declared-type-name must be supplied together")
target_route = tuple(route_values) if all(route_values) else None
```

- [x] **Step 4: Verify repository and push**

Run: `.venv/bin/python -m pytest -q`

Expected: PASS.

```bash
git add english_knowledge_tagger/type_review_packet.py scripts/sample_type_review_packet.py tests/test_type_review_packet.py docs/type-policy-mapping.md docs/superpowers/plans/2026-08-25-exact-route-review-packets.md
git commit -m "feat: sample exact question type routes"
git push origin HEAD:main
```
