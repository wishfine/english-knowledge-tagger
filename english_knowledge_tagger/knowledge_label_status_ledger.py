"""Build a reproducible status ledger for the complete teacher label set."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable, Mapping

from .knowledge_taxonomy_migration import load_knowledge_taxonomy_migration


SCHEMA_VERSION = "knowledge-label-status-ledger-v1"
_METRIC = re.compile(r"(?P<matches>\d+)\s*/\s*(?P<total>\d+)\s*=\s*(?P<rate>[\d.]+)%")
_Z95_ONE_SIDED = 1.6448536269514722


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_raw(label: str) -> str:
    return "知识点->" + label.removeprefix("知识点@").replace("@", "->")


def _parse_table_line(line: str) -> dict[str, str]:
    cells = [cell.strip() for cell in line.split("|")[1:-1]]
    if len(cells) < 6:
        raise ValueError(f"full sample ledger row has fewer than 6 cells: {line[:120]}")
    return {
        "legacy_label": cells[0],
        "ds_rate": cells[1],
        "true_accuracy": cells[2],
        "false_error": cells[3],
        "conclusion": cells[4],
        "summary": cells[5],
    }


def _parse_metric(value: str) -> tuple[int, int, float] | None:
    match = _METRIC.search(value)
    if match is None:
        return None
    matches = int(match.group("matches"))
    total = int(match.group("total"))
    if total <= 0 or matches < 0 or matches > total:
        return None
    return matches, total, float(match.group("rate")) / 100.0


def _wilson_lower(matches: int, total: int) -> float:
    p = matches / total
    z2 = _Z95_ONE_SIDED**2
    denominator = 1 + z2 / total
    centre = p + z2 / (2 * total)
    spread = _Z95_ONE_SIDED * ((p * (1 - p) / total + z2 / (4 * total**2)) ** 0.5)
    return max(0.0, (centre - spread) / denominator)


def _load_manifest_labels(paths: Iterable[Path]) -> tuple[set[str], dict[str, str]]:
    labels: set[str] = set()
    sources: dict[str, str] = {}
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError(f"candidate manifest must be an object: {path}")
        source_name = path.stem
        for item in payload.get("candidates", []):
            if not isinstance(item, Mapping) or not isinstance(item.get("legacy_label"), str):
                raise ValueError(f"candidate manifest has malformed candidate: {path}")
            label = item["legacy_label"].strip()
            labels.add(label)
            sources[label] = source_name
    return labels, sources


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def build_knowledge_label_status_ledger(
    *,
    full_sample_ledger: Path,
    candidate_manifests: tuple[Path, ...],
    output: Path,
    quality_excluded: Iterable[str],
    post_sweep_hold: Iterable[str],
    taxonomy_reconciled: Mapping[str, str],
    taxonomy_migration: Path | None = None,
    expected_label_count: int = 384,
) -> dict[str, object]:
    """Render all labels in the authoritative 384-row sample ledger.

    ``candidate_manifests`` identify labels that have final-discriminator
    evidence. Four known low-quality labels and two post-sweep issue labels
    are assigned explicit hold states. The historical ``can/can't`` label is
    kept as the displayed legacy name but may be mapped to the active teacher
    canonical label through ``taxonomy_reconciled``.
    """
    if output.exists():
        raise FileExistsError(f"refusing to overwrite status ledger: {output}")
    if not full_sample_ledger.is_file():
        raise FileNotFoundError(f"full sample ledger not found: {full_sample_ledger}")
    candidate_labels, manifest_sources = _load_manifest_labels(candidate_manifests)
    quality_excluded_set = frozenset(label.strip() for label in quality_excluded if label.strip())
    post_sweep_set = frozenset(label.strip() for label in post_sweep_hold if label.strip())
    reconciled = {key.strip(): value.strip() for key, value in taxonomy_reconciled.items()}
    migration = load_knowledge_taxonomy_migration(taxonomy_migration) if taxonomy_migration else None

    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(full_sample_ledger.read_text(encoding="utf-8").splitlines(), 1):
        if not line.startswith("| 知识点@"):
            continue
        parsed = _parse_table_line(line)
        legacy = parsed["legacy_label"]
        canonical = reconciled.get(legacy, _canonical_raw(legacy))
        if migration is not None and legacy not in reconciled:
            canonical = migration.canonicalize(_canonical_raw(legacy)).canonical_path
        metric = _parse_metric(parsed["ds_rate"])
        if metric is None:
            raise ValueError(f"could not parse DS metric for {legacy!r} at line {line_number}")
        matches, total, rate = metric
        if legacy in reconciled:
            status = "taxonomy_reconciled_pending_rerun"
            status_text = "taxonomy 已纠正，待重新物化/终判"
            source = "wilson141-delta12（原 taxonomy blocked）"
            next_action = "按纠正后的 canonical label 重新物化 packet、终判并做 60 条独立复核"
        elif legacy in quality_excluded_set:
            status = "quality_excluded"
            status_text = "已完成终判，但排除出优质池"
            source = "run133（低质量排除）"
            next_action = "保留为诊断数据；不进入 silver 或训练"
        elif legacy in post_sweep_set:
            status = "post_sweep_hold"
            status_text = "终判完成，post-sweep hold"
            source = "run133/delta11 + 6 条抽检"
            next_action = "定向回查错标/歧义题，修复前保持 hold"
        elif legacy in candidate_labels:
            status = "training_candidate_unreleased"
            status_text = "终判完成，训练候选（未发布）"
            source = manifest_sources.get(legacy, "final evidence")
            next_action = "使用 v3 源合并标签；完成 60 条独立复核后再升级"
        else:
            status = "pending_fast_pool_review"
            status_text = "待处理：未通过快速池门禁"
            source = "完整校准台账"
            next_action = "先做 route/释义/错标模式复核，再决定是否重标或进入快速池"
        rows.append(
            {
                **parsed,
                "canonical_label": canonical,
                "ds_matches": matches,
                "ds_total": total,
                "ds_rate_value": rate,
                "wilson_lower": _wilson_lower(matches, total),
                "status": status,
                "status_text": status_text,
                "source": source,
                "next_action": next_action,
            }
        )

    if not rows:
        raise ValueError("full sample ledger contains no knowledge-label rows")
    status_counts = Counter(str(row["status"]) for row in rows)
    if len(rows) != expected_label_count:
        raise ValueError(
            f"expected {expected_label_count} labels in full sample ledger, found {len(rows)}"
        )

    summary_lines = [
        "# 384 个知识点标签总状态台账",
        "",
        "## 口径",
        "",
        "本台账以 `docs/knowledge-label-calibration-ledger-full-sample.md` 的 384 条末级标签为完整集合。DS 匹配率、True/False 抽样指标沿用该权威台账；状态只描述当前工程证据和处理进度，不把 DS 匹配率当作标签准确率。",
        "",
        "`can/can't表示推测` 不是一个新的 taxonomy 节点。老师 CSV 中已有目标节点 `知识点->词法->动词->情态动词->can->can't表示否定推测`；本台账将历史名称映射到该 canonical 路径，但仍需重新物化 packet、终判和独立复核，不能直接混入当前 138 个训练候选。",
        "",
        "## 状态汇总",
        "",
        "| 状态 | 数量 | 含义 |",
        "|---|---:|---|",
        f"| `training_candidate_unreleased` | {status_counts['training_candidate_unreleased']} | 已有终判正例证据，可进入当前 v3 训练候选；尚未发布为 released silver |",
        f"| `post_sweep_hold` | {status_counts['post_sweep_hold']} | 终判完成，但 6 条抽检发现标签级问题/歧义 |",
        f"| `quality_excluded` | {status_counts['quality_excluded']} | 已运行但未达到优质池门禁 |",
        f"| `taxonomy_reconciled_pending_rerun` | {status_counts['taxonomy_reconciled_pending_rerun']} | 原历史名称已纠正到 CSV 现有节点，尚未重新终判 |",
        f"| `pending_fast_pool_review` | {status_counts['pending_fast_pool_review']} | 还没有足够的快速池终判证据 |",
        f"| **合计** | **{len(rows)}** | |",
        "",
        "## 384 条明细",
        "",
        "| # | 历史标签 | 统一 canonical label | DS 匹配率 | Wilson 单侧95%下界 | True 抽样 | False 抽样 | 当前状态 | 证据来源 | 下一步 |",
        "|---:|---|---|---:|---:|---|---|---|---|---|",
    ]
    for index, row in enumerate(rows, 1):
        summary_lines.append(
            "| "
            + " | ".join(
                (
                    str(index),
                    _cell(row["legacy_label"]),
                    _cell(row["canonical_label"]),
                    _cell(row["ds_rate"]),
                    f"{float(row['wilson_lower']) * 100:.2f}%",
                    _cell(row["true_accuracy"]),
                    _cell(row["false_error"]),
                    _cell(row["status_text"]),
                    _cell(row["source"]),
                    _cell(row["next_action"]),
                )
            )
            + "|"
        )
    summary_lines.extend(
        [
            "",
            "## 证据与复核说明",
            "",
            "- `training_candidate_unreleased` 当前对应 138 个标签；题级训练文件仍要求同一道题的全部未排除历史标签都有唯一、完整、`llm_match=true` evidence。",
            "- `post_sweep_hold` 当前为 `同/近义词` 和 `be going to` 两个标签；它们不能因为 DS true 比例高就自动放行。",
            "- `quality_excluded` 的四个标签继续保留原始 evidence，作为后续诊断，不删除 source。",
            "- `pending_fast_pool_review` 不代表标签错误，只表示当前证据不足；应按标签逐个补 route、释义和错标模式。",
            "",
            "## 输入版本",
            "",
            f"- 完整校准台账 SHA-256：`{_sha256(full_sample_ledger)}`",
        ]
    )
    for manifest in candidate_manifests:
        summary_lines.append(f"- 候选 manifest `{manifest}` SHA-256：`{_sha256(manifest)}`")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return {
        "schema_version": SCHEMA_VERSION,
        "output": str(output),
        "total_labels": len(rows),
        "status_counts": dict(sorted(status_counts.items())),
        "candidate_manifest_count": len(candidate_manifests),
        "candidate_manifest_labels": len(candidate_labels),
        "source_ledger": str(full_sample_ledger),
        "source_ledger_sha256": _sha256(full_sample_ledger),
        "taxonomy_reconciled": dict(sorted(reconciled.items())),
    }
