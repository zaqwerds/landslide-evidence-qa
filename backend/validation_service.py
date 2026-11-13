# -*- coding: utf-8 -*-
"""Coordinate quality checks and accepted, review and rejected categories."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from backend.models import ReportWorkspace
from backend.serialization import write_json
from extraction.event_extractor import Event, EventKnowledge
from extraction.two_phase_validator import TwoPhaseValidator
from schema.ontology_loader import OntologyLoader


class KnowledgeValidationService:
    def __init__(self, ontology_loader: OntologyLoader, min_confidence: float = 0.3):
        self.validator = TwoPhaseValidator(ontology_loader)
        self.min_confidence = min_confidence

    def validate(
        self,
        workspace: ReportWorkspace,
        events: List[Event],
        knowledge: List[EventKnowledge],
    ) -> Tuple[List[Event], List[EventKnowledge], Dict[str, Any]]:
        semantic_report, schema_report = self.validator.validate(events, knowledge)
        buckets = self.validator.classify_events(
            events,
            knowledge,
            min_confidence=self.min_confidence,
            semantic_report=semantic_report,
            schema_report=schema_report,
        )
        accepted_events = buckets["accepted_events"]
        accepted_knowledge = buckets["accepted_knowledge"]
        result = {
            "semantic_report": semantic_report,
            "schema_report": schema_report,
            "accepted_events": accepted_events,
            "accepted_knowledge": accepted_knowledge,
            "review_events": buckets["review_events"],
            "review_knowledge": buckets["review_knowledge"],
            "rejected_events": buckets["rejected_events"],
            "rejected_knowledge": buckets["rejected_knowledge"],
            "event_decisions": buckets["event_decisions"],
            "relation_decisions": buckets["relation_decisions"],
            "counts": {
                "accepted_events": len(accepted_events),
                "accepted_relations": len(accepted_knowledge),
                "review_events": len(buckets["review_events"]),
                "review_relations": len(buckets["review_knowledge"]),
                "rejected_events": len(buckets["rejected_events"]),
                "rejected_relations": len(buckets["rejected_knowledge"]),
            },
        }
        write_json(workspace.run_dir / "04_validation.json", result)
        write_json(
            workspace.run_dir / "05_accepted_knowledge.json",
            {"events": accepted_events, "knowledge": accepted_knowledge},
        )
        return accepted_events, accepted_knowledge, result
