"""Streaming repair of missing parent text context for flattened child records."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping


INDEX_SCHEMA_VERSION = "parent-context-index-v1"
REPAIR_SCHEMA_VERSION = "parent-context-repair-v1"


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _iter_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as source:
        for source_line, line in enumerate(source, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}: line {source_line} must be a JSON object")
            yield source_line, row


def render_parent_context(parent: Mapping[str, object]) -> str:
    """Render only parent text fields; labels, answers and analyses are excluded."""
    parts: list[str] = []
    stem = _text(parent.get("stem"))
    options = _text(parent.get("options"))
    if stem:
        parts.append(f"大题材料：\n{stem}")
    if options:
        parts.append(f"大题补充信息：\n{options}")
    if not parts:
        return ""
    return "父题上下文：\n" + "\n\n".join(parts)


def _create_index(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE parents (
            parent_id TEXT NOT NULL,
            question_id TEXT NOT NULL,
            source_line INTEGER NOT NULL,
            context TEXT NOT NULL,
            context_hash TEXT NOT NULL
        );
        CREATE INDEX parents_by_parent_id ON parents(parent_id);
        CREATE TABLE children (
            question_id TEXT NOT NULL,
            parent_id TEXT NOT NULL,
            source_line INTEGER NOT NULL,
            child_hash TEXT NOT NULL
        );
        CREATE INDEX children_by_identity ON children(question_id, parent_id);
        """
    )


def build_raw_index(raw_path: Path, index_path: Path) -> dict[str, object]:
    """Index raw outer parents and their nested ``sub_questions`` without RAM growth."""
    if index_path.exists():
        raise FileExistsError(f"refusing to overwrite existing raw index: {index_path}")
    index_path.parent.mkdir(parents=True, exist_ok=True)

    counters: Counter[str] = Counter()
    connection = sqlite3.connect(index_path)
    try:
        _create_index(connection)
        parent_rows: list[tuple[str, str, int, str, str]] = []
        child_rows: list[tuple[str, str, int, str]] = []
        for source_line, row in _iter_jsonl(raw_path):
            counters["outer_parent_records"] += 1
            question_id = _text(row.get("question_id"))
            parent_id = _text(row.get("parent_id")) or question_id
            if not question_id or not parent_id:
                counters["parent_identity_missing"] += 1
                continue

            context = render_parent_context(row)
            if not context:
                counters["empty_parent_context"] += 1
            parent_rows.append(
                (parent_id, question_id, source_line, context, _hash_text(context))
            )

            children = row.get("sub_questions")
            if not isinstance(children, list) or not children:
                continue
            counters["parents_with_sub_questions"] += 1
            for child in children:
                if not isinstance(child, Mapping):
                    counters["invalid_nested_child"] += 1
                    continue
                child_question_id = _text(child.get("question_id"))
                child_parent_id = _text(child.get("parent_id")) or parent_id
                if not child_question_id or not child_parent_id:
                    counters["nested_child_identity_missing"] += 1
                    continue
                child_rows.append(
                    (
                        child_question_id,
                        child_parent_id,
                        source_line,
                        _hash_text(json.dumps(child, ensure_ascii=False, sort_keys=True)),
                    )
                )
                counters["nested_child_records"] += 1

            if len(parent_rows) >= 10_000:
                connection.executemany(
                    "INSERT INTO parents VALUES (?, ?, ?, ?, ?)", parent_rows
                )
                connection.executemany(
                    "INSERT INTO children VALUES (?, ?, ?, ?)", child_rows
                )
                connection.commit()
                parent_rows.clear()
                child_rows.clear()

        if parent_rows:
            connection.executemany(
                "INSERT INTO parents VALUES (?, ?, ?, ?, ?)", parent_rows
            )
            connection.executemany(
                "INSERT INTO children VALUES (?, ?, ?, ?)", child_rows
            )
        connection.commit()
    finally:
        connection.close()

    return {
        "schema_version": INDEX_SCHEMA_VERSION,
        "raw_path": str(raw_path),
        "index_path": str(index_path),
        **dict(sorted(counters.items())),
    }


def _parent_candidates(
    cursor: sqlite3.Cursor, parent_id: str
) -> list[tuple[int, str, str]]:
    return cursor.execute(
        "SELECT source_line, context, context_hash FROM parents WHERE parent_id = ? ORDER BY source_line",
        (parent_id,),
    ).fetchall()


def _child_matches(cursor: sqlite3.Cursor, question_id: str, parent_id: str) -> list[tuple[int, str]]:
    return cursor.execute(
        "SELECT source_line, child_hash FROM children WHERE question_id = ? AND parent_id = ? ORDER BY source_line",
        (question_id, parent_id),
    ).fetchall()


def _audit_row(
    *,
    source_line: int,
    row: Mapping[str, Any],
    status: str,
    old_input_hash: str,
    new_input_hash: str,
    raw_child_source_line: int | None = None,
    parent_source_line: int | None = None,
    parent_context_hash: str | None = None,
) -> dict[str, object]:
    return {
        "schema_version": REPAIR_SCHEMA_VERSION,
        "source_line": source_line,
        "question_id": _text(row.get("question_id")) or None,
        "parent_id": _text(row.get("parent_id")) or None,
        "is_sub_question": row.get("is_sub_question"),
        "status": status,
        "raw_child_source_line": raw_child_source_line,
        "parent_source_line": parent_source_line,
        "parent_context_hash": parent_context_hash,
        "old_input_hash": old_input_hash,
        "new_input_hash": new_input_hash,
        "changed": old_input_hash != new_input_hash,
    }


def enrich_enhanced_source(
    enhanced_path: Path,
    index_path: Path,
    output_path: Path,
    audit_path: Path,
    report_path: Path,
    manifest_path: Path,
    *,
    source_sha256: str,
    raw_sha256: str,
) -> dict[str, object]:
    """Create a repaired derived JSONL and a row-level audit sidecar."""
    destinations = (output_path, audit_path, report_path, manifest_path)
    if len(set(destinations)) != len(destinations):
        raise ValueError("repair destinations must be distinct")
    existing = [str(path) for path in destinations if path.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite repair outputs: {', '.join(existing)}")
    if not index_path.exists():
        raise FileNotFoundError(f"raw index does not exist: {index_path}")

    for path in destinations:
        path.parent.mkdir(parents=True, exist_ok=True)

    status_counts: Counter[str] = Counter()
    total_records = 0
    changed_rows = 0
    connection = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True)
    try:
        cursor = connection.cursor()
        with (
            enhanced_path.open("r", encoding="utf-8") as source,
            output_path.open("x", encoding="utf-8") as output,
            audit_path.open("x", encoding="utf-8") as audit,
        ):
            for source_line, line in enumerate(source, 1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(
                        f"{enhanced_path}: line {source_line} must be a JSON object"
                    )
                total_records += 1
                input_value = row.get("input")
                old_input = input_value if isinstance(input_value, str) else ""
                old_hash = _hash_text(old_input)
                status = "not_child"
                parent_source_line = None
                raw_child_source_line = None
                parent_context_hash = None
                new_input = old_input

                if row.get("is_sub_question") is True:
                    question_id = _text(row.get("question_id"))
                    parent_id = _text(row.get("parent_id"))
                    if not question_id or not parent_id or not isinstance(input_value, str):
                        status = "identity_conflict"
                    else:
                        child_matches = _child_matches(cursor, question_id, parent_id)
                        parents = _parent_candidates(cursor, parent_id)
                        contexts = [item for item in parents if item[1]]
                        if not child_matches:
                            status = "missing_child_match"
                        elif len(child_matches) > 1:
                            status = "identity_conflict"
                        elif not contexts:
                            status = "missing_parent"
                        elif len({item[2] for item in contexts}) > 1:
                            status = "ambiguous_parent"
                        else:
                            raw_child_source_line = child_matches[0][0]
                            parent_source_line, parent_context, parent_context_hash = contexts[0]
                            body = parent_context.removeprefix("父题上下文：\n")
                            if parent_context in input_value or body in input_value:
                                status = "already_present"
                            else:
                                new_input = parent_context + "\n\n" + input_value.lstrip()
                                status = "added"

                if new_input != old_input:
                    row["input"] = new_input
                    changed_rows += 1
                new_hash = _hash_text(new_input)
                status_counts[status] += 1
                output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                audit.write(
                    json.dumps(
                        _audit_row(
                            source_line=source_line,
                            row=row,
                            status=status,
                            old_input_hash=old_hash,
                            new_input_hash=new_hash,
                            raw_child_source_line=raw_child_source_line,
                            parent_source_line=parent_source_line,
                            parent_context_hash=parent_context_hash,
                        ),
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\n"
                )
    finally:
        connection.close()

    report = {
        "schema_version": REPAIR_SCHEMA_VERSION,
        "enhanced_path": str(enhanced_path),
        "index_path": str(index_path),
        "output_path": str(output_path),
        "audit_path": str(audit_path),
        "source_sha256": source_sha256,
        "raw_sha256": raw_sha256,
        "index_schema_version": INDEX_SCHEMA_VERSION,
        "total_records": total_records,
        "changed_rows": changed_rows,
        "status_counts": dict(sorted(status_counts.items())),
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "parent-context-repair-manifest-v1",
        "repair_schema_version": REPAIR_SCHEMA_VERSION,
        "enhanced_path": str(enhanced_path),
        "raw_index_path": str(index_path),
        "output_path": str(output_path),
        "audit_path": str(audit_path),
        "report_path": str(report_path),
        "source_sha256": source_sha256,
        "raw_sha256": raw_sha256,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report
