# -*- coding: utf-8 -*-
"""Parse DOCX/PDF reports into text, table and figure carriers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

from backend.models import ContentBundle, ReportWorkspace, TextBlock
from backend.serialization import write_json
from extraction.image_storage import DocxImageStorage, PdfImageStorage
from extraction.segmenter import StructureAwareSegmenter
from extraction.table_storage import DocxTableStorage, PdfTableStorage


class UnifiedDocumentParser:
    def __init__(self, project_root: str | Path, max_segment_length: int = 1500):
        self.project_root = Path(project_root).resolve()
        self.artifacts_root = self.project_root / "artifacts"
        self.max_segment_length = max_segment_length

    def parse(
        self,
        workspace: ReportWorkspace,
        max_segments: int = 0,
    ) -> ContentBundle:
        if workspace.source_format == "docx":
            bundle = self._parse_docx(workspace, max_segments)
        elif workspace.source_format == "pdf":
            bundle = self._parse_pdf(workspace, max_segments)
        else:
            raise ValueError(f"不支持的报告格式: {workspace.source_format}")

        bundle.stats = {
            "text_blocks": len(bundle.text_blocks),
            "tables": len(bundle.tables),
            "figures": len(bundle.figures),
            "warnings": len(bundle.warnings),
        }
        write_json(workspace.run_dir / "01_document_blocks.json", bundle)
        return bundle

    def _parse_docx(
        self,
        workspace: ReportWorkspace,
        max_segments: int,
    ) -> ContentBundle:
        segmenter = StructureAwareSegmenter(
            str(workspace.input_path), max_segment_len=self.max_segment_length
        )
        segments = segmenter.segment()
        if max_segments > 0:
            segments = segments[:max_segments]
        text_blocks = [
            TextBlock(
                block_id=f"{workspace.report_id}_{segment.segment_id}",
                report_id=workspace.report_id,
                text=segment.content,
                section_title=segment.section_title,
                section_path=list(segment.section_path),
                page=segment.page_number,
                source_order=index,
                metadata={"legacy_segment_id": segment.segment_id},
            )
            for index, segment in enumerate(segments, start=1)
        ]

        table_store = DocxTableStorage(
            workspace.input_path,
            self.artifacts_root,
            self.project_root,
            workspace.report_id,
        )
        image_store = DocxImageStorage(
            workspace.input_path,
            self.artifacts_root,
            self.project_root,
            workspace.report_id,
        )
        return ContentBundle(
            report_id=workspace.report_id,
            text_blocks=text_blocks,
            tables=table_store.store(),
            figures=image_store.store(),
        )

    def _parse_pdf(
        self,
        workspace: ReportWorkspace,
        max_segments: int,
    ) -> ContentBundle:
        try:
            import pdfplumber
        except ImportError as exc:
            raise ImportError("PDF解析需要安装 pdfplumber") from exc

        text_blocks: List[TextBlock] = []
        warnings: List[str] = []
        with pdfplumber.open(str(workspace.input_path)) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                page_text = (page.extract_text() or "").strip()
                if not page_text:
                    warnings.append(f"第{page_number}页没有可检索文字，仅保存页面图像")
                    continue
                for chunk in self._split_pdf_text(page_text):
                    block_index = len(text_blocks) + 1
                    text_blocks.append(TextBlock(
                        block_id=f"{workspace.report_id}_pdf_text_{block_index:05d}",
                        report_id=workspace.report_id,
                        text=chunk,
                        section_title=f"第{page_number}页",
                        section_path=[f"第{page_number}页"],
                        page=page_number,
                        source_order=block_index,
                    ))
                    if max_segments > 0 and len(text_blocks) >= max_segments:
                        break
                if max_segments > 0 and len(text_blocks) >= max_segments:
                    break

        table_store = PdfTableStorage(
            workspace.input_path,
            self.artifacts_root,
            self.project_root,
            workspace.report_id,
        )
        image_store = PdfImageStorage(
            workspace.input_path,
            self.artifacts_root,
            self.project_root,
            workspace.report_id,
        )
        return ContentBundle(
            report_id=workspace.report_id,
            text_blocks=text_blocks,
            tables=table_store.store(),
            figures=image_store.store(),
            warnings=warnings,
        )

    def _split_pdf_text(self, text: str) -> List[str]:
        paragraphs = [item.strip() for item in re.split(r"\n\s*\n|(?<=。)\s*\n", text) if item.strip()]
        chunks: List[str] = []
        current = ""
        for paragraph in paragraphs:
            if len(current) + len(paragraph) + 1 <= self.max_segment_length:
                current = f"{current}\n{paragraph}".strip()
            else:
                if current:
                    chunks.append(current)
                while len(paragraph) > self.max_segment_length:
                    chunks.append(paragraph[: self.max_segment_length])
                    paragraph = paragraph[self.max_segment_length :]
                current = paragraph
        if current:
            chunks.append(current)
        return chunks or ([text[: self.max_segment_length]] if text else [])
