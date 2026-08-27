"""Build read-only whole-taxonomy tree tasks from mentor direct-verification rows."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
from typing import Mapping

from .knowledge_taxonomy_tree import ROOT_PATH
from .knowledge_tree_tasks import TASK_SCHEMA_VERSION
from .mentor_direct_rollout import clean_mentor_v1_input


HOLD_SCHEMA_VERSION = "mentor-tree-correction-hold-v1"
_TYPE_METADATA = re.compile(r"(?m)^题型(结构|名称)为：([^\r\n]*)")


def _string(value: object, *, field: str, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: {field} must be a non-empty string")
    return value.strip()


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _canonical_path(rendered_label: str) -> str:
    return "知识点->" + rendered_label.removeprefix("知识点@").replace("@", "->")


def _route_key(input_text: str, is_sub_question: object) -> dict[str, str]:
    metadata = {match.group(1): match.group(2).strip() for match in _TYPE_METADATA.finditer(input_text)}
    scope = "child" if is_sub_question is True else "parent" if is_sub_question is False else "unknown"
    return {
        "scope": scope,
        "declared_type_structure": metadata.get("结构") or "缺失",
        "declared_type_name": metadata.get("名称") or "缺失",
    }


def _route_name(route: Mapping[str, str]) -> str:
    return " × ".join(
        (
            route["scope"],
            route["declared_type_structure"],
            route["declared_type_name"],
        )
    )


def _is_knowledge_label(value: str | None) -> bool:
    return value is not None and value.startswith("知识点@")


def _task_identifier(question_id: str | None, source_line: int) -> str:
    return f"mentor-tree:{question_id or 'line'}:{source_line}"


def build_mentor_tree_correction_tasks(
    verification_path: Path,
    *,
    verify_label: str,
    output_path: Path,
    hold_output_path: Path,
) -> dict[str, object]:
    """Partition one exact mentor label's direct verdicts into tree tasks and holds.

    ``llm_should_be`` remains untrusted model evidence. It may determine whether a
    false result has enough structural information to enter tree search, but never
    becomes a replacement label in this step.
    """
    requested_label = _string(verify_label, field="verify_label", source="tree correction builder")
    if output_path == hold_output_path:
        raise ValueError("tree task and hold output paths must differ")
    if output_path.exists() or hold_output_path.exists():
        raise FileExistsError("refusing to overwrite existing mentor tree task or hold output")

    tasks: list[dict[str, object]] = []
    holds: list[dict[str, object]] = []
    counts: Counter[str] = Counter()
    route_counts: Counter[str] = Counter()

    with verification_path.open("r", encoding="utf-8") as source:
        for source_line, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"mentor verification line {source_line}: invalid JSON") from error
            if not isinstance(row, Mapping):
                raise ValueError(f"mentor verification line {source_line}: JSONL row must be an object")
            row_source = f"mentor verification line {source_line}"
            if _string(row.get("verify_label"), field="verify_label", source=row_source) != requested_label:
                raise ValueError(f"{row_source}: verify_label differs from requested label")
            direct_match = row.get("llm_match")
            if not isinstance(direct_match, bool):
                raise ValueError(f"{row_source}: llm_match must be boolean")

            input_text = _string(row.get("input"), field="input", source=row_source)
            cleaned_context = clean_mentor_v1_input(input_text).strip()
            question_id = _optional_string(row.get("question_id"))
            parent_id = _optional_string(row.get("parent_id"))
            route = _route_key(input_text, row.get("is_sub_question"))
            route_counts[_route_name(route)] += 1
            direct_should_be = _optional_string(row.get("llm_should_be"))
            direct_reason = _optional_string(row.get("llm_reason"))
            source_output_all = _optional_string(row.get("output_all"))

            common = {
                "source_line": source_line,
                "question_id": question_id,
                "parent_id": parent_id,
                "is_sub_question": row.get("is_sub_question"),
                "route_key": route,
                "verify_label": requested_label,
                "historical_label": _canonical_path(requested_label),
                "direct_match": direct_match,
                "direct_should_be": direct_should_be,
                "direct_reason": direct_reason,
                "source_output_all": source_output_all,
            }
            if not cleaned_context:
                holds.append(
                    {
                        "schema_version": HOLD_SCHEMA_VERSION,
                        **common,
                        "hold_reason": "missing_question_context",
                    }
                )
                counts["missing_question_context"] += 1
                continue

            if direct_match:
                trigger_kind = "direct_match_recheck"
            elif direct_should_be == "正确":
                holds.append(
                    {
                        "schema_version": HOLD_SCHEMA_VERSION,
                        **common,
                        "hold_reason": "direct_contract_conflict",
                        "question_context": cleaned_context,
                    }
                )
                counts["direct_contract_conflict"] += 1
                continue
            elif not _is_knowledge_label(direct_should_be):
                holds.append(
                    {
                        "schema_version": HOLD_SCHEMA_VERSION,
                        **common,
                        "hold_reason": "direct_insufficient",
                        "question_context": cleaned_context,
                    }
                )
                counts["direct_insufficient"] += 1
                continue
            else:
                trigger_kind = "direct_mismatch"

            tasks.append(
                {
                    "schema_version": TASK_SCHEMA_VERSION,
                    "task_id": _task_identifier(question_id, source_line),
                    **common,
                    "knowledge_policy": "optional",
                    "allowed_knowledge_prefixes": [ROOT_PATH],
                    "max_output_labels": 1,
                    "question_context": cleaned_context,
                    "trigger_kinds": [trigger_kind],
                    "triggers": [
                        {
                            "kind": trigger_kind,
                            "historical_label": _canonical_path(requested_label),
                            "direct_match": direct_match,
                            "direct_should_be": direct_should_be,
                            "direct_reason": direct_reason,
                        }
                    ],
                }
            )
            counts[trigger_kind] += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    hold_output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as output:
        for task in tasks:
            output.write(json.dumps(task, ensure_ascii=False, sort_keys=True) + "\n")
    with hold_output_path.open("x", encoding="utf-8") as output:
        for hold in holds:
            output.write(json.dumps(hold, ensure_ascii=False, sort_keys=True) + "\n")

    return {
        "schema_version": "mentor-tree-correction-task-report-v1",
        "verification_path": str(verification_path),
        "verify_label": requested_label,
        "output_path": str(output_path),
        "hold_output_path": str(hold_output_path),
        "input_records": sum(route_counts.values()),
        "tasks": len(tasks),
        "holds": len(holds),
        "trigger_counts": dict(sorted(counts.items())),
        "route_counts": dict(sorted(route_counts.items())),
    }
