# -*- coding: utf-8 -*-
"""Store reports, carriers, events and provenance relationships in Neo4j."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from backend.models import ContentBundle, ReportWorkspace
from backend.serialization import write_json
from extraction.event_builder import EventKnowledgeBuilder
from extraction.event_extractor import Event, EventKnowledge
from extraction.image_storage import Neo4jImageStorage
from extraction.table_storage import Neo4jTableStorage
from extraction.content_storage_common import ensure_content_constraints, ensure_report_node
from schema.ontology_loader import OntologyLoader


# Instance-layer labels cleared before writing a new report in single-report mode.
# Exclude SchemaClass and ontology classes to preserve the schema layer.
INSTANCE_LABELS = (
    "Report",
    "TextBlock",
    "Table",
    "TableRow",
    "TableCell",
    "Figure",
    "Event",
    "HyperEdge",
    "Property",
)


def clear_instance_graph(graph) -> int:
    """Delete all report and knowledge instances while preserving ontology and schema nodes."""
    label_condition = " OR ".join(f"n:`{label}`" for label in INSTANCE_LABELS)
    deleted = graph.run(
        f"""
        MATCH (n)
        WHERE {label_condition}
        WITH n
        DETACH DELETE n
        RETURN count(*) AS deleted
        """
    ).evaluate()
    return int(deleted or 0)


def clear_report_graph(graph, report_id: str) -> int:
    """Replace only the specified report and its dependent table and event instances."""
    deleted = graph.run(
        """
        MATCH (report:Report {report_id: $report_id})
        OPTIONAL MATCH (report)-[:HAS_CONTENT|HAS_KNOWLEDGE]->(direct)
        OPTIONAL MATCH (direct)-[:HAS_ROW|HAS_PROPERTIES|PART_OF_CHAIN]->(child)
        OPTIONAL MATCH (child)-[:HAS_CELL|HAS_VALUE]->(grandchild)
        WITH collect(DISTINCT grandchild) + collect(DISTINCT child)
             + collect(DISTINCT direct) + collect(DISTINCT report) AS nodes
        UNWIND nodes AS node
        WITH DISTINCT node WHERE node IS NOT NULL
        DETACH DELETE node
        RETURN count(*) AS deleted
        """,
        report_id=report_id,
    ).evaluate()
    return int(deleted or 0)


class UnifiedNeo4jStorage:
    def __init__(
        self,
        ontology_loader: OntologyLoader,
        uri: str,
        user: str,
        password: str,
        clear_events: bool = True,
    ):
        self.clear_existing_instances = clear_events
        # The unified storage layer clears instances; EventKnowledgeBuilder must not clear events again.
        self.builder = EventKnowledgeBuilder(
            neo4j_uri=uri,
            neo4j_user=user,
            neo4j_password=password,
            ontology_loader=ontology_loader,
        )
        self.graph = self.builder.graph

    def store(
        self,
        workspace: ReportWorkspace,
        bundle: ContentBundle,
        events: List[Event],
        knowledge: List[EventKnowledge],
    ) -> Dict[str, Any]:
        cleared_instance_nodes = 0
        if self.clear_existing_instances:
            cleared_instance_nodes = clear_report_graph(self.graph, workspace.report_id)

        ensure_content_constraints(self.graph)
        self._ensure_text_constraint()
        ensure_report_node(
            self.graph,
            workspace.report_id,
            workspace.source_name,
            workspace.document_hash,
        )

        self.builder.build(events, knowledge, {})
        self._link_report_to_events(workspace.report_id, events)
        schema_links = self.builder.link_to_schema_layer(events, {})
        timeline_relations = self.builder.create_event_timeline(events, {})
        text_stats = self._store_text_blocks(workspace, bundle, events)
        table_stats = Neo4jTableStorage(self.graph).store(
            workspace.report_id,
            workspace.source_name,
            workspace.document_hash,
            bundle.tables,
        )
        figure_stats = Neo4jImageStorage(self.graph).store(
            workspace.report_id,
            workspace.source_name,
            workspace.document_hash,
            bundle.figures,
        )
        self._link_figures_to_events(bundle)

        stats = self.builder.get_stats()
        stats.update({
            "cleared_instance_nodes": cleared_instance_nodes,
            "schema_links": schema_links,
            "timeline_relations": timeline_relations,
            "text_content": text_stats,
            "table_content": table_stats,
            "figure_content": figure_stats,
        })
        write_json(workspace.run_dir / "06_neo4j_result.json", stats)
        return stats

    def _ensure_text_constraint(self) -> None:
        self.graph.run(
            "CREATE CONSTRAINT text_block_id_unique IF NOT EXISTS "
            "FOR (n:TextBlock) REQUIRE n.block_id IS UNIQUE"
        )

    def _store_text_blocks(
        self,
        workspace: ReportWorkspace,
        bundle: ContentBundle,
        events: List[Event],
    ) -> Dict[str, int]:
        payload = [{
            "report_id": workspace.report_id,
            "block_id": block.block_id,
            "text": block.text,
            "section_title": block.section_title,
            "section_path_json": json.dumps(block.section_path, ensure_ascii=False),
            "page": block.page,
            "source_order": block.source_order,
        } for block in bundle.text_blocks]
        if payload:
            self.graph.run(
                """
                UNWIND $items AS item
                MATCH (report:Report {report_id: item.report_id})
                MERGE (block:TextBlock {block_id: item.block_id})
                SET block.text = item.text,
                    block.section_title = item.section_title,
                    block.section_path_json = item.section_path_json,
                    block.page = item.page,
                    block.source_order = item.source_order,
                    block.block_type = 'text'
                MERGE (report)-[:HAS_CONTENT]->(block)
                """,
                items=payload,
            )
        self.graph.run(
            """
            MATCH (event:Event), (block:TextBlock)
            WHERE event.source_segment = block.block_id
            MERGE (event)-[:EXTRACTED_FROM]->(block)
            MERGE (block)-[:SUPPORTS]->(event)
            """
        )
        return {"text_blocks": len(payload)}

    def _link_figures_to_events(self, bundle: ContentBundle) -> None:
        figure_ids = [figure.figure_id for figure in bundle.figures]
        if not figure_ids:
            return
        self.graph.run(
            """
            MATCH (event:Event), (figure:Figure)
            WHERE figure.figure_id IN $figure_ids
              AND event.source_segment = figure.figure_id
            MERGE (event)-[:EXTRACTED_FROM]->(figure)
            MERGE (figure)-[:SUPPORTS]->(event)
            """,
            figure_ids=figure_ids,
        )

    def _link_report_to_events(self, report_id: str, events: List[Event]) -> None:
        event_ids = [event.event_id for event in events]
        if not event_ids:
            return
        self.graph.run(
            """
            MATCH (report:Report {report_id: $report_id})
            MATCH (event:Event)
            WHERE event.event_id IN $event_ids
            SET event.report_id = $report_id
            MERGE (report)-[:HAS_KNOWLEDGE]->(event)
            """,
            report_id=report_id,
            event_ids=event_ids,
        )
