# -*- coding: utf-8 -*-
"""Build an event-oriented knowledge graph."""

import re
from typing import Dict, List, Set, Tuple, Optional
from collections import defaultdict
from datetime import datetime

from py2neo import Graph, Node, Relationship, Subgraph

from schema.ontology_loader import OntologyLoader
from extraction.event_extractor import (
    Event, EventKnowledge, EventType, EventRelation, ExtractionResult
)
from extraction.cluster_deduplication import KGGenStyleCluster


class EventKnowledgeBuilder:
    """Store event nodes, event relationships and n-ary property structures."""

    def __init__(
        self,
        neo4j_uri: str = "neo4j://127.0.0.1:7687",
        neo4j_user: str = "neo4j",
        neo4j_password: str = "",
        ontology_loader: OntologyLoader = None,
    ):
        self.graph = Graph(neo4j_uri, auth=(neo4j_user, neo4j_password))
        self.loader = ontology_loader or OntologyLoader()

        self._created_nodes: Dict[str, Node] = {}
        self._stats = {
            'event_nodes': 0,
            'entity_nodes': 0,
            'event_relations': 0,
            'hyper_edges': 0,
            'causal_chain_hyper_edges': 0,
            'schema_links': 0,
            'timeline_relations': 0,
            'errors': 0,
        }

    # Graph construction

    def build(
        self,
        events: List[Event],
        knowledge: List[EventKnowledge],
        entity_mapping: Dict[str, str] = None,
    ):
        """Build the event knowledge graph."""
        entity_mapping = entity_mapping or {}
        print(f"🔨 开始构建事件知识图谱...")

        # 1. Create event nodes.
        self._create_event_nodes(events, entity_mapping)

        # 2. Create event relationships.
        self._create_event_relations(knowledge, entity_mapping)

        # 3. Create hyperedges for n-ary relationships.
        self._create_hyper_edges(events, knowledge, entity_mapping)

        # 4. Print statistics.
        self._print_stats()

    def _create_event_nodes(
        self,
        events: List[Event],
        entity_mapping: Dict[str, str],
    ):
        """Create event nodes."""
        print("  📍 创建事件节点...")
        batch = []

        for event in events:
            # Use the mapped canonical name.
            canonical_name = entity_mapping.get(event.name, event.name)

            node = Node(
                "Event",
                "滑坡事件",
                event_id=event.event_id,
                name=canonical_name,
                event_type=event.event_type.value,
                description=event.description[:500],
                trigger=event.trigger,
                location=event.location,
                time=event.time,
                source_segment=event.source_segment,
                source_text=event.source_text[:500],
                confidence=event.confidence,
                created_at=datetime.now().isoformat(),
            )

            # Add all attributes.
            for attr_name, attr_value in event.attributes.items():
                node[attr_name] = attr_value

            batch.append(node)
            self._created_nodes[event.name] = node
            self._created_nodes[canonical_name] = node

        # Create nodes in batches.
        for i in range(0, len(batch), 200):
            sub = Subgraph(nodes=batch[i:i + 200])
            self.graph.create(sub)

        self._stats['event_nodes'] = len(batch)
        print(f"    ✅ 事件节点: {len(batch)} 个")

    def _create_event_relations(
        self,
        knowledge: List[EventKnowledge],
        entity_mapping: Dict[str, str],
    ):
        """Create relationships between events."""
        print("  🔗 创建事件关系...")
        rel_batch = []

        for kn in knowledge:
            head_name = entity_mapping.get(kn.head_event, kn.head_event)
            tail_name = entity_mapping.get(kn.tail_event, kn.tail_event)

            head_node = self._created_nodes.get(kn.head_event) or self._created_nodes.get(head_name)
            tail_node = self._created_nodes.get(kn.tail_event) or self._created_nodes.get(tail_name)

            if not head_node or not tail_node:
                continue

            rel_type = self._get_relation_type(kn.relation)
            rel = Relationship(
                head_node, rel_type, tail_node,
                description=kn.description[:200],
                confidence=kn.confidence,
            )
            rel_batch.append(rel)

        # Create nodes in batches.
        for i in range(0, len(rel_batch), 200):
            sub = Subgraph(relationships=rel_batch[i:i + 200])
            self.graph.create(sub)

        self._stats['event_relations'] = len(rel_batch)
        print(f"    ✅ 事件关系: {len(rel_batch)} 条")

    def _create_hyper_edges(
        self,
        events: List[Event],
        knowledge: List[EventKnowledge],
        entity_mapping: Dict[str, str],
    ):
        """Create property and causal-chain hyperedges for n-ary relationships."""
        print("  🔷 创建超边（N 元关系）...")
        hyper_count = 0
        chain_hyper_count = 0

        for event in events:
            canonical_name = entity_mapping.get(event.name, event.name)
            event_node = self._created_nodes.get(canonical_name)
            if not event_node:
                continue

            # Create an attribute hyperedge for each event.
            if len(event.attributes) >= 2:
                # Create an intermediate property-group node.
                hyper_node = Node(
                    "HyperEdge",
                    "属性组",
                    event_id=event.event_id,
                    name=f"{canonical_name}_属性",
                    created_at=datetime.now().isoformat(),
                )
                self.graph.create(hyper_node)

                # Connect the event to the hyperedge.
                rel = Relationship(event_node, "HAS_PROPERTIES", hyper_node)
                self.graph.create(rel)
                hyper_count += 1

                # Create and connect property-value nodes, including the unit field.
                for attr_name, attr_value in event.attributes.items():
                    normalized = event.normalized_attributes.get(attr_name, {})
                    unit = normalized.get("unit") or self._extract_unit_from_value(attr_value)
                    standard_value = normalized.get("value", attr_value)
                    if isinstance(standard_value, list):
                        standard_value = " ~ ".join(str(value) for value in standard_value)
                    attr_node = Node(
                        "Property",
                        name=attr_name,
                        value=standard_value,
                        raw_value=normalized.get("raw", attr_value),
                        unit=unit,
                        is_range=bool(normalized.get("is_range", False)),
                        min_value=normalized.get("min"),
                        max_value=normalized.get("max"),
                    )
                    self.graph.create(attr_node)
                    attr_rel = Relationship(hyper_node, "HAS_VALUE", attr_node)
                    self.graph.create(attr_rel)

        # Represent a causal chain A->B->C using an intermediate hyperedge.
        chain_groups = {}
        for kn in knowledge:
            chain_id = kn.attributes.get('chain_id', '') if kn.attributes else ''
            if chain_id:
                if chain_id not in chain_groups:
                    chain_groups[chain_id] = []
                chain_groups[chain_id].append(kn)

        for chain_id, chain_links in chain_groups.items():
            if len(chain_links) < 2:
                continue

            # Create the causal-chain intermediate node.
            chain_hyper_node = Node(
                "HyperEdge",
                "因果链",
                chain_id=chain_id,
                name=f"因果链_{chain_id}",
                hop_count=len(chain_links),
                created_at=datetime.now().isoformat(),
            )
            self.graph.create(chain_hyper_node)
            chain_hyper_count += 1

            # Connect each chain member to the hyperedge.
            for link in chain_links:
                head_name = entity_mapping.get(link.head_event, link.head_event)
                tail_name = entity_mapping.get(link.tail_event, link.tail_event)

                head_node = self._created_nodes.get(head_name) or self._created_nodes.get(link.head_event)
                tail_node = self._created_nodes.get(tail_name) or self._created_nodes.get(link.tail_event)

                if head_node:
                    rel = Relationship(head_node, "PART_OF_CHAIN", chain_hyper_node)
                    self.graph.create(rel)
                if tail_node:
                    rel = Relationship(chain_hyper_node, "LEADS_TO", tail_node)
                    self.graph.create(rel)

        self._stats['hyper_edges'] = hyper_count
        self._stats['causal_chain_hyper_edges'] = chain_hyper_count
        print(f"    ✅ 超边: {hyper_count} 个")
        print(f"    ✅ 因果链超边: {chain_hyper_count} 个")

    def _extract_unit_from_value(self, value: str) -> str:
        """Extract a unit from a property value."""
        if not value:
            return ""

        # Common unit patterns
        unit_patterns = [
            r'(m[³²32]?|m³|m²|m\d?)$',  # Volume, area and length
            r'(km|cm|mm|μm|nm)$',
            r'(kPa|MPa|GPa|Pa)$',
            r'(g|kg|t)$',
            r'(°|度)$',
            r'(cm/s|m/s|m/d|cm/d|mm/d)$',
            r'(g|gal|Gal)$',
            r'(人|户|万元|元)$',
            r'(mm/d|cm/d|m/d|mm/月|cm/月)$',
        ]

        for pattern in unit_patterns:
            match = re.search(pattern, value)
            if match:
                return match.group(1)

        return ""

    # Relationship-type mapping

    def _get_relation_type(self, event_rel: EventRelation) -> str:
        """Map an event relationship to a Neo4j relationship type."""
        mapping = {
            EventRelation.CAUSAL: "CAUSED_BY",
            EventRelation.TEMPORAL: "PRECEDES",
            EventRelation.CONCURRENT: "CONCURRENT_WITH",
            EventRelation.SPATIAL: "LOCATED_AT",
            EventRelation.PART_OF: "PART_OF",
            EventRelation.ATTRIBUTE: "HAS_ATTRIBUTE",
            EventRelation.CONDITIONAL: "CONDITIONED_BY",
        }
        return mapping.get(event_rel, "RELATED_TO")

    # Schema-layer links

    def link_to_schema_layer(
        self,
        events: List[Event] = None,
        entity_mapping: Dict[str, str] = None,
    ):
        """Link event nodes to ontology classes in the schema layer."""
        entity_mapping = entity_mapping or {}
        print("  🔗 关联 Schema 层...")

        # Map event types to schema ontology classes.
        event_type_to_schema_class = {
            EventType.DISASTER: "滑坡本体",
            EventType.RESULT: "损失评估",
            EventType.RESPONSE: "防治工程",
            EventType.CONDITION: "地质环境",
            EventType.OBSERVATION: "勘查数据",
        }

        schema_links = 0

        if events:
            # Use the supplied event list.
            for event in events:
                canonical_name = entity_mapping.get(event.name, event.name)
                event_node = self._created_nodes.get(canonical_name)
                if not event_node:
                    # Try to locate existing nodes.
                    try:
                        existing = self.graph.nodes.match(
                            "Event", name=canonical_name
                        ).first()
                        if existing:
                            event_node = existing
                        else:
                            continue
                    except Exception:
                        continue

                schema_class = event_type_to_schema_class.get(event.event_type, "地质信息")
                if self._link_event_to_schema(event_node, schema_class, event):
                    schema_links += 1
        else:
            # Use all event nodes already created.
            for name, event_node in self._created_nodes.items():
                event_type_str = event_node.get('event_type', '')
                event_type = self._str_to_event_type(event_type_str)
                schema_class = event_type_to_schema_class.get(event_type, "地质信息")
                if self._link_event_to_schema(event_node, schema_class, None):
                    schema_links += 1

        self._stats['schema_links'] = schema_links
        print(f"    ✅ Schema 关联: {schema_links} 条")
        return schema_links

    def _link_event_to_schema(
        self,
        event_node: Node,
        schema_class_name: str,
        event: Optional[Event] = None,
    ):
        """Link one event node to the schema layer."""
        try:
            # Find or create the SchemaClass node.
            schema_node = self.graph.nodes.match(
                "SchemaClass", name=schema_class_name
            ).first()

            if not schema_node:
                schema_node = Node(
                    "SchemaClass",
                    "本体类",
                    name=schema_class_name,
                    source="ontology",
                )
                self.graph.create(schema_node)

            # Create the INSTANCE_OF relationship.
            rel = Relationship(
                event_node,
                "INSTANCE_OF",
                schema_node,
                description=f"事件实例属于 {schema_class_name} 本体类",
                confidence=event.confidence if event else 0.85,
            )
            self.graph.create(rel)
            return True
        except Exception as e:
            self._stats['errors'] += 1
            return False

    def _str_to_event_type(self, type_str: str) -> EventType:
        """Convert a string to the EventType enumeration."""
        for etype in EventType:
            if etype.value == type_str:
                return etype
        return EventType.CONDITION

    # Event chronology

    def create_event_timeline(
        self,
        events: List[Event],
        entity_mapping: Dict[str, str] = None,
    ):
        """Sort events chronologically and create PRECEDES relationships."""
        entity_mapping = entity_mapping or {}
        print("  ⏱️ 创建事件时序...")

        # Collect events with time information.
        timed_events = []
        for event in events:
            if event.time:
                canonical_name = entity_mapping.get(event.name, event.name)
                event_node = self._created_nodes.get(canonical_name)
                if not event_node:
                    try:
                        event_node = self.graph.nodes.match(
                            "Event", name=canonical_name
                        ).first()
                    except Exception:
                        continue
                if event_node:
                    timed_events.append({
                        'event': event,
                        'node': event_node,
                        'time_str': event.time,
                        'parsed_time': self._parse_time_string(event.time),
                    })

        if len(timed_events) < 2:
            print("    ⚠️ 时间信息不足，跳过时序创建")
            return 0

        # Sort by time.
        timed_events.sort(key=lambda x: x['parsed_time'])

        # Create PRECEDES relationships.
        timeline_count = 0
        for i in range(len(timed_events) - 1):
            current = timed_events[i]
            next_event = timed_events[i + 1]

            rel = Relationship(
                current['node'],
                "PRECEDES",
                next_event['node'],
                description=f"{current['event'].name} 发生在 {next_event['event'].name} 之前",
                from_time=current['time_str'],
                to_time=next_event['time_str'],
                confidence=0.8,
            )
            self.graph.create(rel)
            timeline_count += 1

        self._stats['timeline_relations'] = timeline_count
        print(f"    ✅ 时序关系: {timeline_count} 条")
        return timeline_count

    def _parse_time_string(self, time_str: str) -> Tuple[int, int, int]:
        """Parse a time string into a sortable tuple."""
        year = month = day = 0

        # Match a year-month-day expression.
        m = re.search(r'(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日', time_str)
        if m:
            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return (year, month, day)

        # Match a year-month expression.
        m = re.search(r'(\d{4})\s*年\s*(\d{1,2})\s*月', time_str)
        if m:
            year, month = int(m.group(1)), int(m.group(2))
            return (year, month, 0)

        # Match a year expression.
        m = re.search(r'(\d{4})\s*年', time_str)
        if m:
            year = int(m.group(1))
            return (year, 0, 0)

        # Match a numeric year.
        m = re.search(r'(\d{4})', time_str)
        if m:
            year = int(m.group(1))
            return (year, 0, 0)

        return (0, 0, 0)

    # Statistics

    def _print_stats(self):
        """Print graph-construction statistics."""
        print(f"\n  {'='*50}")
        print(f"  📊 事件知识图谱构建统计")
        print(f"  {'='*50}")
        print(f"     事件节点:          {self._stats['event_nodes']:>6} 个")
        print(f"     事件关系:          {self._stats['event_relations']:>6} 条")
        print(f"     属性超边:          {self._stats['hyper_edges']:>6} 个")
        print(f"     因果链超边:        {self._stats['causal_chain_hyper_edges']:>6} 个")
        print(f"     Schema 关联:       {self._stats['schema_links']:>6} 条")
        print(f"     时序关系:          {self._stats['timeline_relations']:>6} 条")
        print(f"  {'─'*50}")
        total_edges = (
            self._stats['event_relations']
            + self._stats['hyper_edges']
            + self._stats['causal_chain_hyper_edges']
            + self._stats['schema_links']
            + self._stats['timeline_relations']
        )
        total_nodes = self._stats['event_nodes']
        print(f"     总计节点:          {total_nodes:>6} 个")
        print(f"     总计关系/超边:     {total_edges:>6} 条")
        if self._stats['errors']:
            print(f"     ⚠️ 错误:           {self._stats['errors']:>6} 个")
        print(f"  {'='*50}")

    def get_stats(self) -> dict:
        return dict(self._stats)


