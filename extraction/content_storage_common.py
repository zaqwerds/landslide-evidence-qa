# -*- coding: utf-8 -*-
"""Shared storage utilities for table and figure carriers."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterator, List, Tuple, Union

from docx.document import Document as _Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph


DocxBlock = Union[Paragraph, Table]


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Compute a file SHA-256 incrementally without loading the entire report into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_report_id(document_path: Path) -> Tuple[str, str]:
    """Derive a stable report identifier and complete hash from file contents."""
    document_hash = sha256_file(document_path)
    return f"report_{document_hash[:12]}", document_hash


def relative_posix(path: Path, project_root: Path) -> str:
    """Generate a portable POSIX-style relative path."""
    return path.resolve().relative_to(project_root.resolve()).as_posix()


def iter_docx_blocks(document: _Document) -> Iterator[DocxBlock]:
    """Iterate paragraphs and tables in their actual DOCX body order."""
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def page_break_count(element) -> int:
    """Count explicit or recorded rendered page breaks; page numbers remain approximate."""
    try:
        rendered = len(element.xpath(".//w:lastRenderedPageBreak"))
        explicit = len(element.xpath(".//w:br[@w:type='page']"))
        return rendered + explicit
    except Exception:
        return 0


class SectionTracker:
    """Track the current section path while traversing a DOCX document."""

    NUMBERED_HEADING = re.compile(r"^(\d+(?:\.\d+)*)[\s、．.]+(.+)$")
    CHINESE_HEADING = re.compile(r"^第[一二三四五六七八九十百千]+[章节]")

    def __init__(self):
        self._levels: List[str] = []

    @property
    def path(self) -> List[str]:
        return list(self._levels)

    @property
    def title(self) -> str:
        return self._levels[-1] if self._levels else "未知章节"

    def observe(self, paragraph: Paragraph) -> None:
        text = paragraph.text.strip()
        if not text:
            return

        style_name = getattr(getattr(paragraph, "style", None), "name", "") or ""
        style_match = re.search(r"Heading\s*(\d+)|标题\s*(\d+)", style_name, re.I)
        if style_match:
            level = int(style_match.group(1) or style_match.group(2) or 1)
            self._set(level, text)
            return

        number_match = self.NUMBERED_HEADING.match(text)
        if number_match and len(text) <= 100:
            level = number_match.group(1).count(".") + 1
            self._set(level, text)
        elif self.CHINESE_HEADING.match(text) and len(text) <= 100:
            self._set(1, text)

    def _set(self, level: int, title: str) -> None:
        level = max(1, level)
        if len(self._levels) >= level:
            self._levels = self._levels[: level - 1]
        while len(self._levels) < level - 1:
            self._levels.append("未命名章节")
        self._levels.append(title)


def ensure_report_node(graph, report_id: str, document_name: str, document_hash: str):
    """Create or update the Report node shared by tables and figures."""
    graph.run(
        """
        MERGE (report:Report {report_id: $report_id})
        SET report.name = $document_name,
            report.sha256 = $document_hash,
            report.updated_at = datetime()
        """,
        report_id=report_id,
        document_name=document_name,
        document_hash=document_hash,
    )


def ensure_content_constraints(graph) -> None:
    """Create uniqueness constraints for multimodal content nodes."""
    statements = [
        "CREATE CONSTRAINT report_id_unique IF NOT EXISTS FOR (n:Report) REQUIRE n.report_id IS UNIQUE",
        "CREATE CONSTRAINT table_id_unique IF NOT EXISTS FOR (n:Table) REQUIRE n.table_id IS UNIQUE",
        "CREATE CONSTRAINT table_row_id_unique IF NOT EXISTS FOR (n:TableRow) REQUIRE n.row_id IS UNIQUE",
        "CREATE CONSTRAINT table_cell_id_unique IF NOT EXISTS FOR (n:TableCell) REQUIRE n.cell_id IS UNIQUE",
        "CREATE CONSTRAINT figure_id_unique IF NOT EXISTS FOR (n:Figure) REQUIRE n.figure_id IS UNIQUE",
    ]
    for statement in statements:
        graph.run(statement)
