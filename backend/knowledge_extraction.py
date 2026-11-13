# -*- coding: utf-8 -*-
"""Coordinate knowledge extraction from text, tables and figure metadata."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple

from backend.models import ContentBundle, ReportWorkspace
from backend.serialization import write_json
from extraction.event_extractor import (
    Event,
    EventKnowledge,
    EventType,
    OntologyGuidedEventExtractor,
)
from extraction.rule_extractor import RuleBasedExtractor
from extraction.table_extractor import TableExtractor
from schema.ontology_loader import OntologyLoader


class KnowledgeExtractionService:
    def __init__(
        self,
        ontology_loader: OntologyLoader,
        mode: str = "offline",
        provider: str = "deepseek",
        api_base: str | None = None,
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        timeout_seconds: int = 120,
    ):
        self.ontology_loader = ontology_loader
        self.mode = mode
        self.provider = provider
        self.api_base = api_base
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_seconds = timeout_seconds

    def extract(
        self,
        workspace: ReportWorkspace,
        bundle: ContentBundle,
    ) -> Tuple[List[Event], List[EventKnowledge], Dict[str, Any]]:
        text_events, text_knowledge, text_stats = self._extract_text(bundle)
        table_events, table_knowledge, table_stats = self._extract_tables(
            workspace, bundle
        )
        figure_events, figure_knowledge, figure_stats = self._extract_figures(bundle)

        events = text_events + table_events + figure_events
        knowledge = text_knowledge + table_knowledge + figure_knowledge
        stats = {
            "text": text_stats,
            "table": table_stats,
            "figure": figure_stats,
            "total_events": len(events),
            "total_relations": len(knowledge),
        }
        write_json(
            workspace.run_dir / "02_multimodal_knowledge.json",
            {"events": events, "knowledge": knowledge, "stats": stats},
        )
        return events, knowledge, stats

    def _extract_text(
        self,
        bundle: ContentBundle,
    ) -> Tuple[List[Event], List[EventKnowledge], Dict[str, Any]]:
        events: List[Event] = []
        knowledge: List[EventKnowledge] = []
        if self.mode == "offline":
            extractor = RuleBasedExtractor()
            for block in bundle.text_blocks:
                result = extractor.extract_from_text(
                    block.text,
                    block.section_title,
                    block.block_id,
                )
                events.extend(result.events)
                knowledge.extend(result.knowledge)
            return events, knowledge, extractor.get_stats()

        key_name = "OPENAI_API_KEY" if self.provider == "openai" else "DEEPSEEK_API_KEY"
        extractor = OntologyGuidedEventExtractor(
            llm_provider=self.provider,
            api_key=os.environ.get(key_name, ""),
            api_base=self.api_base,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout_seconds=self.timeout_seconds,
            ontology_loader=self.ontology_loader,
        )
        for block in bundle.text_blocks:
            result = extractor.extract_from_segment(
                block.text,
                block.section_title,
                block.block_id,
            )
            events.extend(result.events)
            knowledge.extend(result.knowledge)
        return events, knowledge, extractor.get_stats()

    def _extract_tables(
        self,
        workspace: ReportWorkspace,
        bundle: ContentBundle,
    ) -> Tuple[List[Event], List[EventKnowledge], Dict[str, Any]]:
        extractor = TableExtractor(verbose=False)
        result = extractor.extract_from_tables(bundle.tables, workspace.source_name)
        for event in result.events:
            event.event_id = f"{workspace.report_id}_table_{event.event_id}"
        for item in result.knowledge:
            item.id = f"{workspace.report_id}_table_{item.id}"
        stats = {
            "tables_parsed": result.tables_parsed,
            "tables_skipped": result.tables_skipped,
            "events": len(result.events),
            "relations": len(result.knowledge),
            "details": result.table_details,
        }
        return result.events, result.knowledge, stats

    def _extract_figures(
        self,
        bundle: ContentBundle,
    ) -> Tuple[List[Event], List[EventKnowledge], Dict[str, Any]]:
        events: List[Event] = []
        for figure in bundle.figures:
            description_parts = [
                figure.caption,
            ]
            description = "；".join(item for item in description_parts if item)
            if not description:
                description = f"报告第{figure.page}页包含一项{figure.figure_type}"
            event = Event(
                event_id=f"{figure.figure_id}_observation",
                event_type=EventType.OBSERVATION,
                name=figure.caption or f"第{figure.page}页{figure.figure_type}",
                description=description,
                attributes={
                    "内容模态": "图片",
                    "图片类型": figure.figure_type,
                    "图片路径": figure.relative_path,
                },
                source_segment=figure.figure_id,
                source_text=description[:500],
                confidence=0.8 if figure.caption else 0.65,
            )
            events.append(event)
        return events, [], {
            "figures": len(bundle.figures),
            "events": len(events),
        }
