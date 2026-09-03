"""Sample independent blind post-sweep review packets from final evidence."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable, Mapping


POST_SWEEP_SCHEMA_VERSION = "final-label-post-sweep-review-packet-v1"
POST_SWEEP_REPORT_SCHEMA_VERSION = "final-label-post-sweep-report-v1"
_REMOVED_LINE_PREFIXES = (
    "题型结构为：",
    "题型名称为：",
    "所给图片为题目题干",
    "根据以上信息，当前题目所属的题型方法类目和知识点类目为：",
)


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _identity(row: Mapping[str, object]) -> tuple[str, str, int] | None:
    question_id = _text(row.get("question_id"))
    parent_id = _text(row.get("parent_id"))
    is_sub_question = row.get("is_sub_question")
    if question_id is None or parent_id is None or not isinstance(is_sub_question, bool):
        return None
    return question_id, parent_id, int(is_sub_question)


def _clean_question_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    lines = [
        line for line in value.splitlines()
        if not line.strip().startswith(_REMOVED_LINE_PREFIXES)
    ]
    cleaned = "\n".join(lines).strip()
    return cleaned or None


def _load_excluded_ids(path: Path | None) -> dict[str, set[str]]:
    excluded: dict[str, set[str]] = defaultdict(set)
    if path is None:
        return excluded
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"exclude JSONL line {line_number}: invalid JSON") from error
            if not isinstance(row, Mapping):
                raise ValueError(f"exclude JSONL line {line_number}: row must be an object")
            label = _text(row.get("verify_label", row.get("legacy_label")))
            question_id = _text(row.get("question_id"))
            if label is not None and question_id is not None:
                excluded[label].add(question_id)
    return excluded


def _slug(index: int, canonical_label: str) -> str:
    return f"{index:03d}-{hashlib.sha256(canonical_label.encode('utf-8')).hexdigest()[:12]}"


def build_final_post_sweep_packets(
    *,
    snapshot_db: Path,
    source_path: Path,
    output_dir: Path,
    exclude_jsonl_path: Path | None,
    sample_size: int = 60,
    seed: str,
    excluded_labels: Iterable[str] = (),
) -> dict[str, object]:
    """Sample positive evidence per label and materialize blind source-backed packets."""
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing post-sweep directory: {output_dir}")
    if not snapshot_db.is_file() or not source_path.is_file():
        raise FileNotFoundError("snapshot_db and source_path must exist")
    if not isinstance(sample_size, int) or isinstance(sample_size, bool) or sample_size <= 0:
        raise ValueError("sample_size must be a positive integer")
    if not isinstance(seed, str) or not seed:
        raise ValueError("seed must be non-empty")

    excluded_raw = frozenset(label.strip() for label in excluded_labels if label.strip())
    excluded_ids = _load_excluded_ids(exclude_jsonl_path)
    connection = sqlite3.connect(snapshot_db)
    try:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(evidence)").fetchall()
        }
        required_columns = {
            "question_id", "parent_id", "is_sub_question", "canonical_label",
            "legacy_label", "status", "llm_match", "confidence", "review_id",
        }
        missing_columns = sorted(required_columns - columns)
        if missing_columns:
            raise ValueError("snapshot evidence table missing columns: " + ", ".join(missing_columns))
        evidence_rows = connection.execute(
            """
            SELECT question_id, parent_id, is_sub_question, canonical_label,
                   legacy_label, status, llm_match, confidence, review_id
            FROM evidence
            WHERE status = 'candidate' AND llm_match = 1
            """
        ).fetchall()
    finally:
        connection.close()

    by_label: dict[str, list[dict[str, object]]] = defaultdict(list)
    seen_review_ids: set[str] = set()
    for values in evidence_rows:
        (
            question_id, parent_id, is_sub_question, canonical_label,
            legacy_label, status, llm_match, confidence, review_id,
        ) = values
        if not all(isinstance(value, str) and value.strip() for value in (question_id, parent_id, canonical_label, legacy_label, review_id)):
            raise ValueError("snapshot contains positive evidence with invalid identity or labels")
        if is_sub_question not in (0, 1):
            raise ValueError("snapshot evidence is_sub_question must be 0 or 1")
        if review_id in seen_review_ids:
            raise ValueError(f"duplicate positive evidence review_id: {review_id}")
        seen_review_ids.add(review_id)
        if legacy_label in excluded_raw or canonical_label in excluded_raw:
            continue
        if question_id in excluded_ids.get(legacy_label, set()):
            continue
        by_label[legacy_label].append({
            "question_id": question_id,
            "parent_id": parent_id,
            "is_sub_question": bool(is_sub_question),
            "canonical_label": canonical_label,
            "legacy_label": legacy_label,
            "review_id": review_id,
            "confidence": confidence,
        })

    selected_by_identity: dict[tuple[str, str, int], list[dict[str, object]]] = defaultdict(list)
    label_stats: dict[str, dict[str, object]] = {}
    for index, label in enumerate(sorted(by_label), 1):
        candidates = sorted(
            by_label[label],
            key=lambda row: hashlib.sha256(
                f"{seed}\0{row['review_id']}".encode("utf-8")
            ).hexdigest(),
        )
        selected = candidates[:sample_size]
        for item in selected:
            identity = (item["question_id"], item["parent_id"], int(item["is_sub_question"]))
            selected_by_identity[identity].append(item)
        label_stats[label] = {
            "canonical_label": selected[0]["canonical_label"] if selected else by_label[label][0]["canonical_label"],
            "positive_records_after_exclusion": len(candidates),
            "selected_records": len(selected),
            "selected_review_ids": [item["review_id"] for item in selected],
            "packet_slug": _slug(index, str(label)),
            "emitted_records": 0,
        }

    output_dir.mkdir(parents=True)
    packets_dir = output_dir / "packets"
    packets_dir.mkdir()
    writers: dict[str, Any] = {}
    for label, details in label_stats.items():
        writers[label] = (packets_dir / f"{details['packet_slug']}.review.jsonl").open(
            "x", encoding="utf-8"
        )

    found: set[tuple[str, str, int]] = set()
    source_records = 0
    source_hasher = hashlib.sha256()
    try:
        with source_path.open("rb") as source:
            for source_line, raw_line in enumerate(source, 1):
                source_hasher.update(raw_line)
                if not raw_line.strip():
                    continue
                source_records += 1
                try:
                    row = json.loads(raw_line)
                except json.JSONDecodeError as error:
                    raise ValueError(f"source line {source_line}: invalid JSON") from error
                if not isinstance(row, Mapping):
                    raise ValueError(f"source line {source_line}: row must be an object")
                identity = _identity(row)
                if identity is None:
                    continue
                selected_items = selected_by_identity.get(identity)
                if not selected_items:
                    continue
                question_text = _clean_question_text(row.get("input"))
                if question_text is None:
                    continue
                found.add(identity)
                for item in selected_items:
                    label = str(item["legacy_label"])
                    writers[label].write(json.dumps({
                        "schema_version": POST_SWEEP_SCHEMA_VERSION,
                        "review_id": item["review_id"],
                        "question_id": identity[0],
                        "parent_id": identity[1],
                        "is_sub_question": bool(identity[2]),
                        "verify_label": label,
                        "canonical_label": item["canonical_label"],
                        "source_line": source_line,
                        "question_text": question_text,
                    }, ensure_ascii=False, sort_keys=True) + "\n")
                    label_stats[label]["emitted_records"] = int(label_stats[label]["emitted_records"]) + 1
    finally:
        for handle in writers.values():
            handle.close()

    missing_selected = []
    for label, details in label_stats.items():
        selected_count = int(details["selected_records"])
        emitted_count = int(details["emitted_records"])
        if emitted_count != selected_count:
            missing_selected.append({
                "label": label,
                "selected_records": selected_count,
                "emitted_records": emitted_count,
            })
        details["packet_path"] = str(packets_dir / f"{details['packet_slug']}.review.jsonl")

    report = {
        "schema_version": POST_SWEEP_REPORT_SCHEMA_VERSION,
        "purpose": "independent_post_sweep_label_audit",
        "snapshot_db": str(snapshot_db),
        "source_path": str(source_path),
        "source_sha256": source_hasher.hexdigest(),
        "exclude_jsonl_path": str(exclude_jsonl_path) if exclude_jsonl_path else None,
        "excluded_labels": sorted(excluded_raw),
        "sample_size": sample_size,
        "seed": seed,
        "source_records": source_records,
        "positive_evidence_records_scanned": len(evidence_rows),
        "labels": len(label_stats),
        "total_selected_records": sum(int(item["selected_records"]) for item in label_stats.values()),
        "total_emitted_records": sum(int(item["emitted_records"]) for item in label_stats.values()),
        "labels_with_fewer_than_requested": sum(
            int(item["positive_records_after_exclusion"]) < sample_size
            for item in label_stats.values()
        ),
        "missing_selected_records": missing_selected,
        "label_stats": label_stats,
        "outputs": {
            "packets_dir": str(packets_dir),
            "report": str(output_dir / "report.json"),
        },
    }
    (output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report
