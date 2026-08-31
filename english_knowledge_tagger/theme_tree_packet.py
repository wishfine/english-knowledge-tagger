"""Build a deterministic Theme-1 whole-tree packet from audited evidence."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Mapping

from .knowledge_taxonomy_tree import ROOT_PATH
from .knowledge_tree_tasks import TASK_SCHEMA_VERSION
from .mentor_direct_rollout import clean_mentor_v1_input


_TYPE_METADATA = re.compile(r"(?m)^题型(结构|名称)为：([^\r\n]*)")
_LABEL = "知识点@语篇主题@人与社会@互联通讯"


def _rows(path: Path, *, source: str) -> list[dict[str, object]]:
    result = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{source} line {number}: invalid JSON") from error
        if not isinstance(row, dict):
            raise ValueError(f"{source} line {number}: row must be an object")
        result.append(row)
    return result


def _text(row: Mapping[str, object], field: str, *, source: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: {field} must be non-empty")
    return value.strip()


def _route(input_text: str, is_child: object) -> dict[str, str]:
    values = {match.group(1): match.group(2).strip() for match in _TYPE_METADATA.finditer(input_text)}
    return {
        "scope": "child" if is_child is True else "parent" if is_child is False else "unknown",
        "declared_type_structure": values.get("结构") or "缺失",
        "declared_type_name": values.get("名称") or "缺失",
    }


def _rank(seed: str, question_id: str) -> str:
    return hashlib.sha256(f"{seed}:{question_id}".encode()).hexdigest()


def _pick(rows: list[dict[str, object]], *, count: int, seed: str, stratum: str, chosen: set[str]) -> list[dict[str, object]]:
    candidates = [row for row in rows if row["question_id"] not in chosen]
    ranked = sorted(candidates, key=lambda row: _rank(seed, str(row["question_id"])))
    if len(ranked) < count:
        raise ValueError(f"{stratum}: requires {count} rows but only {len(ranked)} available")
    selected = ranked[:count]
    chosen.update(str(row["question_id"]) for row in selected)
    return selected


def build_theme_tree_packet(
    source_path: Path,
    *,
    evidence_path: Path,
    output_path: Path,
    audit_index_path: Path,
    seed: str,
) -> dict[str, object]:
    """Select 60 Theme-1 tasks: 50 reviewed removes and 10 keep controls."""
    if output_path == audit_index_path or output_path.exists() or audit_index_path.exists():
        raise FileExistsError("Theme-1 output paths must be distinct and absent")
    source_rows = _rows(source_path, source="Theme source")
    evidence_rows = _rows(evidence_path, source="Theme evidence")
    source_by_id: dict[str, dict[str, object]] = {}
    for row in source_rows:
        if row.get("verify_label") != _LABEL:
            raise ValueError("Theme source contains a different verify_label")
        question_id = _text(row, "question_id", source="Theme source")
        if question_id in source_by_id:
            raise ValueError(f"Theme source duplicate question_id {question_id!r}")
        source_by_id[question_id] = row
    evidence_by_id: dict[str, dict[str, object]] = {}
    for row in evidence_rows:
        question_id = _text(row, "question_id", source="Theme evidence")
        parent_id = _text(row, "parent_id", source="Theme evidence")
        if question_id not in source_by_id or source_by_id[question_id].get("parent_id") != parent_id:
            raise ValueError(f"Theme evidence has unmatched identity {question_id!r}")
        if row.get("decision") not in {"keep", "remove", "uncertain"}:
            raise ValueError(f"Theme evidence invalid decision for {question_id!r}")
        if question_id in evidence_by_id:
            raise ValueError(f"Theme evidence duplicate question_id {question_id!r}")
        evidence_by_id[question_id] = row
    if set(source_by_id) != set(evidence_by_id):
        raise ValueError("Theme source and evidence question IDs do not exactly match")

    prepared = []
    for question_id, source in source_by_id.items():
        input_text = _text(source, "input", source=f"Theme source {question_id}")
        context = clean_mentor_v1_input(input_text).strip()
        if not context:
            continue
        prepared.append({"question_id": question_id, "source": source, "decision": evidence_by_id[question_id]["decision"], "route": _route(input_text, source.get("is_sub_question")), "context": context})

    remove = [row for row in prepared if row["decision"] == "remove"]
    keep = [row for row in prepared if row["decision"] == "keep"]
    main = [row for row in remove if row["route"] == {"scope": "parent", "declared_type_structure": "复合题", "declared_type_name": "阅读理解"}]
    other_reading = [row for row in remove if row not in main and "阅读" in row["route"]["declared_type_name"]]
    other = [row for row in remove if row not in main and row not in other_reading]
    chosen: set[str] = set()
    selected = [("main_reading_remove", row) for row in _pick(main, count=30, seed=seed, stratum="main_reading_remove", chosen=chosen)]
    selected += [("other_reading_remove", row) for row in _pick(other_reading, count=10, seed=seed, stratum="other_reading_remove", chosen=chosen)]
    selected += [("other_remove", row) for row in _pick(other, count=10, seed=seed, stratum="other_remove", chosen=chosen)]
    selected += [("keep_control", row) for row in _pick(keep, count=10, seed=seed, stratum="keep_control", chosen=chosen)]
    selected.sort(key=lambda item: _rank(seed, str(item[1]["question_id"])))

    tasks = []
    audit = []
    for source_line, (stratum, row) in enumerate(selected, 1):
        source = row["source"]
        task_id = f"theme-tree:{row['question_id']}"
        tasks.append({
            "schema_version": TASK_SCHEMA_VERSION,
            "task_id": task_id,
            "source_line": source_line,
            "question_id": row["question_id"],
            "parent_id": source.get("parent_id"),
            "is_sub_question": source.get("is_sub_question"),
            "route_key": row["route"],
            "knowledge_policy": "optional",
            "allowed_knowledge_prefixes": [ROOT_PATH],
            "max_output_labels": 1,
            "question_context": row["context"],
            "trigger_kinds": ["web_gpt_audited_theme_followup"],
            "triggers": [{"kind": "web_gpt_audited_theme_followup", "historical_label": "知识点->语篇主题->人与社会->互联通讯"}],
        })
        audit.append({"schema_version": "audited-theme-tree-index-v1", "experiment": "theme-1", "task_id": task_id, "question_id": row["question_id"], "selection_stratum": stratum, "web_gpt_decision": row["decision"], "route_key": row["route"]})
    output_path.parent.mkdir(parents=True, exist_ok=True)
    for path, rows in ((output_path, tasks), (audit_index_path, audit)):
        with path.open("x", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {"schema_version": "theme-tree-packet-report-v1", "source_path": str(source_path), "evidence_path": str(evidence_path), "selected_records": len(tasks), "selected_by_stratum": dict(sorted(Counter(stratum for stratum, _ in selected).items())), "output_path": str(output_path), "audit_index_path": str(audit_index_path), "seed": seed}
