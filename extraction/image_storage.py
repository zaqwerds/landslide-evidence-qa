# -*- coding: utf-8 -*-
"""Store original DOCX/PDF images, metadata and Neo4j Figure nodes."""

from __future__ import annotations

import json
import mimetypes
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional

from docx import Document
from docx.image.image import Image as DocxImage
from docx.oxml.ns import qn
from docx.table import Table

from extraction.content_storage_common import (
    SectionTracker,
    ensure_content_constraints,
    ensure_report_node,
    iter_docx_blocks,
    make_report_id,
    page_break_count,
    relative_posix,
    sha256_bytes,
)


@dataclass
class StoredFigure:
    figure_id: str
    report_id: str
    filename: str
    original_filename: str
    relative_path: str
    figure_type: str
    caption: str
    page: int
    section_title: str
    section_path: List[str]
    source_order: int
    width: int
    height: int
    mime_type: str
    sha256: str
    analysis_text: str = ""
    extraction_confidence: float = 1.0
    analysis_confidence: float = 0.0
    review_status: str = "unprocessed"


class DocxImageStorage:
    """Extract original embedded DOCX images and build a Figure inventory."""

    FIGURE_CAPTION = re.compile(
        r"^\s*(?:图|照片|附图)\s*[0-9一二三四五六七八九十]",
        re.I,
    )
    FIGURE_CAPTION_START = re.compile(
        r"(?:图|照片|附图)\s*[0-9一二三四五六七八九十]",
        re.I,
    )
    TYPE_PATTERNS = [
        (re.compile(r"剖面|断面"), "工程地质剖面图"),
        (re.compile(r"平面|分区|布置|范围|地形|地质图"), "平面图"),
        (re.compile(r"曲线|趋势|监测|位移|变化"), "统计图"),
        (re.compile(r"示意|流程|模型"), "示意图"),
        (re.compile(r"照片|全貌|裂缝|变形|鼓胀|滑坡体"), "现场照片"),
    ]

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
        self.figure_dir = (
            self.artifacts_root / self.report_id / "content" / "figures"
        )

    def store(self) -> List[StoredFigure]:
        self.figure_dir.mkdir(parents=True, exist_ok=True)
        document = Document(str(self.document_path))
        tracker = SectionTracker()
        page = 1
        figures: List[StoredFigure] = []
        pending_caption: List[StoredFigure] = []

        for source_order, block in enumerate(iter_docx_blocks(document), start=1):
            element = block._element
            if not isinstance(block, Table):
                page += page_break_count(element)
                text = block.text.strip()

                # Word often places a figure caption in a separate paragraph after the image.
                if text and self.FIGURE_CAPTION.match(text) and pending_caption:
                    captions = self._split_captions(text)
                    for index, figure in enumerate(pending_caption):
                        caption = (
                            captions[index]
                            if len(captions) == len(pending_caption)
                            else text
                        )
                        figure.caption = caption
                        figure.figure_type = self._classify(caption)
                    pending_caption = []

                tracker.observe(block)
                inline_caption = text if self.FIGURE_CAPTION.match(text) else ""
            else:
                inline_caption = ""

            block_figures = self._extract_from_element(
                document=document,
                element=element,
                page=page,
                section_title=tracker.title,
                section_path=tracker.path,
                source_order=source_order,
                start_index=len(figures) + 1,
                caption=inline_caption,
            )
            figures.extend(block_figures)
            if block_figures and not inline_caption:
                pending_caption = block_figures

        manifest = self.figure_dir / "figures.json"
        manifest.write_text(
            json.dumps([asdict(item) for item in figures], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return figures

    def _extract_from_element(
        self,
        document,
        element,
        page: int,
        section_title: str,
        section_path: List[str],
        source_order: int,
        start_index: int,
        caption: str,
    ) -> List[StoredFigure]:
        figures: List[StoredFigure] = []
        seen_relationships = set()
        try:
            # Support both modern DrawingML (a:blip/r:embed) and legacy
            # Word VML (v:imagedata/r:id); older templates remain common in geological reports.
            image_references = element.xpath(
                ".//*[local-name()='blip' or local-name()='imagedata']"
            )
        except Exception:
            image_references = []

        for offset, image_reference in enumerate(image_references):
            relationship_id = (
                image_reference.get(qn("r:embed"))
                or image_reference.get(qn("r:id"))
                or image_reference.get(qn("r:link"))
            )
            if not relationship_id or relationship_id in seen_relationships:
                continue
            seen_relationships.add(relationship_id)
            part = document.part.related_parts.get(relationship_id)
            if part is None or not hasattr(part, "blob"):
                continue

            data = bytes(part.blob)
            source_name = PurePosixPath(str(part.partname)).name
            suffix = Path(source_name).suffix.lower()
            mime_type = getattr(part, "content_type", "") or mimetypes.guess_type(source_name)[0] or "application/octet-stream"
            if not suffix:
                suffix = mimetypes.guess_extension(mime_type) or ".bin"

            figure_number = start_index + offset
            filename = f"figure_p{page:03d}_{figure_number:03d}{suffix}"
            target = self.figure_dir / filename
            target.write_bytes(data)
            width, height = self._image_size(data)
            figure_id = f"{self.report_id}_figure_{figure_number:04d}"
            figures.append(
                StoredFigure(
                    figure_id=figure_id,
                    report_id=self.report_id,
                    filename=filename,
                    original_filename=source_name,
                    relative_path=relative_posix(target, self.project_root),
                    figure_type=self._classify(caption),
                    caption=caption,
                    page=page,
                    section_title=section_title,
                    section_path=list(section_path),
                    source_order=source_order,
                    width=width,
                    height=height,
                    mime_type=mime_type,
                    sha256=sha256_bytes(data),
                )
            )
        return figures

    @classmethod
    def _classify(cls, caption: str) -> str:
        for pattern, figure_type in cls.TYPE_PATTERNS:
            if pattern.search(caption or ""):
                return figure_type
        return "未分类图片"

    @classmethod
    def _split_captions(cls, text: str) -> List[str]:
        """Split multiple figure captions occurring in the same paragraph."""
        starts = [match.start() for match in cls.FIGURE_CAPTION_START.finditer(text)]
        if len(starts) <= 1:
            return [text.strip()] if text.strip() else []
        starts.append(len(text))
        return [
            text[starts[index] : starts[index + 1]].strip(" ｜|\t")
            for index in range(len(starts) - 1)
            if text[starts[index] : starts[index + 1]].strip(" ｜|\t")
        ]

    @staticmethod
    def _image_size(data: bytes) -> tuple[int, int]:
        try:
            image = DocxImage.from_blob(data)
            return int(image.px_width or 0), int(image.px_height or 0)
        except Exception:
            return 0, 0


class Neo4jImageStorage:
    """Store figure metadata as Report-HAS_CONTENT-Figure structures."""

    def __init__(self, graph):
        self.graph = graph

    def store(
        self,
        report_id: str,
        document_name: str,
        document_hash: str,
        figures: List[StoredFigure],
    ) -> Dict[str, int]:
        ensure_content_constraints(self.graph)
        ensure_report_node(self.graph, report_id, document_name, document_hash)
        payload = [
            {
                "figure_id": item.figure_id,
                "report_id": report_id,
                "filename": item.filename,
                "original_filename": item.original_filename,
                "relative_path": item.relative_path,
                "figure_type": item.figure_type,
                "caption": item.caption,
                "page": item.page,
                "section_title": item.section_title,
                "section_path_json": json.dumps(item.section_path, ensure_ascii=False),
                "source_order": item.source_order,
                "width": item.width,
                "height": item.height,
                "mime_type": item.mime_type,
                "sha256": item.sha256,
                "analysis_text": item.analysis_text,
                "extraction_confidence": item.extraction_confidence,
                "analysis_confidence": item.analysis_confidence,
                "review_status": item.review_status,
            }
            for item in figures
        ]
        if payload:
            self.graph.run(
                """
                UNWIND $items AS item
                MATCH (report:Report {report_id: item.report_id})
                MERGE (figure:Figure {figure_id: item.figure_id})
                SET figure.filename = item.filename,
                    figure.original_filename = item.original_filename,
                    figure.relative_path = item.relative_path,
                    figure.figure_type = item.figure_type,
                    figure.caption = item.caption,
                    figure.page = item.page,
                    figure.section_title = item.section_title,
                    figure.section_path_json = item.section_path_json,
                    figure.source_order = item.source_order,
                    figure.width = item.width,
                    figure.height = item.height,
                    figure.mime_type = item.mime_type,
                    figure.sha256 = item.sha256,
                    figure.analysis_text = item.analysis_text,
                    figure.extraction_confidence = item.extraction_confidence,
                    figure.analysis_confidence = item.analysis_confidence,
                    figure.review_status = item.review_status,
                    figure.block_type = 'figure'
                MERGE (report)-[:HAS_CONTENT]->(figure)
                """,
                items=payload,
            )
        return {"figures": len(payload)}

    def link_event_evidence(self, figure_id: str, event_ids: List[str]) -> int:
        """Link extracted events back to their original Figure evidence."""
        if not event_ids:
            return 0
        self.graph.run(
            """
            MATCH (figure:Figure {figure_id: $figure_id})
            MATCH (event:Event)
            WHERE event.event_id IN $event_ids
            MERGE (event)-[:EXTRACTED_FROM]->(figure)
            MERGE (figure)-[:SUPPORTS]->(event)
            """,
            figure_id=figure_id,
            event_ids=event_ids,
        )
        return len(event_ids)


class PdfImageStorage:
    """Extract PDF image regions; save whole scanned pages when no searchable text is available."""

    def __init__(
        self,
        document_path: str | Path,
        artifacts_root: str | Path,
        project_root: str | Path,
        report_id: str | None = None,
        resolution: int = 150,
    ):
        self.document_path = Path(document_path).resolve()
        self.artifacts_root = Path(artifacts_root).resolve()
        self.project_root = Path(project_root).resolve()
        generated_id, self.document_hash = make_report_id(self.document_path)
        self.report_id = report_id or generated_id
        self.resolution = resolution
        self.figure_dir = self.artifacts_root / self.report_id / "content" / "figures"

    def store(self) -> List[StoredFigure]:
        try:
            import pdfplumber
        except ImportError as exc:
            raise ImportError("PDF图片处理需要安装 pdfplumber") from exc

        self.figure_dir.mkdir(parents=True, exist_ok=True)
        figures: List[StoredFigure] = []
        with pdfplumber.open(str(self.document_path)) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                text = (page.extract_text() or "").strip()
                image_boxes = page.images or []
                if image_boxes:
                    for image_box in image_boxes:
                        record = self._render_region(
                            page,
                            page_number,
                            image_box,
                            len(figures) + 1,
                            "PDF图片区域",
                        )
                        if record:
                            figures.append(record)
                elif len(text) < 20:
                    # If a scanned page has no separate image object, save the entire page for viewing.
                    record = self._render_region(
                        page,
                        page_number,
                        None,
                        len(figures) + 1,
                        "扫描页面",
                    )
                    if record:
                        figures.append(record)

        (self.figure_dir / "figures.json").write_text(
            json.dumps([asdict(item) for item in figures], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return figures

    def _render_region(
        self,
        page,
        page_number: int,
        image_box,
        figure_number: int,
        figure_type: str,
    ) -> Optional[StoredFigure]:
        try:
            target_page = page
            if image_box:
                bbox = (
                    max(0, float(image_box.get("x0", 0))),
                    max(0, float(image_box.get("top", 0))),
                    min(float(page.width), float(image_box.get("x1", page.width))),
                    min(float(page.height), float(image_box.get("bottom", page.height))),
                )
                if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                    return None
                target_page = page.crop(bbox)
            rendered = target_page.to_image(resolution=self.resolution).original
            filename = f"figure_p{page_number:03d}_{figure_number:03d}.png"
            target = self.figure_dir / filename
            rendered.save(target, format="PNG")
            data = target.read_bytes()
            return StoredFigure(
                figure_id=f"{self.report_id}_figure_{figure_number:04d}",
                report_id=self.report_id,
                filename=filename,
                original_filename=f"page_{page_number}.pdf",
                relative_path=relative_posix(target, self.project_root),
                figure_type=figure_type,
                caption=f"第{page_number}页{figure_type}",
                page=page_number,
                section_title=f"第{page_number}页",
                section_path=[f"第{page_number}页"],
                source_order=page_number,
                width=int(getattr(rendered, "width", 0)),
                height=int(getattr(rendered, "height", 0)),
                mime_type="image/png",
                sha256=sha256_bytes(data),
                extraction_confidence=0.7,
                review_status="unprocessed",
            )
        except Exception:
            return None
