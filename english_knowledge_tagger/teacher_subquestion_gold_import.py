"""Import teacher-verified numbered small-question labels from a workbook read-only."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterator, Mapping
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from .knowledge_rulebook import KnowledgeRulebook
from .knowledge_taxonomy_migration import KnowledgeTaxonomyMigration


SCHEMA_VERSION = "teacher-subquestion-gold-v1"
DEFAULT_SHEET = "小题知识点"
QUESTION_ID_HEADER = "题目ID"
GOLD_LABELS_HEADER = "小题知识点标签（每个小题单独一行）"
_NUMBERED_ITEM = re.compile(r"(?m)^\s*[（(](\d+)[)）]\s*")
_SPREADSHEET = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_OFFICE_RELATIONSHIP = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_RELATIONSHIP = "http://schemas.openxmlformats.org/package/2006/relationships"
_NS = {"m": _SPREADSHEET, "r": _OFFICE_RELATIONSHIP, "p": _PACKAGE_RELATIONSHIP}


def _node_text(node: ET.Element | None) -> str:
    return "".join(node.itertext()) if node is not None else ""


def _column(reference: str) -> str:
    return "".join(character for character in reference if character.isalpha())


def _sheet_path(target: str) -> str:
    normalized = PurePosixPath(target)
    if normalized.is_absolute() or ".." in normalized.parts:
        raise ValueError(f"workbook sheet relationship has unsafe target: {target}")
    return str(PurePosixPath("xl") / normalized)


def _shared_strings(archive: ZipFile) -> tuple[str, ...]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return ()
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return tuple(_node_text(item) for item in root.findall("m:si", _NS))


def _worksheet_rows(workbook_path: Path, sheet_name: str) -> Iterator[tuple[int, dict[str, str]]]:
    with ZipFile(workbook_path) as archive:
        shared = _shared_strings(archive)
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {
            relation.attrib["Id"]: relation.attrib["Target"]
            for relation in relationships.findall("p:Relationship", _NS)
            if "Id" in relation.attrib and "Target" in relation.attrib
        }
        sheet = next(
            (item for item in workbook.findall("m:sheets/m:sheet", _NS) if item.attrib.get("name") == sheet_name),
            None,
        )
        if sheet is None:
            raise ValueError(f"teacher workbook has no sheet named {sheet_name!r}")
        relationship_id = sheet.attrib.get(f"{{{_OFFICE_RELATIONSHIP}}}id")
        if relationship_id not in targets:
            raise ValueError(f"teacher workbook sheet {sheet_name!r} has no relationship target")
        worksheet = ET.fromstring(archive.read(_sheet_path(targets[relationship_id])))
        for row in worksheet.findall("m:sheetData/m:row", _NS):
            row_number = int(row.attrib.get("r", "0"))
            values: dict[str, str] = {}
            for cell in row.findall("m:c", _NS):
                reference = cell.attrib.get("r", "")
                column = _column(reference)
                if not column:
                    continue
                cell_type = cell.attrib.get("t")
                if cell_type == "inlineStr":
                    value = _node_text(cell.find("m:is", _NS))
                else:
                    raw_value = cell.find("m:v", _NS)
                    value = raw_value.text if raw_value is not None and raw_value.text is not None else ""
                    if cell_type == "s" and value:
                        try:
                            value = shared[int(value)]
                        except (IndexError, ValueError) as error:
                            raise ValueError(
                                f"teacher workbook row {row_number} has invalid shared-string reference"
                            ) from error
                values[column] = value
            yield row_number, values


def _canonical_path(label: str) -> str:
    normalized = label.strip()
    if not normalized.startswith("知识点@"):
        raise ValueError(f"teacher gold label must start with '知识点@': {normalized}")
    return "知识点->" + normalized.removeprefix("知识点@").replace("@", "->")


def _numbered_label_sets(value: str) -> tuple[tuple[int, tuple[str, ...]], ...]:
    matches = list(_NUMBERED_ITEM.finditer(value))
    if not matches:
        return ()
    sets: list[tuple[int, tuple[str, ...]]] = []
    seen_indexes: set[int] = set()
    for position, match in enumerate(matches):
        index = int(match.group(1))
        if index <= 0 or index in seen_indexes:
            raise ValueError(f"teacher gold labels have invalid or duplicate subquestion index: {index}")
        seen_indexes.add(index)
        end = matches[position + 1].start() if position + 1 < len(matches) else len(value)
        raw_labels = value[match.end() : end].strip()
        labels = tuple(label.strip() for label in re.split(r"[;；]", raw_labels) if label.strip())
        if not labels:
            raise ValueError(f"teacher gold labels subquestion {index} has no labels")
        if len(set(labels)) != len(labels):
            raise ValueError(f"teacher gold labels subquestion {index} has duplicate labels")
        sets.append((index, labels))
    return tuple(sets)


def import_teacher_subquestion_gold(
    workbook_path: Path,
    *,
    rulebook: KnowledgeRulebook,
    migration: KnowledgeTaxonomyMigration,
    output_path: Path,
    sheet_name: str = DEFAULT_SHEET,
) -> dict[str, object]:
    """Write parent-ID and numbered-subquestion teacher gold without resolving source children."""
    if output_path.exists():
        raise FileExistsError(f"teacher subquestion gold output already exists: {output_path}")
    rows = list(_worksheet_rows(workbook_path, sheet_name))
    header_row_number: int | None = None
    header_columns: dict[str, str] = {}
    for row_number, values in rows:
        reverse = {value.strip(): column for column, value in values.items() if value.strip()}
        if QUESTION_ID_HEADER in reverse and GOLD_LABELS_HEADER in reverse:
            header_row_number = row_number
            header_columns = {
                "question_id": reverse[QUESTION_ID_HEADER],
                "gold_labels": reverse[GOLD_LABELS_HEADER],
            }
            break
    if header_row_number is None:
        raise ValueError(
            f"teacher workbook sheet {sheet_name!r} requires headers "
            f"{QUESTION_ID_HEADER!r} and {GOLD_LABELS_HEADER!r}"
        )

    output_rows: list[dict[str, object]] = []
    report_counts: Counter[str] = Counter()
    mapping_counts: Counter[str] = Counter()
    rulebook_status_counts: Counter[str] = Counter()
    parent_ids: set[str] = set()
    for excel_row, values in rows:
        if excel_row <= header_row_number:
            continue
        parent_question_id = values.get(header_columns["question_id"], "").strip()
        raw_gold = values.get(header_columns["gold_labels"], "").strip()
        if not parent_question_id and not raw_gold:
            continue
        if not parent_question_id or not raw_gold:
            report_counts["incomplete_rows"] += 1
            continue
        numbered_sets = _numbered_label_sets(raw_gold)
        if not numbered_sets:
            report_counts["non_small_question_rows"] += 1
            continue
        parent_ids.add(parent_question_id)
        for subquestion_index, legacy_labels in numbered_sets:
            mappings: list[dict[str, str | None]] = []
            canonical_labels: list[str] = []
            for legacy_label in legacy_labels:
                legacy_path = _canonical_path(legacy_label)
                canonicalized = migration.canonicalize(legacy_path)
                rulebook_record = rulebook.records.get(canonicalized.canonical_path)
                rulebook_status = rulebook_record.status if rulebook_record is not None else "unmapped"
                mapping_counts[canonicalized.status] += 1
                rulebook_status_counts[rulebook_status] += 1
                mappings.append(
                    {
                        "legacy_label": legacy_label,
                        "legacy_path": legacy_path,
                        "canonical_label": canonicalized.canonical_path,
                        "status": canonicalized.status,
                        "rule_id": canonicalized.rule_id,
                        "rulebook_status": rulebook_status,
                    }
                )
                canonical_labels.append(canonicalized.canonical_path)
            output_rows.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "source_workbook_path": str(workbook_path),
                    "source_workbook_sha256": hashlib.sha256(workbook_path.read_bytes()).hexdigest(),
                    "source_sheet": sheet_name,
                    "source_excel_row": excel_row,
                    "parent_question_id": parent_question_id,
                    "subquestion_index": subquestion_index,
                    "legacy_gold_labels": list(legacy_labels),
                    "gold_labels": canonical_labels,
                    "taxonomy_mappings": mappings,
                    "taxonomy_resolved": all(
                        mapping["rulebook_status"] == "active" for mapping in mappings
                    ),
                    "adjudication_status": "teacher_verified_unresolved_child_mapping",
                }
            )
            report_counts["subquestion_gold_sets"] += 1
            report_counts["individual_gold_labels"] += len(canonical_labels)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as output:
        for row in output_rows:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {
        "schema_version": SCHEMA_VERSION,
        "workbook_path": str(workbook_path),
        "workbook_sha256": hashlib.sha256(workbook_path.read_bytes()).hexdigest(),
        "sheet_name": sheet_name,
        "output_path": str(output_path),
        "parent_question_ids": len(parent_ids),
        "subquestion_gold_sets": report_counts["subquestion_gold_sets"],
        "individual_gold_labels": report_counts["individual_gold_labels"],
        "non_small_question_rows": report_counts["non_small_question_rows"],
        "incomplete_rows": report_counts["incomplete_rows"],
        "taxonomy_mapping_counts": dict(sorted(mapping_counts.items())),
        "rulebook_status_counts": dict(sorted(rulebook_status_counts.items())),
    }
