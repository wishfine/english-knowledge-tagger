"""Freeze deterministic four-pool label membership and pool-local names.

The freeze is intentionally based on the checked-in status ledger, not on
runtime evidence directories.  This makes numbering stable while individual
question records can still be routed to ``已处理`` or ``有问题`` later.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any


SCHEMA_VERSION = "label-pool-freeze-v1"
_METRIC = re.compile(r"(?P<matches>\d+)\s*/\s*(?P<total>\d+)\s*=\s*(?P<rate>[\d.]+)%")
_ROW = re.compile(r"^\|\s*(?P<index>\d+)\s*\|")
_POOL_ORDER = ("优质", "次优", "劣质", "次次优")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _metric(value: str) -> tuple[int, int, float] | None:
    match = _METRIC.search(value)
    if match is None:
        return None
    matches = int(match.group("matches"))
    total = int(match.group("total"))
    if total <= 0 or matches < 0 or matches > total:
        raise ValueError(f"invalid metric: {value!r}")
    return matches, total, float(match.group("rate")) / 100.0


def _true_count(value: str) -> tuple[int, int] | None:
    match = re.search(r"(\d+)\s*/\s*(\d+)", value)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def _legacy_to_canonical(label: str) -> str:
    canonical = "知识点->" + label.removeprefix("知识点@").replace("@", "->")
    canonical = canonical.replace("知识点->语法词法", "知识点->词法")
    canonical = canonical.replace("知识点->语法句法", "知识点->句法")
    return canonical


def _parse_status_ledger(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _ROW.match(line)
        if match is None:
            continue
        cells = _cells(line)
        if len(cells) < 10:
            raise ValueError(f"status ledger row has fewer than 10 cells: {line[:120]}")
        legacy = cells[1]
        if not legacy.startswith("知识点@"):
            continue
        ds = _metric(cells[3])
        true = _true_count(cells[5])
        if ds is None or true is None:
            raise ValueError(f"could not parse metrics for {legacy!r}")
        record = {
            "ledger_index": int(match.group("index")),
            "legacy_label": legacy,
            "canonical_label": cells[2],
            "ds_matches": ds[0],
            "ds_total": ds[1],
            "ds_rate": ds[2],
            "ds_rate_text": cells[3],
            "wilson_lower": float(cells[4].rstrip("%")) / 100.0,
            "wilson_lower_text": cells[4],
            "true_matches": true[0],
            "true_total": true[1],
            "true_text": cells[5],
            "false_text": cells[6],
            "status_text": cells[7],
            "evidence_source": cells[8],
        }
        if legacy in records:
            raise ValueError(f"duplicate status ledger label: {legacy!r}")
        records[legacy] = record
    if not records:
        raise ValueError(f"no label rows found in status ledger: {path}")
    return records


def _parse_low_quality_ledger(path: Path) -> set[str]:
    labels: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = _cells(line)
        if len(cells) < 2:
            continue
        match = re.fullmatch(r"`([^`]+)`", cells[1])
        if match and match.group(1).startswith("知识点@"):
            labels.add(match.group(1))
    return labels


def _safe_label(label: str) -> str:
    replacements = {
        "/": "／",
        "\\": "＼",
        ":": "：",
        "*": "＊",
        "?": "？",
        '"': "＂",
        "<": "＜",
        ">": "＞",
        "|": "｜",
    }
    value = "".join(replacements.get(char, "_" if ord(char) < 32 else char) for char in label)
    value = value.strip() or "label"
    return value.encode("utf-8")[:180].decode("utf-8", errors="ignore")


def _pool_reason(pool: str) -> str:
    return {
        "优质": "Wilson 单侧 95% 下界 ≥70% 且 True 抽样 12/12",
        "次优": "B/H 次优规则：B 为 50%≤DS<70% 且 True 12/12；H 为 DS>70% 且 True≠12/12",
        "劣质": "低质量处理台账中的 26 个标签",
        "次次优": "384 个完整集合扣除优质、次优、劣质后的剩余标签",
    }[pool]


def build_label_pool_freeze(
    *,
    status_ledger: Path,
    low_quality_ledger: Path,
    output_json: Path,
    output_markdown: Path | None,
    expected_label_count: int = 384,
) -> dict[str, Any]:
    """Build and optionally write the frozen four-pool manifest.

    Pool membership is disjoint and precedence is ``劣质`` → ``优质`` →
    ``次优`` → ``次次优``.  The low-quality precedence ensures an explicit
    remediation decision cannot be overridden by a high historical match rate.
    """
    if not status_ledger.is_file():
        raise FileNotFoundError(status_ledger)
    if not low_quality_ledger.is_file():
        raise FileNotFoundError(low_quality_ledger)
    status = _parse_status_ledger(status_ledger)
    low_quality = _parse_low_quality_ledger(low_quality_ledger)
    quality_excluded = {
        label
        for label, row in status.items()
        if "排除出优质池" in row["status_text"]
    }
    # ``quality_excluded`` is an audit flag, not a pool by itself.  A label
    # can be excluded from the quality gate and still satisfy the explicit
    # B/H next-best rule (the past-form label is the current example).  The
    # remaining excluded labels therefore fall through to 次次优.
    low_labels = low_quality

    labels = set(status) | low_quality
    if len(labels) != expected_label_count:
        raise ValueError(
            f"expected {expected_label_count} labels after low-quality union, found {len(labels)}"
        )

    assigned: dict[str, str] = {}
    reasons: dict[str, str] = {}
    for label in sorted(labels):
        row = status.get(label)
        if label in low_labels:
            pool = "劣质"
        elif row is not None and row["wilson_lower"] >= 0.70 and (
            row["true_matches"], row["true_total"]
        ) == (12, 12):
            pool = "优质"
        elif row is not None and (
            (0.50 <= row["ds_rate"] < 0.70 and (row["true_matches"], row["true_total"]) == (12, 12))
            or (row["ds_rate"] > 0.70 and (row["true_matches"], row["true_total"]) != (12, 12))
        ):
            pool = "次优"
        else:
            pool = "次次优"
        assigned[label] = pool
        reasons[label] = _pool_reason(pool)

    counters: Counter[str] = Counter(assigned.values())
    output_rows: list[dict[str, Any]] = []
    for pool in _POOL_ORDER:
        pool_labels = sorted(
            (label for label, value in assigned.items() if value == pool),
            key=lambda label: (status.get(label, {}).get("canonical_label", _legacy_to_canonical(label)), label),
        )
        for pool_index, label in enumerate(pool_labels, 1):
            row = dict(status.get(label) or {
                "ledger_index": None,
                "legacy_label": label,
                "canonical_label": _legacy_to_canonical(label),
                "ds_matches": None,
                "ds_total": None,
                "ds_rate": None,
                "ds_rate_text": None,
                "wilson_lower": None,
                "wilson_lower_text": None,
                "true_matches": None,
                "true_total": None,
                "true_text": None,
                "false_text": None,
                "status_text": "低质量处理台账，状态台账未列出",
                "evidence_source": "低质量处理台账",
            })
            row.update(
                {
                    "pool": pool,
                    "pool_index": pool_index,
                    "pool_reason": reasons[label],
                    "release_status": (
                        "hold"
                        if row.get("status_text")
                        in {"终判完成，post-sweep hold", "taxonomy 已纠正，待重新物化/终判"}
                        else "not_yet_released"
                    ),
                    "target_basename": f"{pool}-{pool_index:03d}-{_safe_label(label)}",
                    "target_filename": f"{pool}-{pool_index:03d}-{_safe_label(label)}.jsonl",
                }
            )
            output_rows.append(row)

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "freeze_id": "20260907",
        "pool_order": list(_POOL_ORDER),
        "precedence": ["劣质", "优质", "次优", "次次优"],
        "expected_label_count": expected_label_count,
        "pool_counts": {pool: counters[pool] for pool in _POOL_ORDER},
        "criteria": {
            "优质": "Wilson 单侧 95% 下界 >= 0.70 且 True 抽样为 12/12；显式 quality_excluded 只保留为审计标记",
            "次优": "B: 0.50 <= DS match < 0.70 且 True=12/12；H: DS match > 0.70 且 True!=12/12；排除优质和劣质",
            "劣质": "低质量处理台账标签（26 个）",
            "次次优": "完整标签集合的剩余项",
        },
        "sources": {
            "status_ledger": str(status_ledger),
            "status_ledger_sha256": _sha256(status_ledger),
            "low_quality_ledger": str(low_quality_ledger),
            "low_quality_ledger_sha256": _sha256(low_quality_ledger),
        },
        "quality_excluded_labels": sorted(quality_excluded),
        "low_quality_ledger_labels": sorted(low_quality),
        "labels": output_rows,
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    if output_json.exists():
        raise FileExistsError(f"refusing to overwrite {output_json}")
    output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if output_markdown is not None:
        if output_markdown.exists():
            raise FileExistsError(f"refusing to overwrite {output_markdown}")
        lines = [
            "# 四池标签冻结清单（2026-09-07）",
            "",
            "> 本文件只冻结标签池归属、池内编号和未来目标文件名；不移动、不重命名、不修改任何题目数据。题目记录在 DS 终判后仍按 `已处理` / `有问题` 分流。",
            "",
            "## 冻结结果",
            "",
            "| 池子 | 数量 | 编号范围 | 判定口径 |",
            "|---|---:|---|---|",
        ]
        for pool in _POOL_ORDER:
            lines.append(
                f"| {pool} | {counters[pool]} | {pool}-001 至 {pool}-{counters[pool]:03d} | {_pool_reason(pool)} |"
            )
        lines.extend(
            [
                "",
                "## 命名规则",
                "",
                "`<池子>-<三位池内编号>-<历史标签>.jsonl`。文件名中的 `/` 使用全角 `／`，编号按 canonical label 排序；完整对应关系以 JSON 清单为准。",
                "",
                "## 标签明细",
                "",
                "| 池子 | 编号 | 历史标签 | canonical label | DS 匹配率 | Wilson 下界 | True 抽样 | 当前状态 | 发布状态 | 目标文件名 |",
                "|---|---:|---|---|---:|---:|---|---|---|---|",
            ]
        )
        for row in output_rows:
            def cell(value: Any) -> str:
                return "" if value is None else str(value).replace("|", "\\|").replace("\n", " ")

            lines.append(
                "| "
                + " | ".join(
                    (
                        cell(row["pool"]),
                        cell(row["pool_index"]),
                        cell(row["legacy_label"]),
                        cell(row["canonical_label"]),
                        cell(row["ds_rate_text"]),
                        cell(row["wilson_lower_text"]),
                        cell(row["true_text"]),
                        cell(row["status_text"]),
                        cell(row["release_status"]),
                        cell(row["target_filename"]),
                    )
                )
                + "|"
            )
        lines.extend(
            [
                "",
                "## 重要说明",
                "",
                "- `优质` 是标签级候选池，不等于所有记录都已发布；记录仍须经过 DS 终判和最终质量规则。",
                "- `次优` 按 B78 + H32 固定（包含 `一般过去时@动词过去式变化规则`）；其余未进入前三池的标签统一归 `次次优`。",
                "- `quality_excluded` 只是审计标记：上述过去式标签进入次优；另外 3 个排除标签进入次次优，不并入劣质。",
                "- 同一道多标签题按题目-标签对分流；不能用一个标签的通过结果替代其他标签的判定。",
                "- 后续改名时只允许按本清单的 `target_filename` 执行，并保留旧名到新名的映射日志。",
                "",
                f"状态台账 SHA-256：`{payload['sources']['status_ledger_sha256']}`",
                f"劣质台账 SHA-256：`{payload['sources']['low_quality_ledger_sha256']}`",
            ]
        )
        output_markdown.parent.mkdir(parents=True, exist_ok=True)
        output_markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload
