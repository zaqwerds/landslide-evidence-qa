# -*- coding: utf-8 -*-
"""Shared QA data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List


@dataclass
class QueryAnalysis:
    question: str
    modalities: List[str]
    intent: str
    keywords: List[str] = field(default_factory=list)
    explicit_table_ref: str = ""
    explicit_figure_ref: str = ""


@dataclass
class Evidence:
    evidence_id: str
    modality: str
    source_id: str
    title: str
    snippet: str
    path: str = ""
    score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QAResult:
    question: str
    answer: str
    analysis: QueryAnalysis
    evidence: List[Evidence]
    cypher_queries: List[str] = field(default_factory=list)
    used_llm: bool = False
    elapsed_seconds: float = 0.0
    error: str = ""
    retrieval_info: Dict[str, Any] = field(default_factory=dict)
    generation_info: Dict[str, Any] = field(default_factory=dict)


def collect_media_supports(evidence_items: Iterable[Evidence]) -> List[Dict[str, Any]]:
    """Collect tables and figures from direct evidence and event provenance, preserving order and removing duplicates."""
    supports: List[Dict[str, Any]] = []
    seen = set()

    def add(kind: str, source_id: str, title: str, path: str) -> None:
        key = (kind, source_id or path)
        if not key[1] or key in seen:
            return
        seen.add(key)
        supports.append({
            "kind": kind,
            "source_id": source_id,
            "title": title,
            "path": path,
        })

    for evidence in evidence_items:
        if evidence.modality == "table":
            add("table", evidence.source_id, evidence.title, evidence.path)
        elif evidence.modality == "figure":
            add("figure", evidence.source_id, evidence.title, evidence.path)

        for source in evidence.metadata.get("sources", []) or []:
            labels = set(source.get("labels") or [])
            properties = source.get("properties") or {}
            if "Table" in labels:
                add(
                    "table",
                    str(properties.get("table_id") or ""),
                    str(properties.get("title") or "表格证据"),
                    str(properties.get("html_path") or properties.get("json_path") or ""),
                )
            elif "Figure" in labels:
                add(
                    "figure",
                    str(properties.get("figure_id") or ""),
                    str(properties.get("caption") or properties.get("filename") or "图片证据"),
                    str(properties.get("relative_path") or ""),
                )
    return supports
