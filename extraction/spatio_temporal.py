# -*- coding: utf-8 -*-
"""Spatiotemporal enrichment for the knowledge graph."""

import re
import json
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime, date
from collections import defaultdict

from py2neo import Graph, Node, Relationship, Subgraph

from extraction.event_extractor import Event, EventType, EventRelation


# Enumeration definitions

class TemporalNodeType(Enum):
    """Temporal node categories based on OWL-Time."""
    INSTANT = "Instant"       # Instant: a point on the timeline
    INTERVAL = "Interval"     # Interval: a time span with start and end instants


class AllenRelation(Enum):
    """The 13 Allen interval relations, following OWL-Time concepts."""
    BEFORE = "BEFORE"                 # A is before B without overlap.
    AFTER = "AFTER"                   # A is after B, the inverse of BEFORE.
    MEETS = "MEETS"                   # A ends exactly when B starts.
    MET_BY = "MET_BY"                 # A starts exactly when B ends, the inverse of MEETS.
    OVERLAPS = "OVERLAPS"             # A starts before B and ends within B.
    OVERLAPPED_BY = "OVERLAPPED_BY"   # A starts within B and ends after B, the inverse of OVERLAPS.
    STARTS = "STARTS"                 # A and B start together, but A ends earlier.
    STARTED_BY = "STARTED_BY"         # A and B start together, but B ends earlier, the inverse of STARTS.
    DURING = "DURING"                 # A is entirely within B.
    CONTAINS = "CONTAINS"             # A entirely contains B, the inverse of DURING.
    FINISHES = "FINISHES"             # A and B end together, but A starts later.
    FINISHED_BY = "FINISHED_BY"       # A and B end together, but B starts later, the inverse of FINISHES.
    EQUALS = "EQUALS"                 # A and B have identical bounds.


class SpatialTopology(Enum):
    """Spatial topological relationships following LHOM concepts."""
    CONTAINS = "CONTAINS"       # A contains B.
    WITHIN = "WITHIN"           # A is inside B.
    OVERLAPS = "OVERLAPS"       # A partially overlaps B.
    TOUCHES = "TOUCHES"         # A is adjacent to or touches B.
    DISJOINT = "DISJOINT"       # A and B are disjoint.


class SpatialDirection(Enum):
    """Directional spatial relationships following LHOM ordering concepts."""
    NORTH_OF = "NORTH_OF"               # A is north of B.
    SOUTH_OF = "SOUTH_OF"               # A is south of B.
    EAST_OF = "EAST_OF"                 # A is east of B.
    WEST_OF = "WEST_OF"                 # A is west of B.
    NORTHEAST_OF = "NORTHEAST_OF"       # A is northeast of B.
    NORTHWEST_OF = "NORTHWEST_OF"       # A is northwest of B.
    SOUTHEAST_OF = "SOUTHEAST_OF"       # A is southeast of B.
    SOUTHWEST_OF = "SOUTHWEST_OF"       # A is southwest of B.


class DistanceUnit(Enum):
    """Distance units."""
    METER = "m"
    KILOMETER = "km"
    CENTIMETER = "cm"
    MILLIMETER = "mm"


# Dataclasses

@dataclass
class TimeInstant:
    """A time instant based on the OWL-Time Instant concept."""
    instant_id: str
    datetime_value: Optional[datetime] = None
    description: str = ""
    granularity: str = "month"            # year | month | day | hour
    in_xsd_datetime: str = ""             # XSD datetime format


@dataclass
class TimeInterval:
    """A time interval based on the OWL-Time Interval concept."""
    interval_id: str
    begins: Optional[TimeInstant] = None
    ends: Optional[TimeInstant] = None
    description: str = ""
    duration_days: Optional[int] = None


@dataclass
class SpatialCoordinate:
    """Spatial coordinates."""
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    elevation: Optional[float] = None
    coordinate_system: str = "WGS84"
    location_name: str = ""


@dataclass
class SpatialRelationRecord:
    """A structured spatial-relationship record."""
    relation_id: str
    head_entity: str
    relation_type: str = "SPATIAL"
    tail_entity: str = ""
    topology: Optional[SpatialTopology] = None
    direction: Optional[SpatialDirection] = None
    distance_value: Optional[float] = None
    distance_unit: Optional[DistanceUnit] = None
    description: str = ""
    confidence: float = 1.0


@dataclass
class SpatioTemporalEvent:
    """An Event extended with temporal and spatial fields."""
    # Inherited Event fields
    event_id: str = ""
    event_type: EventType = EventType.DISASTER
    name: str = ""
    description: str = ""
    trigger: str = ""
    location: str = ""
    time: str = ""
    attributes: Dict[str, str] = field(default_factory=dict)
    source_segment: str = ""
    source_text: str = ""
    confidence: float = 1.0

    # Spatiotemporal extension fields
    time_interval: Optional[TimeInterval] = None
    spatial_coordinate: Optional[SpatialCoordinate] = None
    spatial_relations: List[SpatialRelationRecord] = field(default_factory=list)
    time_relations: List[Tuple[str, AllenRelation, str]] = field(default_factory=list)

    @classmethod
    def from_event(cls, event: Event) -> "SpatioTemporalEvent":
        """Create a SpatioTemporalEvent from an Event."""
        return cls(
            event_id=event.event_id,
            event_type=event.event_type,
            name=event.name,
            description=event.description,
            trigger=event.trigger,
            location=event.location,
            time=event.time,
            attributes=dict(event.attributes),
            source_segment=event.source_segment,
            source_text=event.source_text,
            confidence=event.confidence,
        )


@dataclass
class TemporalRelationRecord:
    """A temporal-relationship record."""
    relation_id: str
    head_entity: str
    allen_relation: AllenRelation
    tail_entity: str
    description: str = ""
    confidence: float = 1.0


# Time parser

class TimeParser:
    """Parse Chinese time expressions."""

    # Regular expressions for Chinese temporal expressions
    PATTERN_YEAR = re.compile(r'(\d{4})\s*年')
    PATTERN_YEAR_MONTH = re.compile(r'(\d{4})\s*年\s*(\d{1,2})\s*月')
    PATTERN_YEAR_MONTH_DAY = re.compile(r'(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]')
    PATTERN_MONTH = re.compile(r'(\d{1,2})\s*月')
    PATTERN_MONTH_DAY = re.compile(r'(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]')

    # Connectors between time-range endpoints
    RANGE_CONNECTORS = ['至', '到', '～', '~', '-', '—', '——']

    # Season and special-period mappings
    SEASON_MAP = {
        '汛期': (6, 9),     # Default: June through September
        '春季': (3, 5),
        '夏季': (6, 8),
        '秋季': (9, 11),
        '冬季': (12, 2),
        '雨季': (5, 9),
        '旱季': (11, 4),
        '上半年': (1, 6),
        '下半年': (7, 12),
    }

    _counter: int = 0

    @classmethod
    def _next_id(cls) -> int:
        """Generate the next incremental identifier."""
        cls._counter += 1
        return cls._counter

    @classmethod
    def parse_instant(cls, text: str) -> Optional[TimeInstant]:
        """Parse a single time-instant expression."""
        text = text.strip()

        # Try a year-month-day expression.
        m = cls.PATTERN_YEAR_MONTH_DAY.search(text)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            dt = datetime(y, mo, d)
            return TimeInstant(
                instant_id=f"instant_{cls._next_id():04d}",
                datetime_value=dt,
                description=text,
                granularity="day",
                in_xsd_datetime=dt.strftime("%Y-%m-%dT%H:%M:%S"),
            )

        # Try a year-month expression.
        m = cls.PATTERN_YEAR_MONTH.search(text)
        if m:
            y, mo = int(m.group(1)), int(m.group(2))
            dt = datetime(y, mo, 1)
            return TimeInstant(
                instant_id=f"instant_{cls._next_id():04d}",
                datetime_value=dt,
                description=text,
                granularity="month",
                in_xsd_datetime=dt.strftime("%Y-%m"),
            )

        # Try a year expression.
        m = cls.PATTERN_YEAR.search(text)
        if m:
            y = int(m.group(1))
            dt = datetime(y, 1, 1)
            return TimeInstant(
                instant_id=f"instant_{cls._next_id():04d}",
                datetime_value=dt,
                description=text,
                granularity="year",
                in_xsd_datetime=str(y),
            )

        return None

    @classmethod
    def parse_interval(cls, text: str) -> Optional[TimeInterval]:
        """Parse a time-interval expression."""
        text = text.strip()

        # Split a range connector into two candidate time points.
        parts = None
        connector = None
        for conn in cls.RANGE_CONNECTORS:
            if conn in text:
                parts = [p.strip() for p in text.split(conn, 1)]
                connector = conn
                break

        if parts and len(parts) == 2:
            begin_instant = cls.parse_instant(parts[0])
            end_instant = cls.parse_instant(parts[1])
            if begin_instant and end_instant:
                duration = cls._calc_duration_days(begin_instant, end_instant)
                return TimeInterval(
                    interval_id=f"interval_{cls._next_id():04d}",
                    begins=begin_instant,
                    ends=end_instant,
                    description=text,
                    duration_days=duration,
                )

        # Check for a season or special period.
        for season_name, (start_month, end_month) in cls.SEASON_MAP.items():
            if season_name in text:
                # Extract the year.
                year_match = cls.PATTERN_YEAR.search(text)
                if year_match:
                    year = int(year_match.group(1))
                    begin = TimeInstant(
                        instant_id=f"instant_{cls._next_id():04d}",
                        datetime_value=datetime(year, start_month, 1),
                        description=f"{year}年{season_name}开始",
                        granularity="month",
                        in_xsd_datetime=f"{year}-{start_month:02d}",
                    )
                    end = TimeInstant(
                        instant_id=f"instant_{cls._next_id():04d}",
                        datetime_value=datetime(year, end_month, 28),
                        description=f"{year}年{season_name}结束",
                        granularity="month",
                        in_xsd_datetime=f"{year}-{end_month:02d}",
                    )
                    if end_month < start_month:
                        # Handle cross-year periods such as December through February.
                        end = TimeInstant(
                            instant_id=f"instant_{cls._next_id():04d}",
                            datetime_value=datetime(year + 1, end_month, 28),
                            description=f"{year + 1}年{season_name}结束",
                            granularity="month",
                            in_xsd_datetime=f"{year + 1}-{end_month:02d}",
                        )
                    return TimeInterval(
                        interval_id=f"interval_{cls._next_id():04d}",
                        begins=begin,
                        ends=end,
                        description=text,
                        duration_days=cls._calc_duration_days(begin, end),
                    )

        # If interval parsing fails, try an instant.
        instant = cls.parse_instant(text)
        if instant:
            return TimeInterval(
                interval_id=f"interval_{cls._next_id():04d}",
                begins=instant,
                ends=instant,
                description=text,
                duration_days=0,
            )

        return None

    @classmethod
    def parse_time(cls, text: str) -> Optional[TimeInterval]:
        """Parse a temporal expression as an interval or instant."""
        # Try interval parsing first.
        for conn in cls.RANGE_CONNECTORS:
            if conn in text:
                return cls.parse_interval(text)

        # Check for a season or special period.
        for season_name in cls.SEASON_MAP:
            if season_name in text:
                return cls.parse_interval(text)

        # Parse as an instant.
        instant = cls.parse_instant(text)
        if instant:
            return TimeInterval(
                interval_id=f"interval_{cls._next_id():04d}",
                begins=instant,
                ends=instant,
                description=text,
                duration_days=0,
            )
        return None

    @staticmethod
    def _calc_duration_days(
        begin: TimeInstant, end: TimeInstant
    ) -> Optional[int]:
        """Compute elapsed days between two instants."""
        if begin.datetime_value and end.datetime_value:
            delta = end.datetime_value - begin.datetime_value
            return delta.days
        return None

    @staticmethod
    def determine_relation(
        interval_a: TimeInterval, interval_b: TimeInterval
    ) -> Optional[AllenRelation]:
        """Determine the Allen relation between two intervals."""
        a_beg = interval_a.begins
        a_end = interval_a.ends
        b_beg = interval_b.begins
        b_end = interval_b.ends

        if not all([a_beg, a_end, b_beg, b_end]):
            return None

        a_beg_dt = a_beg.datetime_value
        a_end_dt = a_end.datetime_value
        b_beg_dt = b_beg.datetime_value
        b_end_dt = b_end.datetime_value

        if not all([a_beg_dt, a_end_dt, b_beg_dt, b_end_dt]):
            return None

        # Evaluate Allen interval relations in sequence.
        if a_beg_dt == b_beg_dt and a_end_dt == b_end_dt:
            return AllenRelation.EQUALS

        if a_end_dt < b_beg_dt:
            # Check whether the intervals meet.
            if (a_end_dt.month == b_beg_dt.month - 1 or
                (a_end_dt.month == 12 and b_beg_dt.month == 1)):
                return AllenRelation.MEETS
            return AllenRelation.BEFORE

        if a_beg_dt > b_end_dt:
            if (b_end_dt.month == a_beg_dt.month - 1 or
                (b_end_dt.month == 12 and a_beg_dt.month == 1)):
                return AllenRelation.MET_BY
            return AllenRelation.AFTER

        if a_beg_dt == b_beg_dt and a_end_dt < b_end_dt:
            return AllenRelation.STARTS

        if a_beg_dt == b_beg_dt and a_end_dt > b_end_dt:
            return AllenRelation.STARTED_BY

        if a_beg_dt > b_beg_dt and a_end_dt == b_end_dt:
            return AllenRelation.FINISHES

        if a_beg_dt < b_beg_dt and a_end_dt == b_end_dt:
            return AllenRelation.FINISHED_BY

        if a_beg_dt > b_beg_dt and a_end_dt < b_end_dt:
            return AllenRelation.DURING

        if a_beg_dt < b_beg_dt and a_end_dt > b_end_dt:
            return AllenRelation.CONTAINS

        if a_beg_dt < b_beg_dt < a_end_dt < b_end_dt:
            return AllenRelation.OVERLAPS

        if b_beg_dt < a_beg_dt < b_end_dt < a_end_dt:
            return AllenRelation.OVERLAPPED_BY

        return None


# Spatial-relation parser

class SpatialParser:
    """Parse spatial relationships."""

    # Direction keyword mappings
    DIRECTION_KEYWORDS = {
        '北': SpatialDirection.NORTH_OF,
        '南': SpatialDirection.SOUTH_OF,
        '东': SpatialDirection.EAST_OF,
        '西': SpatialDirection.WEST_OF,
        '东北': SpatialDirection.NORTHEAST_OF,
        '西北': SpatialDirection.NORTHWEST_OF,
        '东南': SpatialDirection.SOUTHEAST_OF,
        '西南': SpatialDirection.SOUTHWEST_OF,
    }

    # Topology keyword mappings
    TOPOLOGY_KEYWORDS = {
        '包含': SpatialTopology.CONTAINS,
        '包括': SpatialTopology.CONTAINS,
        '位于': SpatialTopology.WITHIN,
        '在.*内': SpatialTopology.WITHIN,
        '内部': SpatialTopology.WITHIN,
        '重叠': SpatialTopology.OVERLAPS,
        '相邻': SpatialTopology.TOUCHES,
        '接触': SpatialTopology.TOUCHES,
        '交界': SpatialTopology.TOUCHES,
        '不相交': SpatialTopology.DISJOINT,
        '分离': SpatialTopology.DISJOINT,
    }

    # Regular expressions for distances
    PATTERN_DISTANCE = re.compile(
        r'(\d+\.?\d*)\s*(m|km|cm|mm|米|千米|公里|厘米|毫米)'
    )

    # Regular expressions for longitude and latitude
    PATTERN_LONLAT = re.compile(
        r'(?:经度|东经|E)[:\s]*(\d+\.?\d*)[°\s]*.*?'
        r'(?:纬度|北纬|N)[:\s]*(\d+\.?\d*)[°\s]*'
    )
    PATTERN_LON = re.compile(r'(?:经度|东经|E)[:\s]*(\d+\.?\d*)')
    PATTERN_LAT = re.compile(r'(?:纬度|北纬|N)[:\s]*(\d+\.?\d*)')
    PATTERN_ELEVATION = re.compile(
        r'(?:高程|海拔|标高|ELV?)[:\s]*(\d+\.?\d*)\s*(?:m|米)?'
    )

    @classmethod
    def parse_direction(cls, text: str) -> Optional[SpatialDirection]:
        """Parse a direction expression."""
        # Match longer keywords first by sorting in descending length.
        sorted_keywords = sorted(
            cls.DIRECTION_KEYWORDS.keys(),
            key=len, reverse=True
        )
        for keyword in sorted_keywords:
            if keyword in text:
                return cls.DIRECTION_KEYWORDS[keyword]
        return None

    @classmethod
    def parse_topology(cls, text: str) -> Optional[SpatialTopology]:
        """Parse a topological relationship."""
        for keyword, topology in cls.TOPOLOGY_KEYWORDS.items():
            if re.search(keyword, text):
                return topology
        return None

    @classmethod
    def parse_distance(cls, text: str) -> Optional[Tuple[float, DistanceUnit]]:
        """Parse a distance expression."""
        m = cls.PATTERN_DISTANCE.search(text)
        if not m:
            return None

        value = float(m.group(1))
        unit_str = m.group(2)

        # Normalize units.
        unit_map = {
            'm': DistanceUnit.METER, '米': DistanceUnit.METER,
            'km': DistanceUnit.KILOMETER, '千米': DistanceUnit.KILOMETER,
            '公里': DistanceUnit.KILOMETER,
            'cm': DistanceUnit.CENTIMETER, '厘米': DistanceUnit.CENTIMETER,
            'mm': DistanceUnit.MILLIMETER, '毫米': DistanceUnit.MILLIMETER,
        }
        unit = unit_map.get(unit_str, DistanceUnit.METER)
        return (value, unit)

    @classmethod
    def parse_coordinate(cls, text: str) -> Optional[SpatialCoordinate]:
        """Parse longitude, latitude and elevation."""
        lon = None
        lat = None
        elevation = None

        # Try a combined longitude/latitude match.
        m = cls.PATTERN_LONLAT.search(text)
        if m:
            lon = float(m.group(1))
            lat = float(m.group(2))
        else:
            # Match the coordinates separately.
            m_lon = cls.PATTERN_LON.search(text)
            m_lat = cls.PATTERN_LAT.search(text)
            if m_lon:
                lon = float(m_lon.group(1))
            if m_lat:
                lat = float(m_lat.group(1))

        # Match elevation.
        m_elev = cls.PATTERN_ELEVATION.search(text)
        if m_elev:
            elevation = float(m_elev.group(1))

        if lon is not None or lat is not None or elevation is not None:
            return SpatialCoordinate(
                longitude=lon,
                latitude=lat,
                elevation=elevation,
            )

        return None

    @classmethod
    def parse_spatial_relation(
        cls,
        head_entity: str,
        tail_entity: str,
        text: str,
        relation_id: str = "",
    ) -> SpatialRelationRecord:
        """Convert spatial text into structured relationship records."""
        direction = cls.parse_direction(text)
        topology = cls.parse_topology(text)
        distance = cls.parse_distance(text)

        relation_type = "SPATIAL"
        if direction:
            relation_type = f"SPATIAL_DIRECTIONAL_{direction.value}"
        elif topology:
            relation_type = f"SPATIAL_TOPOLOGICAL_{topology.value}"
        elif distance:
            relation_type = "SPATIAL_DISTANCE"

        return SpatialRelationRecord(
            relation_id=relation_id or f"sr_{hash(text) & 0xFFFF:04x}",
            head_entity=head_entity,
            relation_type=relation_type,
            tail_entity=tail_entity,
            topology=topology,
            direction=direction,
            distance_value=distance[0] if distance else None,
            distance_unit=distance[1] if distance else None,
            description=text,
            confidence=0.8,
        )


# Spatiotemporal event builder

class SpatioTemporalEnhancer:
    """Enrich events with temporal and spatial information."""

    def __init__(
        self,
        neo4j_uri: str = "neo4j://127.0.0.1:7687",
        neo4j_user: str = "neo4j",
        neo4j_password: str = "",
        clear_st_data: bool = False,
    ):
        """Initialize spatiotemporal enrichment."""
        self.graph = Graph(neo4j_uri, auth=(neo4j_user, neo4j_password))
        self.clear_st_data = clear_st_data

        self.time_parser = TimeParser()
        self.spatial_parser = SpatialParser()

        self._created_time_nodes: Dict[str, Node] = {}
        self._created_space_nodes: Dict[str, Node] = {}
        self._created_event_nodes: Dict[str, Node] = {}

        self._stats = {
            'time_nodes': 0,
            'space_nodes': 0,
            'st_events': 0,
            'temporal_relations': 0,
            'spatial_relations': 0,
            'timeline_relations': 0,
            'errors': 0,
        }

    # Construction entry point

    def enhance(
        self,
        events: List[Event],
        spatial_relations: Optional[List[SpatialRelationRecord]] = None,
        entity_mapping: Optional[Dict[str, str]] = None,
    ) -> List[SpatioTemporalEvent]:
        """Add spatiotemporal information to a list of events."""
        entity_mapping = entity_mapping or {}
        print("时空增强: 开始构建时空知识图谱...")

        if self.clear_st_data:
            self._clear_st_data()

        # 1. Convert events to spatiotemporal events.
        st_events = self._convert_to_st_events(events, entity_mapping)

        # 2. Parse temporal information.
        self._parse_temporal_info(st_events)

        # 3. Parse spatial information.
        self._parse_spatial_info(st_events, spatial_relations)

        # 4. Write to Neo4j.
        self._write_to_neo4j(st_events, entity_mapping)

        self._print_stats()
        return st_events

    def _convert_to_st_events(
        self,
        events: List[Event],
        entity_mapping: Dict[str, str],
    ) -> List[SpatioTemporalEvent]:
        """Convert Event objects to SpatioTemporalEvent objects."""
        st_events = []
        for event in events:
            canonical_name = entity_mapping.get(event.name, event.name)
            st_event = SpatioTemporalEvent.from_event(event)
            st_event.name = canonical_name
            st_events.append(st_event)
        self._stats['st_events'] = len(st_events)
        print(f"  转换时空事件: {len(st_events)} 个")
        return st_events

    def _parse_temporal_info(
        self,
        st_events: List[SpatioTemporalEvent],
    ) -> None:
        """Parse and populate temporal fields."""
        print("  解析时间信息...")
        for st_event in st_events:
            if st_event.time:
                interval = self.time_parser.parse_time(st_event.time)
                if interval:
                    st_event.time_interval = interval

        # Compute temporal relationships between events.
        events_with_time = [
            e for e in st_events if e.time_interval is not None
        ]
        for i in range(len(events_with_time)):
            for j in range(i + 1, len(events_with_time)):
                a = events_with_time[i]
                b = events_with_time[j]
                if a.time_interval and b.time_interval:
                    rel = self.time_parser.determine_relation(
                        a.time_interval, b.time_interval
                    )
                    if rel:
                        a.time_relations.append((b.name, rel, b.name))
                        b.time_relations.append((a.name, rel, a.name))

    def _parse_spatial_info(
        self,
        st_events: List[SpatioTemporalEvent],
        spatial_relations: Optional[List[SpatialRelationRecord]] = None,
    ) -> None:
        """Parse and populate spatial fields."""
        print("  解析空间信息...")
        for st_event in st_events:
            # Parse coordinates from location text.
            full_text = f"{st_event.location} {st_event.description}"
            coord = self.spatial_parser.parse_coordinate(full_text)
            if coord:
                coord.location_name = st_event.location
                st_event.spatial_coordinate = coord

            # Parse spatial relationships.
            if full_text.strip():
                # Try extracting direction, topology and distance from the description.
                direction = self.spatial_parser.parse_direction(full_text)
                topology = self.spatial_parser.parse_topology(full_text)
                distance = self.spatial_parser.parse_distance(full_text)

                if direction or topology or distance:
                    sr = SpatialRelationRecord(
                        relation_id=f"sr_{st_event.event_id}",
                        head_entity=st_event.name,
                        relation_type="SPATIAL",
                        direction=direction,
                        topology=topology,
                        distance_value=distance[0] if distance else None,
                        distance_unit=distance[1] if distance else None,
                        description=full_text[:200],
                        confidence=st_event.confidence,
                    )
                    st_event.spatial_relations.append(sr)

        # Process externally supplied spatial relationships.
        if spatial_relations:
            # Build an event-name lookup.
            name_to_event: Dict[str, SpatioTemporalEvent] = {}
            for e in st_events:
                name_to_event[e.name] = e

            for sr in spatial_relations:
                if sr.head_entity in name_to_event:
                    name_to_event[sr.head_entity].spatial_relations.append(sr)

    # Neo4j storage

    def _write_to_neo4j(
        self,
        st_events: List[SpatioTemporalEvent],
        entity_mapping: Dict[str, str],
    ) -> None:
        """Write spatiotemporal records to Neo4j."""
        print("  写入 Neo4j...")

        # 1. Create time nodes.
        self._create_time_nodes(st_events)

        # 2. Create spatial nodes.
        self._create_space_nodes(st_events)

        # 3. Create spatiotemporal event nodes.
        self._create_st_event_nodes(st_events, entity_mapping)

        # 4. Create temporal relationships.
        self._create_temporal_relations(st_events)

        # 5. Create spatial relationships.
        self._create_spatial_relations(st_events)

        # 6. Create timeline relationships.
        self._create_timeline_relations(st_events)

    def _create_time_nodes(
        self,
        st_events: List[SpatioTemporalEvent],
    ) -> None:
        """Create Instant and Interval nodes."""
        print("    创建时间节点...")
        batch = []
        instant_set: set = set()
        interval_set: set = set()

        for st_event in st_events:
            if st_event.time_interval is None:
                continue

            interval = st_event.time_interval

            # Create an Interval node.
            if interval.interval_id not in interval_set:
                node = Node(
                    "TemporalNode",
                    "TimeInterval",
                    interval_id=interval.interval_id,
                    description=interval.description,
                    duration_days=interval.duration_days,
                )
                batch.append(node)
                self._created_time_nodes[interval.interval_id] = node
                interval_set.add(interval.interval_id)

            # Create the starting Instant node.
            if interval.begins and interval.begins.instant_id not in instant_set:
                node = Node(
                    "TemporalNode",
                    "TimeInstant",
                    instant_id=interval.begins.instant_id,
                    description=interval.begins.description,
                    datetime_value=(
                        interval.begins.datetime_value.isoformat()
                        if interval.begins.datetime_value else ""
                    ),
                    granularity=interval.begins.granularity,
                    in_xsd_datetime=interval.begins.in_xsd_datetime,
                )
                batch.append(node)
                self._created_time_nodes[interval.begins.instant_id] = node
                instant_set.add(interval.begins.instant_id)

            # Create the ending Instant node.
            if interval.ends and interval.ends.instant_id not in instant_set:
                node = Node(
                    "TemporalNode",
                    "TimeInstant",
                    instant_id=interval.ends.instant_id,
                    description=interval.ends.description,
                    datetime_value=(
                        interval.ends.datetime_value.isoformat()
                        if interval.ends.datetime_value else ""
                    ),
                    granularity=interval.ends.granularity,
                    in_xsd_datetime=interval.ends.in_xsd_datetime,
                )
                batch.append(node)
                self._created_time_nodes[interval.ends.instant_id] = node
                instant_set.add(interval.ends.instant_id)

        # Create nodes in batches.
        for i in range(0, len(batch), 200):
            sub = Subgraph(nodes=batch[i:i + 200])
            self.graph.create(sub)

        self._stats['time_nodes'] = len(batch)
        print(f"      时间节点: {len(batch)} 个")

        # Create begins/ends relationships for the Interval.
        self._create_interval_bounds(st_events, interval_set)

    def _create_interval_bounds(
        self,
        st_events: List[SpatioTemporalEvent],
        interval_set: set,
    ) -> None:
        """Create begins/ends relationships between intervals and instants."""
        rel_batch = []
        seen: set = set()

        for st_event in st_events:
            if st_event.time_interval is None:
                continue

            interval = st_event.time_interval
            interval_node = self._created_time_nodes.get(interval.interval_id)
            if interval_node is None:
                continue

            if interval.begins:
                begin_node = self._created_time_nodes.get(
                    interval.begins.instant_id
                )
                if begin_node and (interval.interval_id, "begins") not in seen:
                    rel = Relationship(
                        interval_node, "HAS_BEGINNING", begin_node
                    )
                    rel_batch.append(rel)
                    seen.add((interval.interval_id, "begins"))

            if interval.ends:
                end_node = self._created_time_nodes.get(
                    interval.ends.instant_id
                )
                if end_node and (interval.interval_id, "ends") not in seen:
                    rel = Relationship(
                        interval_node, "HAS_END", end_node
                    )
                    rel_batch.append(rel)
                    seen.add((interval.interval_id, "ends"))

        for i in range(0, len(rel_batch), 200):
            sub = Subgraph(relationships=rel_batch[i:i + 200])
            self.graph.create(sub)

    def _create_space_nodes(
        self,
        st_events: List[SpatioTemporalEvent],
    ) -> None:
        """Create spatial nodes."""
        print("    创建空间节点...")
        batch = []
        coord_set: set = set()

        for st_event in st_events:
            if st_event.spatial_coordinate is None:
                continue

            coord = st_event.spatial_coordinate
            node_key = (
                f"{coord.longitude}_{coord.latitude}_{coord.elevation}"
            )

            if node_key not in coord_set:
                node = Node(
                    "SpatialNode",
                    "SpatialCoordinate",
                    longitude=coord.longitude,
                    latitude=coord.latitude,
                    elevation=coord.elevation,
                    coordinate_system=coord.coordinate_system,
                    location_name=coord.location_name,
                )
                batch.append(node)
                self._created_space_nodes[node_key] = node
                coord_set.add(node_key)

        # Also create a location node for each event.
        for st_event in st_events:
            if st_event.location:
                loc_key = f"loc_{st_event.location}"
                if loc_key not in self._created_space_nodes:
                    node = Node(
                        "SpatialNode",
                        "Location",
                        name=st_event.location,
                        location_name=st_event.location,
                    )
                    batch.append(node)
                    self._created_space_nodes[loc_key] = node

        for i in range(0, len(batch), 200):
            sub = Subgraph(nodes=batch[i:i + 200])
            self.graph.create(sub)

        self._stats['space_nodes'] = len(batch)
        print(f"      空间节点: {len(batch)} 个")

    def _create_st_event_nodes(
        self,
        st_events: List[SpatioTemporalEvent],
        entity_mapping: Dict[str, str],
    ) -> None:
        """Create spatiotemporal event nodes."""
        print("    创建时空事件节点...")
        batch = []

        for st_event in st_events:
            canonical_name = entity_mapping.get(st_event.name, st_event.name)

            node = Node(
                "SpatioTemporalEvent",
                "时空事件",
                event_id=st_event.event_id,
                name=canonical_name,
                event_type=st_event.event_type.value,
                description=st_event.description[:500],
                trigger=st_event.trigger,
                location=st_event.location,
                time=st_event.time,
                source_segment=st_event.source_segment,
                confidence=st_event.confidence,
            )

            # Add time-interval information.
            if st_event.time_interval:
                node["interval_id"] = st_event.time_interval.interval_id
                node["interval_description"] = st_event.time_interval.description
                if st_event.time_interval.duration_days is not None:
                    node["duration_days"] = st_event.time_interval.duration_days

            # Add spatial-coordinate information.
            if st_event.spatial_coordinate:
                coord = st_event.spatial_coordinate
                node["longitude"] = coord.longitude
                node["latitude"] = coord.latitude
                node["elevation"] = coord.elevation

            # Add all attributes.
            for attr_name, attr_value in st_event.attributes.items():
                node[attr_name] = attr_value

            batch.append(node)
            self._created_event_nodes[canonical_name] = node

        for i in range(0, len(batch), 200):
            sub = Subgraph(nodes=batch[i:i + 200])
            self.graph.create(sub)

        print(f"      时空事件节点: {len(batch)} 个")

        # Link the event to its time node.
        self._link_events_to_time(st_events)
        # Link the event to its spatial node.
        self._link_events_to_space(st_events)

    def _link_events_to_time(
        self,
        st_events: List[SpatioTemporalEvent],
    ) -> None:
        """Link events to time nodes."""
        rel_batch = []

        for st_event in st_events:
            event_node = self._created_event_nodes.get(st_event.name)
            if event_node is None:
                continue

            if st_event.time_interval:
                interval_node = self._created_time_nodes.get(
                    st_event.time_interval.interval_id
                )
                if interval_node:
                    rel = Relationship(
                        event_node,
                        "OCCURS_DURING",
                        interval_node,
                        description=st_event.time_interval.description,
                    )
                    rel_batch.append(rel)

        for i in range(0, len(rel_batch), 200):
            sub = Subgraph(relationships=rel_batch[i:i + 200])
            self.graph.create(sub)

        self._stats['temporal_relations'] += len(rel_batch)

    def _link_events_to_space(
        self,
        st_events: List[SpatioTemporalEvent],
    ) -> None:
        """Link events to spatial nodes."""
        rel_batch = []

        for st_event in st_events:
            event_node = self._created_event_nodes.get(st_event.name)
            if event_node is None:
                continue

            # Link to the coordinate node.
            if st_event.spatial_coordinate:
                coord = st_event.spatial_coordinate
                coord_key = (
                    f"{coord.longitude}_{coord.latitude}_{coord.elevation}"
                )
                coord_node = self._created_space_nodes.get(coord_key)
                if coord_node:
                    rel = Relationship(
                        event_node,
                        "LOCATED_AT",
                        coord_node,
                    )
                    rel_batch.append(rel)

            # Link to the named-location node.
            if st_event.location:
                loc_key = f"loc_{st_event.location}"
                loc_node = self._created_space_nodes.get(loc_key)
                if loc_node:
                    rel = Relationship(
                        event_node,
                        "LOCATED_AT",
                        loc_node,
                    )
                    rel_batch.append(rel)

        for i in range(0, len(rel_batch), 200):
            sub = Subgraph(relationships=rel_batch[i:i + 200])
            self.graph.create(sub)

        self._stats['spatial_relations'] += len(rel_batch)

    def _create_temporal_relations(
        self,
        st_events: List[SpatioTemporalEvent],
    ) -> None:
        """Create temporal relationships using Allen interval relations."""
        print("    创建时间关系...")
        rel_batch = []
        seen: set = set()

        for st_event in st_events:
            if st_event.time_interval is None:
                continue

            interval_node = self._created_time_nodes.get(
                st_event.time_interval.interval_id
            )
            if interval_node is None:
                continue

            for head_name, allen_rel, tail_name in st_event.time_relations:
                # Find the corresponding target interval.
                tail_event = next(
                    (e for e in st_events if e.name == tail_name), None
                )
                if tail_event is None or tail_event.time_interval is None:
                    continue

                tail_interval_node = self._created_time_nodes.get(
                    tail_event.time_interval.interval_id
                )
                if tail_interval_node is None:
                    continue

                rel_key = (
                    st_event.time_interval.interval_id,
                    allen_rel.value,
                    tail_event.time_interval.interval_id,
                )
                if rel_key in seen:
                    continue
                seen.add(rel_key)

                rel = Relationship(
                    interval_node,
                    allen_rel.value,
                    tail_interval_node,
                )
                rel_batch.append(rel)

        for i in range(0, len(rel_batch), 200):
            sub = Subgraph(relationships=rel_batch[i:i + 200])
            self.graph.create(sub)

        self._stats['temporal_relations'] += len(rel_batch)
        print(f"      时间关系: {len(rel_batch)} 条")

    def _create_spatial_relations(
        self,
        st_events: List[SpatioTemporalEvent],
    ) -> None:
        """Create spatial relationships."""
        print("    创建空间关系...")
        rel_batch = []
        seen: set = set()

        for st_event in st_events:
            head_node = self._created_event_nodes.get(st_event.name)
            if head_node is None:
                continue

            for sr in st_event.spatial_relations:
                if not sr.tail_entity:
                    continue

                tail_node = self._created_event_nodes.get(sr.tail_entity)
                if tail_node is None:
                    continue

                rel_key = (
                    st_event.name,
                    sr.relation_type,
                    sr.tail_entity,
                )
                if rel_key in seen:
                    continue
                seen.add(rel_key)

                # Determine the relationship type.
                if sr.direction:
                    rel_type = sr.direction.value
                elif sr.topology:
                    rel_type = sr.topology.value
                else:
                    rel_type = "SPATIAL_RELATED_TO"

                rel = Relationship(
                    head_node,
                    rel_type,
                    tail_node,
                    description=sr.description,
                    distance_value=sr.distance_value,
                    distance_unit=(
                        sr.distance_unit.value if sr.distance_unit else None
                    ),
                    confidence=sr.confidence,
                )
                rel_batch.append(rel)

        for i in range(0, len(rel_batch), 200):
            sub = Subgraph(relationships=rel_batch[i:i + 200])
            self.graph.create(sub)

        self._stats['spatial_relations'] += len(rel_batch)
        print(f"      空间关系: {len(rel_batch)} 条")

    def _create_timeline_relations(
        self,
        st_events: List[SpatioTemporalEvent],
    ) -> None:
        """Create PRECEDES and CONCURRENT_WITH timeline relationships."""
        print("    创建时间线关系...")
        rel_batch = []

        # Select events with time information and sort chronologically.
        sorted_events = sorted(
            [
                e for e in st_events
                if e.time_interval and e.time_interval.begins
                and e.time_interval.begins.datetime_value
            ],
            key=lambda e: e.time_interval.begins.datetime_value,  # type: ignore
        )

        seen: set = set()
        for i in range(len(sorted_events)):
            for j in range(i + 1, len(sorted_events)):
                a = sorted_events[i]
                b = sorted_events[j]

                a_node = self._created_event_nodes.get(a.name)
                b_node = self._created_event_nodes.get(b.name)
                if a_node is None or b_node is None:
                    continue

                rel_key = (a.name, b.name)
                if rel_key in seen:
                    continue
                seen.add(rel_key)

                # Determine the temporal relationship.
                a_end = a.time_interval.ends  # type: ignore
                b_beg = b.time_interval.begins  # type: ignore

                if a_end and a_end.datetime_value and b_beg.datetime_value:
                    if a_end.datetime_value == b_beg.datetime_value:
                        # Concurrent occurrence
                        rel = Relationship(
                            a_node, "CONCURRENT_WITH", b_node
                        )
                    else:
                        # Sequential occurrence
                        rel = Relationship(
                            a_node, "PRECEDES", b_node
                        )
                    rel_batch.append(rel)

        for i in range(0, len(rel_batch), 200):
            sub = Subgraph(relationships=rel_batch[i:i + 200])
            self.graph.create(sub)

        self._stats['timeline_relations'] = len(rel_batch)
        print(f"      时间线关系: {len(rel_batch)} 条")

    def _clear_st_data(self) -> None:
        """Clear existing spatiotemporal records."""
        try:
            self.graph.run(
                "MATCH (n:SpatioTemporalEvent) DETACH DELETE n"
            )
            self.graph.run(
                "MATCH (n:TemporalNode) DETACH DELETE n"
            )
            self.graph.run(
                "MATCH (n:SpatialNode) DETACH DELETE n"
            )
            print("  已清除时空数据")
        except Exception as e:
            print(f"  清除时空数据失败: {e}")

    # Statistics

    def _print_stats(self) -> None:
        """Print enrichment statistics."""
        print(f"\n  时空知识图谱构建统计:")
        print(f"     时间节点: {self._stats['time_nodes']}")
        print(f"     空间节点: {self._stats['space_nodes']}")
        print(f"     时空事件: {self._stats['st_events']}")
        print(f"     时间关系: {self._stats['temporal_relations']}")
        print(f"     空间关系: {self._stats['spatial_relations']}")
        print(f"     时间线关系: {self._stats['timeline_relations']}")
        if self._stats['errors']:
            print(f"     错误: {self._stats['errors']}")

    def get_stats(self) -> dict:
        """Return enrichment statistics."""
        return dict(self._stats)


# Spatiotemporal query interface

class SpatioTemporalQuery:
    """Query spatiotemporal graph information."""

    def __init__(
        self,
        neo4j_uri: str = "neo4j://127.0.0.1:7687",
        neo4j_user: str = "neo4j",
        neo4j_password: str = "",
    ):
        """Initialize the spatiotemporal query interface."""
        self.graph = Graph(neo4j_uri, auth=(neo4j_user, neo4j_password))

    def query_by_time_range(
        self,
        start_time: str,
        end_time: str,
        event_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Query events within a time range."""
        # Parse the time range.
        parser = TimeParser()
        start_interval = parser.parse_time(start_time)
        end_interval = parser.parse_time(end_time)

        if not start_interval or not end_interval:
            return []

        start_dt = (
            start_interval.begins.datetime_value.isoformat()
            if start_interval.begins and start_interval.begins.datetime_value
            else start_time
        )
        end_dt = (
            end_interval.ends.datetime_value.isoformat()
            if end_interval.ends and end_interval.ends.datetime_value
            else end_time
        )

        # Build the Cypher query.
        cypher = """
        MATCH (e:SpatioTemporalEvent)-[:OCCURS_DURING]->(ti:TimeInterval)
        MATCH (ti)-[:HAS_BEGINNING]->(b:TimeInstant)
        MATCH (ti)-[:HAS_END]->(ed:TimeInstant)
        WHERE b.datetime_value >= $start_dt AND ed.datetime_value <= $end_dt
        """
        params: Dict[str, Any] = {
            "start_dt": start_dt,
            "end_dt": end_dt,
            "limit": limit,
        }

        if event_type:
            cypher += " AND e.event_type = $event_type"
            params["event_type"] = event_type

        cypher += """
        RETURN e.name AS name,
               e.event_type AS event_type,
               e.description AS description,
               e.location AS location,
               ti.description AS time_description,
               ti.duration_days AS duration_days,
               e.confidence AS confidence
        ORDER BY b.datetime_value ASC
        LIMIT $limit
        """

        try:
            result = self.graph.run(cypher, params).data()
            return result
        except Exception as e:
            print(f"查询失败: {e}")
            return []

    def query_by_spatial_relation(
        self,
        entity: str,
        relation: Optional[str] = None,
        distance: Optional[float] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Query by spatial relationship."""
        # Build a flexible Cypher query.
        params: Dict[str, Any] = {
            "entity": entity,
            "limit": limit,
        }

        if relation:
            # Search a particular relationship type.
            cypher = f"""
            MATCH (e:SpatioTemporalEvent)-[r:{relation}]->(target:SpatioTemporalEvent)
            WHERE e.name = $entity OR e.location CONTAINS $entity
            RETURN target.name AS name,
                   target.event_type AS event_type,
                   target.description AS description,
                   target.location AS location,
                   type(r) AS relation_type,
                   r.distance_value AS distance_value,
                   r.distance_unit AS distance_unit,
                   r.confidence AS confidence
            LIMIT $limit
            """
        elif distance is not None:
            # Query by distance.
            cypher = """
            MATCH (e:SpatioTemporalEvent)-[r]->(target:SpatioTemporalEvent)
            WHERE (e.name = $entity OR e.location CONTAINS $entity)
              AND r.distance_value IS NOT NULL
              AND r.distance_value <= $distance
            RETURN target.name AS name,
                   target.event_type AS event_type,
                   target.description AS description,
                   target.location AS location,
                   type(r) AS relation_type,
                   r.distance_value AS distance_value,
                   r.distance_unit AS distance_unit,
                   r.confidence AS confidence
            ORDER BY r.distance_value ASC
            LIMIT $limit
            """
            params["distance"] = distance
        else:
            # Query all spatially related entities.
            cypher = """
            MATCH (e:SpatioTemporalEvent)-[r]->(target:SpatioTemporalEvent)
            WHERE (e.name = $entity OR e.location CONTAINS $entity)
              AND (type(r) IN [
                'NORTH_OF', 'SOUTH_OF', 'EAST_OF', 'WEST_OF',
                'NORTHEAST_OF', 'NORTHWEST_OF', 'SOUTHEAST_OF', 'SOUTHWEST_OF',
                'CONTAINS', 'WITHIN', 'OVERLAPS', 'TOUCHES', 'DISJOINT',
                'LOCATED_AT', 'SPATIAL_RELATED_TO'
              ])
            RETURN target.name AS name,
                   target.event_type AS event_type,
                   target.description AS description,
                   target.location AS location,
                   type(r) AS relation_type,
                   r.distance_value AS distance_value,
                   r.distance_unit AS distance_unit,
                   r.confidence AS confidence
            LIMIT $limit
            """

        try:
            result = self.graph.run(cypher, params).data()
            return result
        except Exception as e:
            print(f"查询失败: {e}")
            return []

    def get_event_timeline(
        self,
        entity_name: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Retrieve the event timeline."""
        cypher = """
        MATCH (e:SpatioTemporalEvent)-[:OCCURS_DURING]->(ti:TimeInterval)
        MATCH (ti)-[:HAS_BEGINNING]->(b:TimeInstant)
        WHERE e.name CONTAINS $entity_name
           OR e.location CONTAINS $entity_name
           OR e.description CONTAINS $entity_name
        OPTIONAL MATCH (e)-[r:PRECEDES|CONCURRENT_WITH]->(next:SpatioTemporalEvent)
        RETURN e.name AS name,
               e.event_type AS event_type,
               e.description AS description,
               e.location AS location,
               ti.description AS time_description,
               ti.duration_days AS duration_days,
               b.datetime_value AS start_datetime,
               e.confidence AS confidence,
               collect(DISTINCT next.name) AS next_events
        ORDER BY b.datetime_value ASC
        LIMIT $limit
        """

        try:
            result = self.graph.run(
                cypher,
                entity_name=entity_name,
                limit=limit,
            ).data()
            return result
        except Exception as e:
            print(f"查询失败: {e}")
            return []

    def get_spatial_context(
        self,
        entity_name: str,
    ) -> Dict[str, Any]:
        """Retrieve the spatial context."""
        context: Dict[str, Any] = {
            "entity": entity_name,
            "coordinate": None,
            "location": None,
            "nearby_entities": [],
            "contained_by": [],
            "contains": [],
            "spatial_relations": [],
        }

        # 1. Retrieve coordinates.
        cypher = """
        MATCH (e:SpatioTemporalEvent)
        WHERE e.name = $entity_name
        RETURN e.longitude AS longitude,
               e.latitude AS latitude,
               e.elevation AS elevation,
               e.location AS location
        LIMIT 1
        """
        try:
            result = self.graph.run(cypher, entity_name=entity_name).data()
            if result:
                row = result[0]
                if row.get("longitude") or row.get("latitude"):
                    context["coordinate"] = {
                        "longitude": row.get("longitude"),
                        "latitude": row.get("latitude"),
                        "elevation": row.get("elevation"),
                    }
                context["location"] = row.get("location")
        except Exception:
            pass

        # 2. Retrieve nearby entities through directional relationships.
        cypher = """
        MATCH (e:SpatioTemporalEvent)-[r]->(target:SpatioTemporalEvent)
        WHERE e.name = $entity_name
          AND type(r) IN [
            'NORTH_OF', 'SOUTH_OF', 'EAST_OF', 'WEST_OF',
            'NORTHEAST_OF', 'NORTHWEST_OF', 'SOUTHEAST_OF', 'SOUTHWEST_OF'
          ]
        RETURN target.name AS name,
               target.event_type AS event_type,
               type(r) AS direction,
               r.distance_value AS distance_value,
               r.distance_unit AS distance_unit,
               r.description AS description
        LIMIT 20
        """
        try:
            result = self.graph.run(cypher, entity_name=entity_name).data()
            context["nearby_entities"] = result
        except Exception:
            pass

        # 3. Retrieve containment relationships.
        cypher = """
        MATCH (e:SpatioTemporalEvent)-[r:WITHIN]->(parent:SpatioTemporalEvent)
        WHERE e.name = $entity_name
        RETURN parent.name AS name, parent.event_type AS event_type
        LIMIT 10
        """
        try:
            result = self.graph.run(cypher, entity_name=entity_name).data()
            context["contained_by"] = result
        except Exception:
            pass

        cypher = """
        MATCH (e:SpatioTemporalEvent)-[r:CONTAINS]->(child:SpatioTemporalEvent)
        WHERE e.name = $entity_name
        RETURN child.name AS name, child.event_type AS event_type
        LIMIT 10
        """
        try:
            result = self.graph.run(cypher, entity_name=entity_name).data()
            context["contains"] = result
        except Exception:
            pass

        # 4. Retrieve all spatial relationships.
        cypher = """
        MATCH (e:SpatioTemporalEvent)-[r]->(target)
        WHERE e.name = $entity_name
          AND (target:SpatioTemporalEvent OR target:SpatialNode)
        RETURN target.name AS target_name,
               labels(target) AS target_labels,
               type(r) AS relation_type,
               r.description AS description,
               r.distance_value AS distance_value,
               r.distance_unit AS distance_unit
        LIMIT 30
        """
        try:
            result = self.graph.run(cypher, entity_name=entity_name).data()
            context["spatial_relations"] = result
        except Exception:
            pass

        return context


