"""Build whole-taxonomy root tasks only for atomic label-blind gate outcomes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping


def build_root_tree_tasks(packet_path: Path, evidence_path: Path, *, output_path: Path) -> dict[str, object]:
    if output_path.exists():
        raise FileExistsError(f"root tree task output already exists: {output_path}")
    packet: dict[str, Mapping[str, object]] = {}
    with packet_path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip(): continue
            row = json.loads(line)
            if not isinstance(row, Mapping) or not isinstance(row.get("task_id"), str): raise ValueError(f"packet line {line_number}: task_id required")
            if row["task_id"] in packet: raise ValueError(f"packet line {line_number}: duplicate task_id")
            packet[row["task_id"]] = row
    tasks=[]; shapes={}
    with evidence_path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip(): continue
            evidence=json.loads(line)
            if not isinstance(evidence, Mapping) or not isinstance(evidence.get("task_id"), str): raise ValueError(f"evidence line {line_number}: task_id required")
            task_id=evidence["task_id"]
            if task_id not in packet: raise ValueError(f"evidence line {line_number}: task absent from packet")
            shape=evidence.get("task_shape")
            shapes[str(shape if shape is not None else evidence.get("status", "missing"))]=shapes.get(str(shape if shape is not None else evidence.get("status", "missing")),0)+1
            if shape != "atomic_knowledge": continue
            row=packet[task_id]
            tasks.append({"schema_version":"root-tree-task-v1", "task_id":f"root-tree:{task_id}", "source_task_id":task_id, "source_line":row.get("source_line"), "question_id":row.get("question_id"), "parent_id":row.get("parent_id"), "route_key":row.get("route_key"), "knowledge_policy":"required", "allowed_knowledge_prefixes":["知识点"], "max_output_labels":1, "question_context":row.get("question_context"), "trigger_kinds":["task_shape_atomic"], "triggers":[{"kind":"task_shape_atomic", "gate_evidence":evidence.get("evidence")} ]})
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as output:
        for row in tasks: output.write(json.dumps(row, ensure_ascii=False, sort_keys=True)+"\n")
    return {"schema_version":"root-tree-task-report-v1", "packet_path":str(packet_path), "evidence_path":str(evidence_path), "output_path":str(output_path), "gate_counts":shapes, "tree_tasks":len(tasks)}
