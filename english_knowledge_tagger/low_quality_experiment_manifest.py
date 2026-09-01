"""Manifest-driven offline preparation for low-quality definition experiments."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Mapping

from .knowledge_rulebook import load_knowledge_rulebook
from .knowledge_taxonomy_migration import load_knowledge_taxonomy_migration
from .mentor_direct_materialization import materialize_mentor_direct_verdicts
from .terminal_label_stability import build_terminal_label_stability_packet


SCHEMA_VERSION = "low-quality-definition-experiment-manifest-v1"
_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass(frozen=True)
class PseudoGoldSource:
    legacy_label: str
    path: Path
    expected_records: int


@dataclass(frozen=True)
class LowQualityExperimentManifest:
    path: Path
    teacher_csv: Path
    definition_overrides: Path
    taxonomy_migration: Path
    mentor_samples: Path
    mentor_results: Path
    pseudo_gold_sources: tuple[PseudoGoldSource, ...]
    teacher_corrections: Path | None = None


def _expand_path(
    value: object,
    *,
    field: str,
    base: Path,
    environment: Mapping[str, str],
) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"manifest {field} must be a non-empty path string")

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in environment:
            raise ValueError(f"manifest {field} references missing environment variable {name}")
        return environment[name]

    expanded = _ENV_PATTERN.sub(replace, value.strip())
    path = Path(expanded).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def load_low_quality_experiment_manifest(
    path: Path,
    *,
    environment: Mapping[str, str] | None = None,
    check_paths: bool = True,
) -> LowQualityExperimentManifest:
    """Load a path manifest and optionally require all declared inputs to exist."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"experiment manifest is not valid JSON: {path}") from error
    if not isinstance(payload, Mapping) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"experiment manifest schema_version must be {SCHEMA_VERSION!r}")
    env = dict(os.environ if environment is None else environment)
    base = path.resolve().parent
    required = {
        field: _expand_path(
            payload.get(field), field=field, base=base, environment=env
        )
        for field in (
            "teacher_csv",
            "definition_overrides",
            "taxonomy_migration",
            "mentor_samples",
            "mentor_results",
        )
    }
    raw_sources = payload.get("pseudo_gold_sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ValueError("manifest pseudo_gold_sources must be a non-empty list")
    sources = []
    seen_labels = set()
    for index, item in enumerate(raw_sources, 1):
        if not isinstance(item, Mapping):
            raise ValueError(f"pseudo_gold_sources[{index}] must be an object")
        label = item.get("legacy_label")
        if not isinstance(label, str) or not label.strip().startswith("知识点@"):
            raise ValueError(f"pseudo_gold_sources[{index}].legacy_label is invalid")
        label = label.strip()
        if label in seen_labels:
            raise ValueError(f"manifest contains duplicate pseudo-gold label: {label}")
        seen_labels.add(label)
        expected = item.get("expected_records")
        if not isinstance(expected, int) or isinstance(expected, bool) or expected <= 0:
            raise ValueError(f"pseudo_gold_sources[{index}].expected_records must be positive")
        sources.append(
            PseudoGoldSource(
                legacy_label=label,
                path=_expand_path(
                    item.get("path"),
                    field=f"pseudo_gold_sources[{index}].path",
                    base=base,
                    environment=env,
                ),
                expected_records=expected,
            )
        )
    teacher_corrections = (
        _expand_path(
            payload.get("teacher_corrections"),
            field="teacher_corrections",
            base=base,
            environment=env,
        )
        if payload.get("teacher_corrections") is not None
        else None
    )
    declared_paths = [*required.values(), *(item.path for item in sources)]
    if teacher_corrections is not None:
        declared_paths.append(teacher_corrections)
    if check_paths:
        missing = next((item for item in declared_paths if not item.is_file()), None)
        if missing is not None:
            raise ValueError(f"manifest input path is not a readable file: {missing}")
    return LowQualityExperimentManifest(
        path=path.resolve(),
        teacher_csv=required["teacher_csv"],
        definition_overrides=required["definition_overrides"],
        taxonomy_migration=required["taxonomy_migration"],
        mentor_samples=required["mentor_samples"],
        mentor_results=required["mentor_results"],
        pseudo_gold_sources=tuple(sources),
        teacher_corrections=teacher_corrections,
    )


def _slug(label: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", label).strip("_")
    return normalized[:160]


def prepare_low_quality_definition_batch(
    manifest: LowQualityExperimentManifest,
    *,
    output_root: Path,
    seed: str,
) -> dict[str, object]:
    """Materialize each reviewed label and build D0/D1/D2 packets offline."""
    if output_root.exists():
        raise FileExistsError(f"batch output root already exists: {output_root}")
    if not seed.strip():
        raise ValueError("batch seed must be non-empty")
    rulebook = load_knowledge_rulebook(
        manifest.teacher_csv, overrides_path=manifest.definition_overrides
    )
    migration = load_knowledge_taxonomy_migration(manifest.taxonomy_migration)
    slugs = [_slug(item.legacy_label) for item in manifest.pseudo_gold_sources]
    if len(slugs) != len(set(slugs)):
        raise ValueError("pseudo-gold label slugs collide")
    output_root.mkdir(parents=True)
    indexed = []
    for source, slug in zip(manifest.pseudo_gold_sources, slugs):
        label_root = output_root / slug
        label_root.mkdir()
        materialized = label_root / "materialized.jsonl"
        materialization = materialize_mentor_direct_verdicts(
            manifest.mentor_samples,
            results_path=manifest.mentor_results,
            verify_label=source.legacy_label,
            output_path=materialized,
        )
        packet = label_root / "stability.packet.jsonl"
        packet_report = build_terminal_label_stability_packet(
            materialized,
            pseudo_gold_path=source.path,
            verify_label=source.legacy_label,
            rulebook=rulebook,
            migration=migration,
            output_path=packet,
            seed=seed,
        )
        if packet_report["questions"] != source.expected_records:
            raise ValueError(
                f"pseudo-gold count mismatch for {source.legacy_label}: "
                f"expected {source.expected_records}, got {packet_report['questions']}"
            )
        indexed.append(
            {
                "legacy_label": source.legacy_label,
                "canonical_label": packet_report["canonical_label"],
                "pseudo_gold_path": str(source.path),
                "materialized_path": str(materialized),
                "packet_path": str(packet),
                "questions": packet_report["questions"],
                "packet_rows": packet_report["packet_rows"],
                "definition_variants": packet_report["definition_variants"],
                "materialized_records": materialization["materialized_records"],
            }
        )
    index = {
        "schema_version": "low-quality-definition-batch-index-v1",
        "manifest": str(manifest.path),
        "output_root": str(output_root),
        "seed": seed,
        "labels": indexed,
    }
    (output_root / "batch.index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "schema_version": "low-quality-definition-batch-report-v1",
        "output_root": str(output_root),
        "index": str(output_root / "batch.index.json"),
        "labels": len(indexed),
        "questions": sum(int(item["questions"]) for item in indexed),
        "packet_rows": sum(int(item["packet_rows"]) for item in indexed),
    }
