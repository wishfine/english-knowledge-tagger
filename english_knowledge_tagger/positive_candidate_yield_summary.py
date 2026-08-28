"""Render current mentor DS match yields for frozen positive candidate manifests."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Iterable


_BUCKETS = (
    (90.0, "DS match ≥90%"),
    (80.0, "DS match 80%–89.9%"),
    (70.0, "DS match 70%–79.9%"),
    (0.0, "DS match <70%：快速筛选 hold"),
)


def _candidate_labels(manifest_paths: Iterable[Path]) -> tuple[str, ...]:
    labels: list[str] = []
    seen: set[str] = set()
    for path in manifest_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        candidates = payload.get("candidates")
        if not isinstance(candidates, list):
            raise ValueError(f"manifest candidates must be a list: {path}")
        for item in candidates:
            label = item.get("legacy_label") if isinstance(item, dict) else None
            if not isinstance(label, str) or not label.strip():
                raise ValueError(f"manifest candidate must have legacy_label: {path}")
            if label in seen:
                raise ValueError(f"duplicate candidate label across manifests: {label}")
            seen.add(label)
            labels.append(label)
    return tuple(labels)


def _mentor_report_rates(path: Path) -> dict[str, tuple[int, int, float]]:
    rates: dict[str, tuple[int, int, float]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| 知识点@"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 6:
            continue
        match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)%", cells[5])
        if match is None:
            continue
        label = cells[0]
        if label in rates:
            raise ValueError(f"duplicate DS match rate in ledger: {label}")
        try:
            total = int(cells[1])
            matched = int(cells[2])
        except ValueError as error:
            raise ValueError(f"invalid mentor report counts for {label}") from error
        if total <= 0 or not 0 <= matched <= total:
            raise ValueError(f"invalid mentor report match counts for {label}")
        rates[label] = (matched, total, float(match.group(1)))
    return rates


def build_positive_candidate_yield_summary(
    manifest_paths: tuple[Path, ...], ledger_path: Path
) -> str:
    """Return a Markdown report for every manifest candidate using current ledger rates."""
    labels = _candidate_labels(manifest_paths)
    rates = _mentor_report_rates(ledger_path)
    missing = [label for label in labels if label not in rates]
    if missing:
        raise ValueError("candidate labels missing DS rates from mentor report: " + ", ".join(missing))

    grouped: list[tuple[str, list[tuple[str, int, int, float]]]] = []
    for index, (threshold, title) in enumerate(_BUCKETS):
        upper = _BUCKETS[index - 1][0] if index else None
        rows = [
            (label, *rates[label])
            for label in labels
            if rates[label][2] >= threshold and (upper is None or rates[label][2] < upper)
        ]
        rows.sort(key=lambda row: (-row[3], row[0]))
        grouped.append((title, rows))

    low_count = len(grouped[-1][1])
    lines = [
        "# 133 个正例候选标签：当前 DS match 汇总",
        "",
        "## 使用说明",
        "",
        "- 标签集合来自两个冻结 manifest，合计 133 个；DS match 直接来自 mentor 原始验证报告。",
        "- DS match 是 mentor DS 与历史标签的一致率，不是人工真实准确率。",
        "- `eligible` 仅表示仍满足当前 DS match ≥70% 的快速筛选前置条件；仍需 final 判别、独立 60 条审计和完整标签集合 gate。",
        "- `hold` 表示当前 DS match <70%，不得作为快速筛选发布对象；不删除源数据。",
        "",
        "## 当前快照",
        "",
        f"- 候选标签：{len(labels)}",
        f"- 当前 DS match ≥70%：{len(labels) - low_count}",
        f"- 当前 DS match <70%：{low_count}",
        "",
    ]
    for title, rows in grouped:
        lines.extend([f"## {title}（{len(rows)}）", "", "| 标签 | DS match | 当前快速池状态 |", "|---|---:|---|"])
        for label, matched, total, rate in rows:
            status = "`eligible`" if rate >= 70 else "`hold`"
            lines.append(f"| {label} | {matched}/{total} = {rate:.1f}% | {status} |")
        lines.append("")
    return "\n".join(lines)
