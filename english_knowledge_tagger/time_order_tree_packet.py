"""Build a blind, stratified whole-tree packet for the time-order label."""

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


LABEL = "知识点@语用@时间@顺序"
PACKET_SCHEMA_VERSION = "time-order-tree-packet-v1"
_TYPE_METADATA = re.compile(r"(?m)^\s*题型(结构|名称)为：([^\r\n]*)")


def _rows(path: Path, *, source: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{source} line {line_number}: invalid JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"{source} line {line_number}: row must be an object")
            rows.append(row)
    return rows


def _text(row: Mapping[str, object], field: str, *, source: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: {field} must be non-empty")
    return value.strip()


def _route(input_text: str, is_child: object) -> dict[str, str]:
    values = {
        match.group(1): match.group(2).strip()
        for match in _TYPE_METADATA.finditer(input_text)
    }
    return {
        "scope": "child" if is_child is True else "parent" if is_child is False else "unknown",
        "declared_type_structure": values.get("结构") or "缺失",
        "declared_type_name": values.get("名称") or "缺失",
    }


def _rank(seed: str, question_id: str) -> str:
    return hashlib.sha256(f"{seed}:{question_id}".encode()).hexdigest()


def _pick(
    rows: list[dict[str, object]],
    *,
    count: int,
    seed: str,
    stratum: str,
    chosen: set[str],
) -> list[dict[str, object]]:
    candidates = [row for row in rows if str(row["question_id"]) not in chosen]
    ranked = sorted(candidates, key=lambda row: _rank(seed, str(row["question_id"])))
    if len(ranked) < count:
        raise ValueError(f"{stratum}: requires {count} rows but only {len(ranked)} available")
    selected = ranked[:count]
    chosen.update(str(row["question_id"]) for row in selected)
    return selected


def _stratum(route: Mapping[str, str]) -> str:
    key = (
        route.get("scope"),
        route.get("declared_type_structure"),
        route.get("declared_type_name"),
    )
    if key == ("parent", "单选题", "选择题"):
        return "parent_choice_remove"
    if key == ("parent", "单选题", "听力单选"):
        return "parent_listening_remove"
    if key == ("child", "复合题", "听力单选"):
        return "child_listening_remove"
    return "other_remove"


def _audio_status(row: Mapping[str, object], context: str) -> str:
    if row.get("contain_audio") is True or "音频" in context:
        return "audio_present"
    return "no_audio"


def build_time_order_tree_packet(
    source_path: Path,
    *,
    evidence_path: Path,
    output_path: Path,
    audit_index_path: Path,
    seed: str,
) -> dict[str, object]:
    """Select the documented 60 remove rows and 12 keep controls.

    The source is a mentor materialization and evidence is a separate blind
    human/Web-GPT review.  Their identities must match exactly, including
    ``parent_id``; no decision or historical label enters the DS-facing task.
    """

    if output_path == audit_index_path or output_path.exists() or audit_index_path.exists():
        raise FileExistsError("time-order output paths must be distinct and absent")

    source_rows = _rows(source_path, source="time-order source")
    evidence_rows = _rows(evidence_path, source="time-order evidence")
    source_by_id: dict[str, dict[str, object]] = {}
    for row in source_rows:
        if row.get("verify_label") != LABEL:
            raise ValueError("time-order source contains a different verify_label")
        question_id = _text(row, "question_id", source="time-order source")
        if question_id in source_by_id:
            raise ValueError(f"time-order source duplicate question_id {question_id!r}")
        source_by_id[question_id] = row

    evidence_by_id: dict[str, dict[str, object]] = {}
    for row in evidence_rows:
        question_id = _text(row, "question_id", source="time-order evidence")
        parent_id = _text(row, "parent_id", source="time-order evidence")
        source = source_by_id.get(question_id)
        if source is None or source.get("parent_id") != parent_id:
            raise ValueError(f"time-order evidence has unmatched identity {question_id!r}")
        decision = row.get("decision")
        if decision not in {"keep", "remove", "uncertain"}:
            raise ValueError(f"time-order evidence invalid decision for {question_id!r}")
        if question_id in evidence_by_id:
            raise ValueError(f"time-order evidence duplicate question_id {question_id!r}")
        evidence_by_id[question_id] = row

    if set(source_by_id) != set(evidence_by_id):
        raise ValueError("time-order source and evidence question IDs do not exactly match")

    prepared: list[dict[str, object]] = []
    skipped_missing_context = 0
    for question_id, source in source_by_id.items():
        raw_input = _text(source, "input", source=f"time-order source {question_id}")
        context = clean_mentor_v1_input(raw_input).strip()
        if not context:
            skipped_missing_context += 1
            continue
        route = _route(raw_input, source.get("is_sub_question"))
        prepared.append(
            {
                "question_id": question_id,
                "source": source,
                "decision": evidence_by_id[question_id]["decision"],
                "route": route,
                "context": context,
                "audio_status": _audio_status(source, context),
            }
        )

    remove = [row for row in prepared if row["decision"] == "remove"]
    keep = [row for row in prepared if row["decision"] == "keep"]
    uncertain = [row for row in prepared if row["decision"] == "uncertain"]
    if len(remove) != 60:
        raise ValueError(f"time-order evidence must contain exactly 60 remove rows, found {len(remove)}")
    if len(keep) < 12:
        raise ValueError(f"time-order evidence needs at least 12 keep rows, found {len(keep)}")

    remove_by_stratum: dict[str, list[dict[str, object]]] = {
        name: [row for row in remove if _stratum(row["route"]) == name]
        for name in (
            "parent_choice_remove",
            "parent_listening_remove",
            "child_listening_remove",
            "other_remove",
        )
    }
    required_counts = {
        "parent_choice_remove": 31,
        "parent_listening_remove": 16,
        "child_listening_remove": 8,
        "other_remove": 5,
    }
    if any(len(remove_by_stratum[name]) != count for name, count in required_counts.items()):
        actual = {name: len(rows) for name, rows in remove_by_stratum.items()}
        raise ValueError(f"time-order remove strata do not match required 31/16/8/5: {actual}")

    chosen: set[str] = set()
    selected: list[tuple[str, dict[str, object]]] = []
    for name, count in required_counts.items():
        selected.extend(
            (name, row)
            for row in _pick(
                remove_by_stratum[name],
                count=count,
                seed=seed,
                stratum=name,
                chosen=chosen,
            )
        )
    selected.extend(
        ("keep_control", row)
        for row in _pick(keep, count=12, seed=seed, stratum="keep_control", chosen=chosen)
    )
    selected.sort(key=lambda item: _rank(seed, str(item[1]["question_id"])))

    tasks: list[dict[str, object]] = []
    audits: list[dict[str, object]] = []
    for source_line, (selection_stratum, row) in enumerate(selected, 1):
        source = row["source"]
        question_id = str(row["question_id"])
        task_id = f"time-order-tree:{question_id}"
        route = row["route"]
        tasks.append(
            {
                "schema_version": TASK_SCHEMA_VERSION,
                "task_id": task_id,
                "source_line": source_line,
                "question_id": question_id,
                "parent_id": source.get("parent_id"),
                "is_sub_question": source.get("is_sub_question"),
                "route_key": route,
                "knowledge_policy": "optional",
                "allowed_knowledge_prefixes": [ROOT_PATH],
                "max_output_labels": 1,
                "question_context": row["context"],
                "trigger_kinds": ["web_gpt_audited_time_order_followup"],
                "triggers": [
                    {
                        "kind": "web_gpt_audited_time_order_followup",
                        "historical_label": "知识点->语用->时间->顺序",
                    }
                ],
            }
        )
        audits.append(
            {
                "schema_version": PACKET_SCHEMA_VERSION,
                "experiment": "order-1",
                "task_id": task_id,
                "question_id": question_id,
                "selection_stratum": selection_stratum,
                "web_gpt_decision": row["decision"],
                "route_key": route,
                "audio_status": row["audio_status"],
                "whole_image": source.get("whole_image") is True,
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    for path, rows in ((output_path, tasks), (audit_index_path, audits)):
        with path.open("x", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    return {
        "schema_version": "time-order-tree-packet-report-v1",
        "source_path": str(source_path),
        "evidence_path": str(evidence_path),
        "output_path": str(output_path),
        "audit_index_path": str(audit_index_path),
        "seed": seed,
        "source_records": len(source_rows),
        "evidence_records": len(evidence_rows),
        "prepared_records": len(prepared),
        "skipped_missing_context": skipped_missing_context,
        "uncertain_excluded": len(uncertain),
        "selected_records": len(tasks),
        "selected_by_stratum": dict(
            sorted(Counter(selection_stratum for selection_stratum, _ in selected).items())
        ),
    }
