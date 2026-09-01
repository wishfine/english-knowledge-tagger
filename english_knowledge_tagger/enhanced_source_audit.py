"""Streaming profile and stratified sampling for the enhanced SFT source."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Callable, Mapping

from .sft_labels import parse_sft_output_labels


SCHEMA_VERSION = "enhanced-source-audit-v1"
MISSING = "__MISSING__"
_TYPE_STRUCTURE = re.compile(r"(?m)^\s*题型结构为：([^\r\n]*)")
_TYPE_NAME = re.compile(r"(?m)^\s*题型名称为：([^\r\n]*)")
_SECTION_PREFIXES = (
    "题目题干：",
    "当前小题题干：",
    "题目选项：",
    "当前小题选项：",
    "题目解析：",
    "当前小题解析：",
    "题目答案：",
    "当前小题答案：",
    "小题序号：",
    "根据以上信息，当前题目所属的题型方法类目和知识点类目为：",
)
_HEADER_PREFIXES = (
    "题型结构为：",
    "题型名称为：",
    "所给图片为题目题干",
    "本题题干中包含音频内容",
    "题目题干中包含音频内容",
    "音频片段时长",
)


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _scope(row: Mapping[str, Any]) -> str:
    if row.get("is_sub_question") is True:
        return "child"
    if row.get("is_sub_question") is False:
        return "parent"
    return "unknown"


def _declared(pattern: re.Pattern[str], value: object) -> str:
    if not isinstance(value, str):
        return MISSING
    match = pattern.search(value)
    if match is None:
        return MISSING
    return match.group(1).strip() or MISSING


def _section_has_content(value: object, prefixes: tuple[str, ...]) -> bool:
    if not isinstance(value, str):
        return False
    lines = value.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not any(stripped.startswith(prefix) for prefix in prefixes):
            continue
        tail = stripped.split("：", 1)[1].strip() if "：" in stripped else ""
        if tail:
            return True
        for next_line in lines[index + 1 :]:
            next_stripped = next_line.strip()
            if not next_stripped:
                continue
            if next_stripped.startswith(_SECTION_PREFIXES):
                break
            if next_stripped.startswith(_HEADER_PREFIXES):
                continue
            return True
    return False


def _content_shape(row: Mapping[str, Any], input_text: str) -> str:
    if not input_text.strip():
        return "empty_input"

    scope = _scope(row)
    has_stem = _section_has_content(input_text, ("题目题干：", "当前小题题干："))
    has_options = _section_has_content(input_text, ("题目选项：", "当前小题选项："))
    has_analysis = _section_has_content(input_text, ("题目解析：", "当前小题解析："))
    has_answer = _section_has_content(input_text, ("题目答案：", "当前小题答案："))

    if scope == "parent":
        if not has_stem:
            return "parent_shell_no_stem"
        stem_line = next(
            (
                line.strip().split("：", 1)[1].strip()
                for line in input_text.splitlines()
                if line.strip().startswith("题目题干：") and "：" in line
            ),
            "",
        )
        if len(stem_line) <= 120 and not (has_options or has_analysis or has_answer):
            return "parent_shell_compact"
        return "parent_with_material"
    if scope == "child":
        if has_stem:
            return "child_with_stem"
        if has_options or has_analysis or has_answer:
            return "child_without_stem"
        return "child_empty"
    return "unknown_shape"


def _modality(row: Mapping[str, Any], input_text: str) -> str:
    audio = row.get("contain_audio") is True or "音频" in input_text
    image_value = row.get("images")
    image = (
        row.get("whole_image") is True
        or (isinstance(image_value, list) and bool(image_value))
        or "图片" in input_text
    )
    if audio and image:
        return "audio_image"
    if audio:
        return "audio"
    if image:
        return "image"
    return "text"


def _label_counts(row: Mapping[str, Any]) -> tuple[int, int]:
    parsed = parse_sft_output_labels(row.get("output"))
    if parsed is None:
        return 0, 0
    knowledge, question_types = parsed
    return len(knowledge), len(question_types)


def _identity(row: Mapping[str, Any]) -> tuple[str, str, str] | None:
    question_id = _text(row.get("question_id"))
    parent_id = _text(row.get("parent_id"))
    if not question_id or not parent_id or not isinstance(row.get("is_sub_question"), bool):
        return None
    return question_id, parent_id, "child" if row["is_sub_question"] else "parent"


def _sample_rank(seed: str, sample_kind: str, bucket: tuple[str, ...], source_line: int) -> int:
    value = "\x1f".join((seed, sample_kind, *bucket, str(source_line))).encode("utf-8")
    return int.from_bytes(hashlib.sha256(value).digest()[:8], "big")


def _offer_sample(
    samples: dict[tuple[str, tuple[str, ...]], list[tuple[int, dict[str, Any]]]],
    *,
    seed: str,
    sample_kind: str,
    bucket: tuple[str, ...],
    source_line: int,
    sample: dict[str, Any],
    limit: int,
) -> None:
    key = (sample_kind, bucket)
    values = samples.setdefault(key, [])
    ranked = (_sample_rank(seed, sample_kind, bucket, source_line), sample)
    values.append(ranked)
    values.sort(key=lambda item: item[0])
    del values[limit:]


def _create_index(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE identities (
            identity TEXT PRIMARY KEY,
            source_line INTEGER NOT NULL
        );
        CREATE TABLE parent_ids (
            parent_id TEXT PRIMARY KEY
        );
        CREATE TABLE child_parent_refs (
            source_line INTEGER NOT NULL,
            parent_id TEXT NOT NULL
        );
        """
    )


def profile_enhanced_source(
    source_path: Path,
    *,
    index_path: Path,
    sample_output_path: Path,
    sample_per_bucket: int = 3,
    seed: str = "enhanced-source-audit-v1",
    progress_every: int | None = None,
    progress_callback: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    """Profile all valid rows and write deterministic type/shape samples."""
    if sample_per_bucket <= 0:
        raise ValueError("sample_per_bucket must be positive")
    if not seed.strip():
        raise ValueError("seed must be non-empty")
    if progress_every is not None and progress_every <= 0:
        raise ValueError("progress_every must be positive when provided")
    if index_path.exists() or sample_output_path.exists():
        raise FileExistsError("refusing to overwrite audit index or sample output")
    index_path.parent.mkdir(parents=True, exist_ok=True)
    sample_output_path.parent.mkdir(parents=True, exist_ok=True)

    source_digest = hashlib.sha256()
    scope_counts: Counter[str] = Counter()
    content_shape_counts: Counter[str] = Counter()
    modality_counts: Counter[str] = Counter()
    input_presence_counts: Counter[str] = Counter()
    knowledge_cardinality: Counter[int] = Counter()
    type_cardinality: Counter[int] = Counter()
    type_buckets: dict[tuple[str, str, str], dict[str, Any]] = {}
    shape_buckets: dict[tuple[str, str, str, str], int] = Counter()
    samples: dict[tuple[str, tuple[str, ...]], list[tuple[int, dict[str, Any]]]] = {}
    valid_records = 0
    invalid_json_lines = 0
    non_object_lines = 0
    missing_identity = 0
    duplicate_identity = 0

    connection = sqlite3.connect(index_path)
    try:
        _create_index(connection)
        identity_rows: list[tuple[str, int]] = []
        parent_rows: list[tuple[str]] = []
        child_rows: list[tuple[int, str]] = []

        with source_path.open("rb") as source:
            for source_line, raw_line in enumerate(source, 1):
                source_digest.update(raw_line)
                if not raw_line.strip():
                    continue
                try:
                    row = json.loads(raw_line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    invalid_json_lines += 1
                    continue
                if not isinstance(row, dict):
                    non_object_lines += 1
                    continue

                valid_records += 1
                if (
                    progress_callback is not None
                    and progress_every is not None
                    and valid_records % progress_every == 0
                ):
                    progress_callback(valid_records)
                scope = _scope(row)
                input_text = _text(row.get("input"))
                structure = _declared(_TYPE_STRUCTURE, input_text)
                name = _declared(_TYPE_NAME, input_text)
                shape = _content_shape(row, input_text)
                modality = _modality(row, input_text)
                knowledge_count, type_count = _label_counts(row)

                scope_counts[scope] += 1
                content_shape_counts[shape] += 1
                modality_counts[modality] += 1
                knowledge_cardinality[knowledge_count] += 1
                type_cardinality[type_count] += 1
                input_presence_counts["has_stem"] += int(
                    _section_has_content(input_text, ("题目题干：", "当前小题题干："))
                )
                input_presence_counts["has_options"] += int(
                    _section_has_content(input_text, ("题目选项：", "当前小题选项："))
                )
                input_presence_counts["has_analysis"] += int(
                    _section_has_content(input_text, ("题目解析：", "当前小题解析："))
                )
                input_presence_counts["has_answer"] += int(
                    _section_has_content(input_text, ("题目答案：", "当前小题答案："))
                )

                type_key = (scope, structure, name)
                type_bucket = type_buckets.setdefault(
                    type_key,
                    {
                        "scope": scope,
                        "declared_type_structure": structure,
                        "declared_type_name": name,
                        "record_count": 0,
                        "content_shapes": Counter(),
                        "modalities": Counter(),
                        "knowledge_cardinality": Counter(),
                        "type_cardinality": Counter(),
                    },
                )
                type_bucket["record_count"] += 1
                type_bucket["content_shapes"][shape] += 1
                type_bucket["modalities"][modality] += 1
                type_bucket["knowledge_cardinality"][knowledge_count] += 1
                type_bucket["type_cardinality"][type_count] += 1
                shape_buckets[(scope, shape, modality, str(knowledge_count))] += 1

                identity = _identity(row)
                if identity is None:
                    missing_identity += 1
                else:
                    identity_key = json.dumps(identity, ensure_ascii=False, separators=(",", ":"))
                    identity_rows.append((identity_key, source_line))
                    if scope == "parent":
                        parent_rows.append((identity[1],))
                    elif scope == "child":
                        child_rows.append((source_line, identity[1]))
                sample = {
                    "source_line": source_line,
                    "question_id": row.get("question_id"),
                    "parent_id": row.get("parent_id"),
                    "is_sub_question": row.get("is_sub_question"),
                    "declared_type_structure": structure,
                    "declared_type_name": name,
                    "content_shape": shape,
                    "modality": modality,
                    "knowledge_label_count": knowledge_count,
                    "type_label_count": type_count,
                    "contain_audio": row.get("contain_audio"),
                    "whole_image": row.get("whole_image"),
                    "images": row.get("images"),
                    "input": row.get("input"),
                    "output": row.get("output"),
                }
                _offer_sample(
                    samples,
                    seed=seed,
                    sample_kind="type",
                    bucket=type_key,
                    source_line=source_line,
                    sample=sample,
                    limit=sample_per_bucket,
                )
                _offer_sample(
                    samples,
                    seed=seed,
                    sample_kind="shape",
                    bucket=(scope, shape, modality, str(knowledge_count)),
                    source_line=source_line,
                    sample=sample,
                    limit=sample_per_bucket,
                )

                if len(identity_rows) >= 20_000:
                    before = connection.total_changes
                    connection.executemany(
                        "INSERT OR IGNORE INTO identities VALUES (?, ?)", identity_rows
                    )
                    duplicate_identity += len(identity_rows) - (connection.total_changes - before)
                    connection.executemany(
                        "INSERT OR IGNORE INTO parent_ids VALUES (?)", parent_rows
                    )
                    connection.executemany(
                        "INSERT INTO child_parent_refs VALUES (?, ?)", child_rows
                    )
                    connection.commit()
                    identity_rows.clear()
                    parent_rows.clear()
                    child_rows.clear()

        if identity_rows:
            before = connection.total_changes
            connection.executemany("INSERT OR IGNORE INTO identities VALUES (?, ?)", identity_rows)
            duplicate_identity += len(identity_rows) - (connection.total_changes - before)
            connection.executemany("INSERT OR IGNORE INTO parent_ids VALUES (?)", parent_rows)
            connection.executemany("INSERT INTO child_parent_refs VALUES (?, ?)", child_rows)
        connection.commit()
        orphan_children = connection.execute(
            "SELECT COUNT(*) FROM child_parent_refs c LEFT JOIN parent_ids p ON p.parent_id = c.parent_id WHERE p.parent_id IS NULL"
        ).fetchone()[0]
    finally:
        connection.close()

    sample_rows: list[dict[str, Any]] = []
    for (sample_kind, bucket), ranked in sorted(samples.items(), key=lambda item: (item[0][0], item[0][1])):
        for rank, sample in ranked:
            sample_rows.append(
                {
                    "sample_kind": sample_kind,
                    "bucket": list(bucket),
                    "sample_rank": rank,
                    **sample,
                }
            )
    with sample_output_path.open("x", encoding="utf-8") as output:
        for row in sample_rows:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    def sorted_counts(counter: Counter[Any]) -> dict[str, int]:
        return {str(key): counter[key] for key in sorted(counter, key=lambda value: str(value))}

    type_rows = []
    for key in sorted(type_buckets):
        value = type_buckets[key]
        type_rows.append(
            {
                "scope": value["scope"],
                "declared_type_structure": value["declared_type_structure"],
                "declared_type_name": value["declared_type_name"],
                "record_count": value["record_count"],
                "content_shapes": sorted_counts(value["content_shapes"]),
                "modalities": sorted_counts(value["modalities"]),
                "knowledge_cardinality": sorted_counts(value["knowledge_cardinality"]),
                "type_cardinality": sorted_counts(value["type_cardinality"]),
            }
        )

    report = {
        "schema_version": SCHEMA_VERSION,
        "source_path": str(source_path),
        "source_sha256": source_digest.hexdigest(),
        "index_path": str(index_path),
        "sample_output_path": str(sample_output_path),
        "sample_per_bucket": sample_per_bucket,
        "seed": seed,
        "sampled_records": valid_records,
        "valid_records": valid_records,
        "invalid_json_lines": invalid_json_lines,
        "non_object_lines": non_object_lines,
        "scope_counts": {scope: scope_counts[scope] for scope in ("parent", "child", "unknown")},
        "content_shape_counts": sorted_counts(content_shape_counts),
        "modality_counts": sorted_counts(modality_counts),
        "input_presence_counts": sorted_counts(input_presence_counts),
        "knowledge_cardinality": sorted_counts(knowledge_cardinality),
        "type_cardinality": sorted_counts(type_cardinality),
        "missing_identity_count": missing_identity,
        "duplicate_identity_count": duplicate_identity,
        "orphan_child_parent_count": orphan_children,
        "type_bucket_count": len(type_buckets),
        "shape_bucket_count": len(shape_buckets),
        "type_buckets": type_rows,
    }
    return report
