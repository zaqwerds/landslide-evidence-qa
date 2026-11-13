# -*- coding: utf-8 -*-
"""Basic multimodal knowledge fusion for the unified processing pipeline."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple

from backend.models import ReportWorkspace
from backend.serialization import write_json
from extraction.event_extractor import Event, EventKnowledge


class BasicKnowledgeFusion:
    """Conservatively merge exact duplicates by event type and normalized name."""

    def fuse(
        self,
        workspace: ReportWorkspace,
        events: List[Event],
        knowledge: List[EventKnowledge],
    ) -> Tuple[List[Event], List[EventKnowledge], Dict[str, Any]]:
        representatives: Dict[Tuple[str, str], Event] = {}
        evidence: Dict[Tuple[str, str], List[str]] = {}

        for event in sorted(events, key=lambda item: (-float(item.confidence), item.event_id)):
            key = (event.event_type.value, self._normalize(event.name) or event.event_id)
            evidence.setdefault(key, []).append(event.source_segment or event.event_id)
            if key not in representatives:
                representatives[key] = event
                continue
            current = representatives[key]
            for attr_name, attr_value in event.attributes.items():
                if attr_name not in current.attributes or not current.attributes[attr_name]:
                    current.attributes[attr_name] = attr_value
            if len(event.description) > len(current.description):
                current.description = event.description

        fused_events = list(representatives.values())
        for key, event in representatives.items():
            event.attributes["证据ID列表"] = json.dumps(
                sorted(set(evidence[key])), ensure_ascii=False
            )

        seen_relations = set()
        fused_knowledge: List[EventKnowledge] = []
        for item in sorted(knowledge, key=lambda row: (-float(row.confidence), row.id)):
            relation = getattr(item.relation, "value", str(item.relation))
            key = (
                self._normalize(item.head_event),
                relation,
                self._normalize(item.tail_event),
            )
            if key in seen_relations:
                continue
            seen_relations.add(key)
            fused_knowledge.append(item)

        stats = {
            "input_events": len(events),
            "output_events": len(fused_events),
            "merged_events": len(events) - len(fused_events),
            "input_relations": len(knowledge),
            "output_relations": len(fused_knowledge),
            "merged_relations": len(knowledge) - len(fused_knowledge),
            "strategy": "event_type+normalized_exact_name",
        }
        write_json(
            workspace.run_dir / "03_fused_knowledge.json",
            {"events": fused_events, "knowledge": fused_knowledge, "stats": stats},
        )
        return fused_events, fused_knowledge, stats

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"[\s，。；：、,.;:（）()\[\]【】]+", "", value or "").lower()
