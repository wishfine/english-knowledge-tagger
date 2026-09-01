#!/usr/bin/env python3
"""Build the read-only definition ambiguity profile for all knowledge leaves."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from english_knowledge_tagger.definition_ambiguity_profile import (
    build_definition_ambiguity_manifest,
    load_p0_label_policy,
    summarize_confusion_evidence,
    summarize_mentor_results,
)
from english_knowledge_tagger.knowledge_rulebook import load_knowledge_rulebook
from english_knowledge_tagger.knowledge_taxonomy_migration import (
    load_knowledge_taxonomy_migration,
)


_FLAG_COLUMNS = (
    "known_definition_override",
    "broad_trigger_wording",
    "missing_negative_boundary",
    "missing_standard_route",
    "missing_examples",
    "low_original_compressed_overlap",
    "fallback_or_comprehensive",
)


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = (
        "canonical_label",
        "status",
        "root_node",
        "is_p0",
        "matches",
        "mismatches",
        "sample_size",
        "match_rate",
        "ambiguity_score",
        "direct_active_leaf_siblings",
        "audit_families",
        "confusion_neighbors",
        *_FLAG_COLUMNS,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            mentor_yield = row["mentor_yield"]
            flags = row["flags"]
            writer.writerow(
                {
                    "canonical_label": row["canonical_label"],
                    "status": row["status"],
                    "root_node": row["root_node"],
                    "is_p0": str(bool(row["is_p0"])).lower(),
                    "matches": mentor_yield["matches"],
                    "mismatches": mentor_yield["mismatches"],
                    "sample_size": mentor_yield["sample_size"],
                    "match_rate": (
                        "" if mentor_yield["match_rate"] is None else mentor_yield["match_rate"]
                    ),
                    "ambiguity_score": row["ambiguity_score"],
                    "direct_active_leaf_siblings": row["direct_active_leaf_siblings"],
                    "audit_families": json.dumps(row["audit_families"], ensure_ascii=False),
                    "confusion_neighbors": json.dumps(
                        row["confusion_neighbors"], ensure_ascii=False
                    ),
                    **{name: str(bool(flags[name])).lower() for name in _FLAG_COLUMNS},
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teacher-csv", type=Path, required=True)
    parser.add_argument("--definition-overrides", type=Path, required=True)
    parser.add_argument("--taxonomy-migration", type=Path, required=True)
    parser.add_argument("--mentor-results", type=Path, required=True)
    parser.add_argument(
        "--confusion-evidence",
        type=Path,
        action="append",
        help="Optional flat replace or tree-candidate JSONL; may be repeated.",
    )
    parser.add_argument("--p0-policy", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    outputs = (args.output_json, args.output_csv, args.report)
    if len(set(outputs)) != len(outputs):
        parser.error("output paths must be distinct")
    existing = next((path for path in outputs if path.exists()), None)
    if existing is not None:
        parser.error(f"refusing to overwrite existing output: {existing}")
    try:
        rulebook = load_knowledge_rulebook(
            args.teacher_csv, overrides_path=args.definition_overrides
        )
        migration = load_knowledge_taxonomy_migration(args.taxonomy_migration)
        yields = summarize_mentor_results(
            args.mentor_results, migration=migration, rulebook=rulebook
        )
        manifest = build_definition_ambiguity_manifest(
            rulebook,
            yields=yields,
            p0_labels=load_p0_label_policy(args.p0_policy),
            additional_confusions=summarize_confusion_evidence(
                tuple(args.confusion_evidence or ()),
                migration=migration,
                rulebook=rulebook,
            ),
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_csv(args.output_csv, list(manifest["labels"]))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(manifest["summary"], ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest["summary"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
