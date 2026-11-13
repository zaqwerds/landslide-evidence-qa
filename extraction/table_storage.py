# -*- coding: utf-8 -*-
"""Store original table carriers, structure and Neo4j nodes for DOCX/PDF reports."""

from __future__ import annotations

import html
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from docx import Document
from docx.table import Table

from extraction.content_storage_common import (
    SectionTracker,
    ensure_content_constraints,
    ensure_report_node,
    iter_docx_blocks,
    make_report_id,
    page_break_count,
    relative_posix,
    sha256_file,
)
from extraction.table_extractor import TableParser
from extraction.value_normalizer import normalize_measurement


@dataclass
class StoredTableCell:
    cell_id: str
    row_index: int
    column_index: int
    raw_text: str
    header: str = ""
    header_path: str = ""
    normalized_value: Any = ""
    unit: str = ""
    is_numeric: bool = False
    is_range: bool = False
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    rowspan: int = 1
    colspan: int = 1
    confidence: float = 1.0


@dataclass
class StoredTableRow:
    row_id: str
    row_index: int
    row_type: str
    cells: List[StoredTableCell] = field(default_factory=list)


@dataclass
class StoredTable:
    table_id: str
    report_id: str
    title: str
    category: str
    page: int
    section_title: str
    section_path: List[str]
    row_count: int
    column_count: int
    rows: List[StoredTableRow]
    json_path: str
    html_path: str
    headers: List[str] = field(default_factory=list)
    data_rows: List[Dict[str, str]] = field(default_factory=list)
    sha256: str = ""
    parse_confidence: float = 1.0


class DocxTableStorage:
    """Save DOCX tables as HTML, JSON and graph-ready records."""

    TABLE_CAPTION = re.compile(r"^\s*表\s*\d", re.I)

    def __init__(
        self,
        document_path: str | Path,
        artifacts_root: str | Path,
        project_root: str | Path,
        report_id: str | None = None,
    ):
        self.document_path = Path(document_path).resolve()
        self.artifacts_root = Path(artifacts_root).resolve()
        self.project_root = Path(project_root).resolve()
        generated_id, self.document_hash = make_report_id(self.document_path)
        self.report_id = report_id or generated_id
        self.table_dir = (
            self.artifacts_root / self.report_id / "content" / "tables"
        )

    def store(self) -> List[StoredTable]:
        """Extract and save all tables, returning records for the Neo4j writer."""
        self.table_dir.mkdir(parents=True, exist_ok=True)
        document = Document(str(self.document_path))
        tracker = SectionTracker()
        page = 1
        previous_text = ""
        tables: List[StoredTable] = []

        for block in iter_docx_blocks(document):
            if hasattr(block, "text") and not isinstance(block, Table):
                page += page_break_count(block._element)
                text = block.text.strip()
                tracker.observe(block)
                if text:
                    previous_text = text
                continue

            if not isinstance(block, Table):
                continue

            table_index = len(tables) + 1
            raw_rows = [
                [cell.text.strip() for cell in row.cells]
                for row in block.rows
            ]
            parsed = TableParser.parse_table(raw_rows, table_index)
            table_id = f"{self.report_id}_table_{table_index:03d}"
            title = (
                previous_text
                if self.TABLE_CAPTION.match(previous_text)
                else (parsed.title if parsed else f"表{table_index}")
            )
            category = parsed.category if parsed else "unknown"
            headers = parsed.headers if parsed else self._fallback_headers(raw_rows)
            rows = self._build_rows(block, table_id, headers)

            json_file = self.table_dir / f"table_{table_index:03d}.json"
            html_file = self.table_dir / f"table_{table_index:03d}.html"
            record = StoredTable(
                table_id=table_id,
                report_id=self.report_id,
                title=title,
                category=category,
                page=page,
                section_title=tracker.title,
                section_path=tracker.path,
                row_count=len(block.rows),
                column_count=max((len(row.cells) for row in block.rows), default=0),
                rows=rows,
                json_path=relative_posix(json_file, self.project_root),
                html_path=relative_posix(html_file, self.project_root),
                headers=headers,
                data_rows=(
                    parsed.rows
                    if parsed
                    else self._fallback_data_rows(raw_rows, headers)
                ),
            )

            json_file.write_text(
                json.dumps(asdict(record), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            html_file.write_text(self._to_html(record), encoding="utf-8")
            record.sha256 = sha256_file(json_file)
            # Write the hash back to the final JSON for integrity checking.
            json_file.write_text(
                json.dumps(asdict(record), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tables.append(record)

        manifest = self.table_dir / "tables.json"
        manifest.write_text(
            json.dumps([asdict(item) for item in tables], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return tables

    def _build_rows(
        self,
        table: Table,
        table_id: str,
        headers: List[str],
    ) -> List[StoredTableRow]:
        """Record cell coordinates, horizontal merge spans and numeric-normalization results."""
        result: List[StoredTableRow] = []
        for row_index, row in enumerate(table.rows):
            row_record = StoredTableRow(
                row_id=f"{table_id}_row_{row_index:04d}",
                row_index=row_index,
                row_type="header" if row_index == 0 else "data",
            )
            seen_xml_cells = set()
            column_index = 0
            for cell in row.cells:
                xml_identity = id(cell._tc)
                if xml_identity in seen_xml_cells:
                    column_index += 1
                    continue
                seen_xml_cells.add(xml_identity)

                colspan = sum(1 for candidate in row.cells if candidate._tc is cell._tc)
                header = headers[column_index] if column_index < len(headers) else f"列{column_index + 1}"
                measurement = normalize_measurement(cell.text, header)
                value = measurement.get("value", cell.text.strip())
                row_record.cells.append(
                    StoredTableCell(
                        cell_id=f"{table_id}_cell_{row_index:04d}_{column_index:04d}",
                        row_index=row_index,
                        column_index=column_index,
                        raw_text=cell.text.strip(),
                        header=header,
                        header_path=header,
                        normalized_value=value,
                        unit=measurement.get("unit", ""),
                        is_numeric=bool(measurement.get("is_numeric")),
                        is_range=bool(measurement.get("is_range")),
                        minimum=measurement.get("min"),
                        maximum=measurement.get("max"),
                        rowspan=1,
                        colspan=max(1, colspan),
                    )
                )
                column_index += max(1, colspan)
            result.append(row_record)
        return result

    @staticmethod
    def _fallback_headers(raw_rows: List[List[str]]) -> List[str]:
        if not raw_rows:
            return []
        return [text.strip() or f"列{index + 1}" for index, text in enumerate(raw_rows[0])]

    @staticmethod
    def _fallback_data_rows(
        raw_rows: List[List[str]], headers: List[str]
    ) -> List[Dict[str, str]]:
        """Retain basic row/column mappings when header recognition fails."""
        result: List[Dict[str, str]] = []
        for raw_row in raw_rows[1:]:
            padded = list(raw_row[: len(headers)]) + [""] * max(
                0, len(headers) - len(raw_row)
            )
            if any(value.strip() for value in padded):
                result.append(dict(zip(headers, padded)))
        return result

    @staticmethod
    def _to_html(table: StoredTable) -> str:
        lines = [
            "<!doctype html>",
            '<html lang="zh-CN"><head><meta charset="utf-8">',
            f"<title>{html.escape(table.title)}</title>",
            "<style>body{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;}"
            "table{border-collapse:collapse;}th,td{border:1px solid #666;padding:6px 10px;}"
            "caption{font-weight:bold;margin-bottom:10px;}</style></head><body>",
            f"<table><caption>{html.escape(table.title)}</caption>",
        ]
        for row in table.rows:
            lines.append("<tr>")
            tag = "th" if row.row_type == "header" else "td"
            for cell in row.cells:
                attrs = ""
                if cell.rowspan > 1:
                    attrs += f' rowspan="{cell.rowspan}"'
                if cell.colspan > 1:
                    attrs += f' colspan="{cell.colspan}"'
                lines.append(f"<{tag}{attrs}>{html.escape(cell.raw_text)}</{tag}>")
            lines.append("</tr>")
        lines.extend(["</table>", "</body></html>"])
        return "\n".join(lines)


class Neo4jTableStorage:
    """Store tables as Report-Table-Row-Cell graph structures."""

    def __init__(self, graph):
        self.graph = graph

    def store(
        self,
        report_id: str,
        document_name: str,
        document_hash: str,
        tables: List[StoredTable],
    ) -> Dict[str, int]:
        ensure_content_constraints(self.graph)
        ensure_report_node(self.graph, report_id, document_name, document_hash)
        counts = {"tables": 0, "rows": 0, "cells": 0}

        for table in tables:
            self.graph.run(
                """
                MATCH (report:Report {report_id: $report_id})
                MERGE (table:Table {table_id: $table_id})
                SET table.title = $title,
                    table.category = $category,
                    table.page = $page,
                    table.section_title = $section_title,
                    table.section_path_json = $section_path_json,
                    table.row_count = $row_count,
                    table.column_count = $column_count,
                    table.json_path = $json_path,
                    table.html_path = $html_path,
                    table.sha256 = $sha256,
                    table.parse_confidence = $parse_confidence,
                    table.block_type = 'table'
                MERGE (report)-[:HAS_CONTENT]->(table)
                """,
                report_id=report_id,
                table_id=table.table_id,
                title=table.title,
                category=table.category,
                page=table.page,
                section_title=table.section_title,
                section_path_json=json.dumps(table.section_path, ensure_ascii=False),
                row_count=table.row_count,
                column_count=table.column_count,
                json_path=table.json_path,
                html_path=table.html_path,
                sha256=table.sha256,
                parse_confidence=table.parse_confidence,
            )
            counts["tables"] += 1

            row_payload = []
            cell_payload = []
            for row in table.rows:
                row_payload.append({
                    "row_id": row.row_id,
                    "table_id": table.table_id,
                    "row_index": row.row_index,
                    "row_type": row.row_type,
                })
                for cell in row.cells:
                    cell_payload.append({
                        "cell_id": cell.cell_id,
                        "row_id": row.row_id,
                        "row_index": cell.row_index,
                        "column_index": cell.column_index,
                        "raw_text": cell.raw_text,
                        "header": cell.header,
                        "header_path": cell.header_path,
                        "normalized_value_json": json.dumps(cell.normalized_value, ensure_ascii=False),
                        "unit": cell.unit,
                        "is_numeric": cell.is_numeric,
                        "is_range": cell.is_range,
                        "minimum": cell.minimum,
                        "maximum": cell.maximum,
                        "rowspan": cell.rowspan,
                        "colspan": cell.colspan,
                        "confidence": cell.confidence,
                    })

            if row_payload:
                self.graph.run(
                    """
                    UNWIND $items AS item
                    MATCH (table:Table {table_id: item.table_id})
                    MERGE (row:TableRow {row_id: item.row_id})
                    SET row.row_index = item.row_index, row.row_type = item.row_type
                    MERGE (table)-[:HAS_ROW]->(row)
                    """,
                    items=row_payload,
                )
            if cell_payload:
                self.graph.run(
                    """
                    UNWIND $items AS item
                    MATCH (row:TableRow {row_id: item.row_id})
                    MERGE (cell:TableCell {cell_id: item.cell_id})
                    SET cell.row_index = item.row_index,
                        cell.column_index = item.column_index,
                        cell.raw_text = item.raw_text,
                        cell.header = item.header,
                        cell.header_path = item.header_path,
                        cell.normalized_value_json = item.normalized_value_json,
                        cell.unit = item.unit,
                        cell.is_numeric = item.is_numeric,
                        cell.is_range = item.is_range,
                        cell.minimum = item.minimum,
                        cell.maximum = item.maximum,
                        cell.rowspan = item.rowspan,
                        cell.colspan = item.colspan,
                        cell.confidence = item.confidence
                    MERGE (row)-[:HAS_CELL]->(cell)
                    """,
                    items=cell_payload,
                )
            counts["rows"] += len(row_payload)
            counts["cells"] += len(cell_payload)

            # Table-event source_segment uses table_XXX; also support newer report-prefixed identifiers.
            short_id = table.table_id.rsplit("_table_", 1)[-1]
            legacy_id = f"table_{short_id}"
            self.graph.run(
                """
                MATCH (table:Table {table_id: $table_id})
                MATCH (event:Event)
                WHERE event.report_id = $report_id
                  AND event.source_segment IN [$table_id, $legacy_id]
                MERGE (event)-[:EXTRACTED_FROM]->(table)
                MERGE (table)-[:SUPPORTS]->(event)
                """,
                table_id=table.table_id,
                legacy_id=legacy_id,
                report_id=report_id,
            )

        return counts


class PdfTableStorage:
    """Extract PDF tables into the same storage representation used for DOCX."""

    def __init__(
        self,
        document_path: str | Path,
        artifacts_root: str | Path,
        project_root: str | Path,
        report_id: str | None = None,
    ):
        self.document_path = Path(document_path).resolve()
        self.artifacts_root = Path(artifacts_root).resolve()
        self.project_root = Path(project_root).resolve()
        generated_id, self.document_hash = make_report_id(self.document_path)
        self.report_id = report_id or generated_id
        self.table_dir = self.artifacts_root / self.report_id / "content" / "tables"

    def store(self) -> List[StoredTable]:
        try:
            import pdfplumber
        except ImportError as exc:
            raise ImportError("PDF表格处理需要安装 pdfplumber") from exc

        self.table_dir.mkdir(parents=True, exist_ok=True)
        tables: List[StoredTable] = []
        with pdfplumber.open(str(self.document_path)) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                for raw_table in page.extract_tables() or []:
                    if not raw_table:
                        continue
                    raw_rows = [
                        [(cell or "").strip() for cell in row]
                        for row in raw_table
                        if row and any((cell or "").strip() for cell in row)
                    ]
                    if not raw_rows:
                        continue
                    table_index = len(tables) + 1
                    parsed = TableParser.parse_table(raw_rows, table_index)
                    headers = parsed.headers if parsed else DocxTableStorage._fallback_headers(raw_rows)
                    title = parsed.title if parsed else f"第{page_number}页表格{table_index}"
                    table_id = f"{self.report_id}_table_{table_index:03d}"
                    rows = self._rows_from_raw(raw_rows, table_id, headers)
                    json_file = self.table_dir / f"table_{table_index:03d}.json"
                    html_file = self.table_dir / f"table_{table_index:03d}.html"
                    record = StoredTable(
                        table_id=table_id,
                        report_id=self.report_id,
                        title=title,
                        category=parsed.category if parsed else "unknown",
                        page=page_number,
                        section_title=f"第{page_number}页",
                        section_path=[f"第{page_number}页"],
                        row_count=len(raw_rows),
                        column_count=max((len(row) for row in raw_rows), default=0),
                        rows=rows,
                        json_path=relative_posix(json_file, self.project_root),
                        html_path=relative_posix(html_file, self.project_root),
                        headers=headers,
                        data_rows=(
                            parsed.rows
                            if parsed
                            else DocxTableStorage._fallback_data_rows(raw_rows, headers)
                        ),
                        parse_confidence=0.8,
                    )
                    json_file.write_text(
                        json.dumps(asdict(record), ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    html_file.write_text(DocxTableStorage._to_html(record), encoding="utf-8")
                    record.sha256 = sha256_file(json_file)
                    json_file.write_text(
                        json.dumps(asdict(record), ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    tables.append(record)

        (self.table_dir / "tables.json").write_text(
            json.dumps([asdict(item) for item in tables], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return tables

    @staticmethod
    def _rows_from_raw(
        raw_rows: List[List[str]],
        table_id: str,
        headers: List[str],
    ) -> List[StoredTableRow]:
        rows: List[StoredTableRow] = []
        for row_index, raw_row in enumerate(raw_rows):
            row = StoredTableRow(
                row_id=f"{table_id}_row_{row_index:04d}",
                row_index=row_index,
                row_type="header" if row_index == 0 else "data",
            )
            for column_index, raw_value in enumerate(raw_row):
                header = headers[column_index] if column_index < len(headers) else f"列{column_index + 1}"
                measurement = normalize_measurement(raw_value, header)
                row.cells.append(StoredTableCell(
                    cell_id=f"{table_id}_cell_{row_index:04d}_{column_index:04d}",
                    row_index=row_index,
                    column_index=column_index,
                    raw_text=raw_value,
                    header=header,
                    header_path=header,
                    normalized_value=measurement.get("value", raw_value),
                    unit=measurement.get("unit", ""),
                    is_numeric=bool(measurement.get("is_numeric")),
                    is_range=bool(measurement.get("is_range")),
                    minimum=measurement.get("min"),
                    maximum=measurement.get("max"),
                    confidence=0.8,
                ))
            rows.append(row)
        return rows
