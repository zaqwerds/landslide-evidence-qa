# -*- coding: utf-8 -*-
"""Ingest external reports, derive content identifiers and manage report workspaces."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from backend.models import ReportWorkspace
from backend.serialization import write_json
from extraction.content_storage_common import make_report_id


class ReportIngestor:
    SUPPORTED_FORMATS = {".docx", ".pdf"}

    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()
        self.input_root = self.project_root / "input"
        self.artifacts_root = self.project_root / "artifacts"
        self.output_root = self.project_root / "output"

    def ingest(self, external_path: str | Path) -> ReportWorkspace:
        source = Path(external_path).resolve()
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"外部报告不存在: {source}")
        suffix = source.suffix.lower()
        if suffix not in self.SUPPORTED_FORMATS:
            supported = ", ".join(sorted(self.SUPPORTED_FORMATS))
            raise ValueError(f"暂不支持 {suffix or '无扩展名'}，当前支持: {supported}")

        report_id, document_hash = make_report_id(source)
        report_input_dir = self.input_root / report_id
        report_artifacts_dir = self.artifacts_root / report_id
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        run_dir = self.output_root / report_id / "runs" / run_id
        report_input_dir.mkdir(parents=True, exist_ok=True)
        report_artifacts_dir.mkdir(parents=True, exist_ok=True)
        run_dir.mkdir(parents=True, exist_ok=False)

        input_path = report_input_dir / f"source{suffix}"
        if source != input_path:
            if not input_path.exists() or make_report_id(input_path)[1] != document_hash:
                shutil.copy2(source, input_path)

        workspace = ReportWorkspace(
            report_id=report_id,
            document_hash=document_hash,
            original_path=source,
            input_path=input_path,
            report_artifacts_dir=report_artifacts_dir,
            run_dir=run_dir,
            source_name=source.name,
            source_format=suffix.lstrip("."),
        )
        write_json(
            run_dir / "00_ingest.json",
            {
                "workspace": workspace,
                "status": "ingested",
            },
        )
        return workspace
