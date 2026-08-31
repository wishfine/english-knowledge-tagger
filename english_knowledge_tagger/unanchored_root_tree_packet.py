"""Build whole-taxonomy tree tasks without using a historical target label."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping


def build_unanchored_root_tree_packet(source_path: Path, *, output_path: Path) -> dict[str, object]:
    """Turn a sanitized question packet into one root-tree task per row.

    The input is expected to come from ``conversion_relation_packet`` (or an
    equivalent sanitized packet). Only question identity, route and context
    cross the boundary; historical labels and model judgements are excluded.
    """
    if output_path.exists():
        raise FileExistsError(f"unanchored root tree output already exists: {output_path}")
    tasks: list[dict[str, object]] = []
    seen: set[str] = set()
    with source_path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"source line {line_number}: invalid JSON") from error
            if not isinstance(row, Mapping):
                raise ValueError(f"source line {line_number}: row must be an object")
            task_id = row.get("task_id")
            if not isinstance(task_id, str) or not task_id.strip():
                raise ValueError(f"source line {line_number}: task_id must be non-empty")
            task_id = task_id.strip()
            if task_id in seen:
                raise ValueError(f"source line {line_number}: duplicate task_id {task_id!r}")
            seen.add(task_id)
            context = row.get("question_context")
            if not isinstance(context, str) or not context.strip():
                raise ValueError(f"source line {line_number}: question_context must be non-empty")
            route = row.get("route_key")
            if not isinstance(route, Mapping):
                raise ValueError(f"source line {line_number}: route_key must be an object")
            tasks.append({
                "schema_version": "unanchored-root-tree-task-v1",
                "task_id": f"root-tree:{task_id}",
                "source_task_id": task_id,
                "source_line": row.get("source_line", line_number),
                "question_id": row.get("question_id"),
                "parent_id": row.get("parent_id"),
                "route_key": dict(route),
                "knowledge_policy": "required",
                "allowed_knowledge_prefixes": ["知识点"],
                "max_output_labels": 1,
                "question_context": context.strip(),
                "trigger_kinds": ["unanchored_root_tree"],
                "triggers": [{"kind": "unanchored_root_tree"}],
            })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as output:
        for task in tasks:
            output.write(json.dumps(task, ensure_ascii=False, sort_keys=True) + "\n")
    return {
        "schema_version": "unanchored-root-tree-task-report-v1",
        "source_path": str(source_path),
        "output_path": str(output_path),
        "tree_tasks": len(tasks),
    }
