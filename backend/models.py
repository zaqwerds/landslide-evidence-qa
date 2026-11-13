# -*- coding: utf-8 -*-
"""Shared data models for backend processing stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class ReportWorkspace:
    report_id: str
    document_hash: str
    original_path: Path
    input_path: Path
    report_artifacts_dir: Path
    run_dir: Path
    source_name: str
    source_format: str


@dataclass
class TextBlock:
    block_id: str
    report_id: str
    text: str
    section_title: str = "未知章节"
    section_path: List[str] = field(default_factory=list)
    page: int = 0
    source_order: int = 0
    block_type: str = "text"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ContentBundle:
    report_id: str
    text_blocks: List[TextBlock] = field(default_factory=list)
    tables: List[Any] = field(default_factory=list)
    figures: List[Any] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
