# -*- coding: utf-8 -*-
"""Extract knowledge from structured tables."""

import re
from typing import Any, List, Dict, Tuple, Optional
from dataclasses import dataclass, field

from extraction.event_extractor import (
    Event, EventKnowledge, EventType, EventRelation
)
from extraction.value_normalizer import normalize_measurement


# Table data structures

@dataclass
class TableData:
    """Parsed table data with headers and rows."""
    table_id: str                           # Table identifier, for example table_35
    title: str                              # Table title read from the current report
    category: str                           # Table category, for example physical or mechanical parameters
    headers: List[str]                      # Merged column headers
    rows: List[Dict[str, str]]              # Data rows mapping column names to values
    raw_row_count: int = 0                  # Original row count


@dataclass
class TableExtractionResult:
    """Combined table-extraction result."""
    events: List[Event] = field(default_factory=list)
    knowledge: List[EventKnowledge] = field(default_factory=list)
    tables_parsed: int = 0
    tables_skipped: int = 0
    table_details: List[Dict] = field(default_factory=list)


# Table classifier

class TableClassifier:
    """Classify tables from their titles and content."""

    # Map title keywords to categories.
    TITLE_KEYWORDS = [
        (r"物理性质", "physical_params"),
        (r"抗剪强度", "shear_strength"),
        (r"力学试验|力学参数|抗压强度|抗拉强度", "mechanical_params"),
        (r"稳定性系数|稳定系数|安全系数|工况", "stability"),
        (r"监测|位移|GNSS|变形速率|裂缝", "monitoring"),
        (r"风险|危险性|易损性", "risk_assessment"),
        (r"滑速|滑移|运动过程", "landslide_speed"),
        (r"堰塞坝|溃坝|溃口|库容", "dam_params"),
        (r"威胁|居民|损失", "threat_info"),
        (r"参数选取|参数选取|计算参数", "stability"),
    ]

    # Image-caption features
    IMAGE_CAPTION_PATTERNS = [
        r"^图\s*\d",
        r"示意图|过程图|俯视图|剖面图|切片图|回水图",
    ]

    @classmethod
    def classify(cls, title: str, first_row_cells: List[str], all_cells_text: str) -> str:
        """Classify a table."""
        # Check whether this is an image-caption table.
        for pattern in cls.IMAGE_CAPTION_PATTERNS:
            if re.search(pattern, title) or re.search(pattern, all_cells_text[:200]):
                return "image_caption"

        # Classify by title keywords.
        for pattern, category in cls.TITLE_KEYWORDS:
            if re.search(pattern, title):
                return category

        # Classify by column-header content.
        header_text = " ".join(first_row_cells)
        if re.search(r"粘聚力|内摩擦角|C\s*\(.*MPa\)|φ|φ\s*\(.*°\)", header_text):
            return "shear_strength"
        if re.search(r"稳定|工况|安全系数", header_text):
            return "stability"
        if re.search(r"密度|含水量|孔隙比|饱和度|液限|塑限", header_text):
            return "physical_params"
        if re.search(r"抗压|抗拉|变形模量|弹性模量|泊松比", header_text):
            return "mechanical_params"
        if re.search(r"位移|变形|GNSS|监测", header_text):
            return "monitoring"
        if re.search(r"风险|危险|易损", header_text):
            return "risk_assessment"
        if re.search(r"滑速|落差|滑坡体积", header_text):
            return "landslide_speed"
        if re.search(r"坝高|库容|溃口|峰值流量", header_text):
            return "dam_params"

        return "unknown"


# Table parser

class TableParser:
    """Parse raw tables into structured TableData objects."""

    # Check whether this is a title row.
    TITLE_PATTERN = re.compile(r"表\s*\d+[\.\-]\d+")

    # Check whether the cell is numeric.
    NUMERIC_PATTERN = re.compile(r"^[\d\.\-＋\+\s～/×xX]+$")

    @classmethod
    def parse_table(cls, raw_rows: List[List[str]], table_index: int) -> Optional[TableData]:
        """Parse one table."""
        if not raw_rows or len(raw_rows) < 2:
            return None

        # Discard completely empty rows.
        raw_rows = [
            [cell.strip() for cell in row]
            for row in raw_rows
            if any(cell.strip() for cell in row)
        ]
        if not raw_rows:
            return None

        # Extract the table title.
        title = ""
        header_start = 0
        first_row_text = " ".join(raw_rows[0])

        # Treat a first row containing a numbered table-title pattern as a title row.
        title_match = cls.TITLE_PATTERN.search(first_row_text)
        if title_match:
            title = first_row_text[:100]
            header_start = 1

        # Detect figure-caption tables, typically one or two rows containing a numbered figure caption.
        all_text = " ".join(" ".join(row) for row in raw_rows)
        if re.search(r"图\s*\d+[\.\-]\d+", all_text) and len(raw_rows) <= 4:
            return None

        # Identify header rows from header_start to the first numeric data row.
        header_rows = []
        data_start = header_start

        for i in range(header_start, len(raw_rows)):
            row = raw_rows[i]
            # Treat a row as data when at least half of its cells are numeric.
            numeric_count = sum(1 for cell in row if cls._is_numeric(cell))
            if numeric_count >= max(2, len(row) // 3):
                data_start = i
                break
            header_rows.append(row)

        if not header_rows:
            # Use the first row as the header when no explicit header is found.
            header_rows = [raw_rows[data_start]] if data_start < len(raw_rows) else []
            data_start += 1

        # Merge multilevel header rows.
        merged_headers = cls._merge_header_rows(header_rows)

        if not merged_headers:
            return None

        # Extract data rows.
        data_rows = []
        for i in range(data_start, len(raw_rows)):
            row = raw_rows[i]
            if len(row) < len(merged_headers):
                # Pad missing columns.
                row = row + [""] * (len(merged_headers) - len(row))
            elif len(row) > len(merged_headers):
                # Truncate extra columns.
                row = row[:len(merged_headers)]

            # Skip repeated headers in continued tables.
            cleaned_row = [cls._clean_header(cell) for cell in row]
            if cleaned_row == merged_headers:
                continue

            row_dict = {}
            for j, header in enumerate(merged_headers):
                row_dict[header] = row[j] if j < len(row) else ""
            data_rows.append(row_dict)

        if not data_rows:
            return None

        # Classification
        category = TableClassifier.classify(
            title, merged_headers, all_text
        )

        return TableData(
            table_id=f"table_{table_index:03d}",
            title=title or f"表格{table_index}",
            category=category,
            headers=merged_headers,
            rows=data_rows,
            raw_row_count=len(raw_rows),
        )

    @classmethod
    def _is_numeric(cls, value: str) -> bool:
        """Check whether a cell is numeric."""
        value = value.strip()
        if not value:
            return False
        return bool(cls.NUMERIC_PATTERN.match(value))

    @classmethod
    def _merge_header_rows(cls, header_rows: List[List[str]]) -> List[str]:
        """Merge multiple header rows into one column-name sequence."""
        if not header_rows:
            return []

        if len(header_rows) == 1:
            # For a single header row, replace blanks with indexed column labels to prevent column shifts.
            result = []
            for idx, h in enumerate(header_rows[0]):
                cleaned = cls._clean_header(h)
                if cleaned:
                    result.append(cleaned)
                else:
                    result.append(f"列{idx + 1}")
            return result

        max_cols = max(len(row) for row in header_rows)
        expanded_rows = []
        for row in header_rows:
            padded = list(row) + [""] * (max_cols - len(row))
            # Word may retain horizontally merged text only in the first cell; propagate the parent header rightward.
            carried = ""
            expanded = []
            for cell in padded:
                cleaned = cls._clean_header(cell)
                if cleaned:
                    carried = cleaned
                expanded.append(cleaned or carried)
            expanded_rows.append(expanded)
        merged = []

        for j in range(max_cols):
            parts = []
            for row in expanded_rows:
                if j < len(row) and row[j].strip():
                    parts.append(row[j].strip())
            # Combine header levels.
            if parts:
                # Keep repeated parent/child header text only once.
                unique_parts = []
                seen = set()
                for p in parts:
                    if p not in seen:
                        unique_parts.append(p)
                        seen.add(p)
                merged.append(" ".join(unique_parts))
            else:
                merged.append(f"列{j+1}")

        # Make column names unique so later dictionary entries do not overwrite earlier columns.
        counts: Dict[str, int] = {}
        unique_headers = []
        for header in merged:
            counts[header] = counts.get(header, 0) + 1
            suffix = f"_{counts[header]}" if counts[header] > 1 else ""
            unique_headers.append(f"{header}{suffix}")
        return unique_headers

    @classmethod
    def _clean_header(cls, header: str) -> str:
        """Clean header text."""
        header = header.strip()
        # Remove newlines.
        header = re.sub(r"\n+", " ", header)
        # Collapse whitespace.
        header = re.sub(r"\s+", " ", header)
        return header


# Event generator

class TableEventGenerator:
    """Convert parsed tables into Event and EventKnowledge records."""

    # Parameter-unit mapping for attribute normalization
    PARAM_UNITS = {
        "密度": "g/cm³",
        "含水量": "%",
        "孔隙比": "",
        "孔隙率": "%",
        "饱和度": "%",
        "液限": "%",
        "塑限": "%",
        "粘聚力": "MPa",
        "内摩擦角": "°",
        "抗压强度": "MPa",
        "抗拉强度": "MPa",
        "变形模量": "×10⁴MPa",
        "弹性模量": "×10⁴MPa",
        "泊松比": "",
        "稳定系数": "",
        "安全系数": "",
        "水平位移": "mm",
        "垂直位移": "mm",
        "变形速率": "mm/月",
        "滑速": "m/s",
        "坝高": "m",
        "库容": "m³",
        "溃口深度": "m",
        "溃口宽度": "m",
        "峰值流量": "m³/s",
        "质心落差": "m",
        "滑坡体积": "m³",
    }

    # Event counter
    _event_counter = 0
    _knowledge_counter = 0

    @classmethod
    def _next_event_id(cls) -> str:
        cls._event_counter += 1
        return f"tbl_evt_{cls._event_counter:04d}"

    @classmethod
    def _next_knowledge_id(cls) -> str:
        cls._knowledge_counter += 1
        return f"tbl_rel_{cls._knowledge_counter:04d}"

    @classmethod
    def reset_counters(cls):
        cls._event_counter = 0
        cls._knowledge_counter = 0

    @classmethod
    def generate_events(cls, tables: List[TableData], source_name: str = "") -> Tuple[List[Event], List[EventKnowledge], List[Dict]]:
        """Generate events and relationships from tables."""
        cls.reset_counters()
        all_events = []
        all_knowledge = []
        table_details = []

        for table in tables:
            if table.category == "image_caption":
                table_details.append({
                    "table_id": table.table_id,
                    "title": table.title,
                    "category": table.category,
                    "rows": 0,
                    "events": 0,
                    "status": "skipped",
                })
                continue

            events, knowledge = cls._table_to_events(table, source_name)
            all_events.extend(events)
            all_knowledge.extend(knowledge)

            table_details.append({
                "table_id": table.table_id,
                "title": table.title,
                "category": table.category,
                "rows": len(table.rows),
                "events": len(events),
                "status": "ok" if events else "empty",
            })

        return all_events, all_knowledge, table_details

    @classmethod
    def _table_to_events(cls, table: TableData, source_name: str) -> Tuple[List[Event], List[EventKnowledge]]:
        """Convert one table into events."""
        events = []
        knowledge = []

        # Select the generation strategy by table category.
        if table.category == "physical_params":
            events, knowledge = cls._gen_physical_params(table, source_name)
        elif table.category == "shear_strength":
            events, knowledge = cls._gen_shear_strength(table, source_name)
        elif table.category == "mechanical_params":
            events, knowledge = cls._gen_mechanical_params(table, source_name)
        elif table.category == "stability":
            events, knowledge = cls._gen_stability(table, source_name)
        elif table.category == "monitoring":
            events, knowledge = cls._gen_monitoring(table, source_name)
        elif table.category == "risk_assessment":
            events, knowledge = cls._gen_risk_assessment(table, source_name)
        elif table.category == "landslide_speed":
            events, knowledge = cls._gen_landslide_speed(table, source_name)
        elif table.category == "dam_params":
            events, knowledge = cls._gen_dam_params(table, source_name)
        elif table.category == "threat_info":
            events, knowledge = cls._gen_threat_info(table, source_name)
        else:
            events, knowledge = cls._gen_generic(table, source_name)

        for event in events:
            event.normalized_attributes = {
                key: normalize_measurement(value, key)
                for key, value in event.attributes.items()
            }

        return events, knowledge

    # Event generation by table category

    @classmethod
    def _gen_physical_params(cls, table: TableData, source: str) -> Tuple[List[Event], List[EventKnowledge]]:
        """Generate observation events from physical-parameter tables."""
        events = []
        for row in table.rows:
            sample_header, sample_id = cls._find_field_entry(
                row, ["土样编号", "样品编号", "编号", "土样 编号"]
            )
            if not sample_id:
                continue

            attrs = {key: val for key, val in row.items() if val.strip()}

            event = Event(
                event_id=cls._next_event_id(),
                event_type=EventType.OBSERVATION,
                name=f"{sample_id}物理性质试验",
                description=cls._describe_row(
                    f"{cls._sample_kind(sample_header)}{sample_id}",
                    "物理性质试验", row, sample_header,
                ),
                attributes=attrs,
                source_segment=table.table_id,
                source_text=f"[{table.title}] {sample_id}",
                confidence=0.95,
            )
            events.append(event)

        return events, []

    @classmethod
    def _gen_shear_strength(cls, table: TableData, source: str) -> Tuple[List[Event], List[EventKnowledge]]:
        """Generate observation events from shear-strength tables."""
        events = []
        for row in table.rows:
            sample_header, sample_id = cls._find_field_entry(
                row, ["土样编号", "样品编号", "滑带土类型", "编号"]
            )
            if not sample_id:
                continue

            attrs = {key: val for key, val in row.items() if val.strip()}

            event = Event(
                event_id=cls._next_event_id(),
                event_type=EventType.OBSERVATION,
                name=f"{sample_id}抗剪强度试验",
                description=cls._describe_row(
                    f"{cls._sample_kind(sample_header)}{sample_id}",
                    "抗剪强度试验", row, sample_header,
                ),
                attributes=attrs,
                source_segment=table.table_id,
                source_text=f"[{table.title}] {sample_id}",
                confidence=0.95,
            )
            events.append(event)

        return events, []

    @classmethod
    def _gen_mechanical_params(cls, table: TableData, source: str) -> Tuple[List[Event], List[EventKnowledge]]:
        """Generate observation events from mechanical-parameter tables."""
        events = []
        for row in table.rows:
            sample_header, sample_id = cls._find_field_entry(
                row, ["土样编号", "样品编号", "编号"]
            )
            if not sample_id:
                continue

            attrs = {key: val for key, val in row.items() if val.strip()}

            event = Event(
                event_id=cls._next_event_id(),
                event_type=EventType.OBSERVATION,
                name=f"{sample_id}力学试验",
                description=cls._describe_row(
                    f"{cls._sample_kind(sample_header)}{sample_id}",
                    "力学试验", row, sample_header,
                ),
                attributes=attrs,
                source_segment=table.table_id,
                source_text=f"[{table.title}] {sample_id}",
                confidence=0.95,
            )
            events.append(event)

        return events, []

    @classmethod
    def _gen_stability(cls, table: TableData, source: str) -> Tuple[List[Event], List[EventKnowledge]]:
        """Generate observations and attribute relationships from stability-factor tables."""
        events = []
        knowledge = []

        for row in table.rows:
            profile_header, profile = cls._find_field_entry(
                row, ["剖面", "变形区", "剖面 工况", "变形阶段"]
            )
            if not profile:
                continue

            attrs = {}
            for key, val in row.items():
                if val.strip():
                    attrs[key] = val

            event = Event(
                event_id=cls._next_event_id(),
                event_type=EventType.OBSERVATION,
                name=f"{profile}稳定性计算",
                description=cls._describe_row(profile, "稳定性计算", row, profile_header),
                attributes=attrs,
                source_segment=table.table_id,
                source_text=f"[{table.title}] {profile}",
                confidence=0.95,
            )
            events.append(event)

        return events, knowledge

    @classmethod
    def _gen_monitoring(cls, table: TableData, source: str) -> Tuple[List[Event], List[EventKnowledge]]:
        """Generate observation events from monitoring tables."""
        events = []
        for row in table.rows:
            point_header, point_id = cls._find_field_entry(
                row, ["编号", "点号", "GNSS", "监测点"]
            )
            if not point_id:
                continue

            attrs = {}
            for key, val in row.items():
                if val.strip():
                    attrs[key] = val

            event = Event(
                event_id=cls._next_event_id(),
                event_type=EventType.OBSERVATION,
                name=f"{point_id}监测数据",
                description=cls._describe_row(point_id, "监测", row, point_header),
                attributes=attrs,
                source_segment=table.table_id,
                source_text=f"[{table.title}] {point_id}",
                confidence=0.90,
            )
            events.append(event)

        return events, []

    @classmethod
    def _gen_risk_assessment(cls, table: TableData, source: str) -> Tuple[List[Event], List[EventKnowledge]]:
        """Generate outcome events from risk-assessment tables."""
        events = []
        for row in table.rows:
            zone_header, zone = cls._find_field_entry(
                row, ["分区", "变形区", "剖面"]
            )
            if not zone:
                continue

            attrs = {}
            for key, val in row.items():
                if val.strip():
                    attrs[key] = val

            event = Event(
                event_id=cls._next_event_id(),
                event_type=EventType.RESULT,
                name=f"{zone}风险评估",
                description=cls._describe_row(zone, "风险评估", row, zone_header),
                attributes=attrs,
                source_segment=table.table_id,
                source_text=f"[{table.title}] {zone}",
                confidence=0.95,
            )
            events.append(event)

        return events, []

    @classmethod
    def _gen_landslide_speed(cls, table: TableData, source: str) -> Tuple[List[Event], List[EventKnowledge]]:
        """Generate disaster events from sliding-velocity or movement-parameter tables."""
        events = []
        for row in table.rows:
            profile_header, profile = cls._find_field_entry(row, ["剖面", "变形区"])
            if not profile:
                continue

            attrs = {}
            for key, val in row.items():
                if val.strip():
                    attrs[key] = val

            event = Event(
                event_id=cls._next_event_id(),
                event_type=EventType.DISASTER,
                name=f"{profile}滑坡运动参数",
                description=cls._describe_row(
                    profile, "滑坡运动参数", row, profile_header
                ),
                attributes=attrs,
                source_segment=table.table_id,
                source_text=f"[{table.title}] {profile}",
                confidence=0.95,
            )
            events.append(event)

        return events, []

    @classmethod
    def _gen_dam_params(cls, table: TableData, source: str) -> Tuple[List[Event], List[EventKnowledge]]:
        """Generate outcome events from landslide-dam parameter tables."""
        events = []
        for row in table.rows:
            zone_header, zone = cls._find_field_entry(
                row, ["变形区", "编号", "分区"]
            )
            if not zone:
                continue

            attrs = {}
            for key, val in row.items():
                if val.strip():
                    attrs[key] = val

            event = Event(
                event_id=cls._next_event_id(),
                event_type=EventType.RESULT,
                name=f"{zone}堰塞坝参数",
                description=cls._describe_row(zone, "堰塞坝参数", row, zone_header),
                attributes=attrs,
                source_segment=table.table_id,
                source_text=f"[{table.title}] {zone}",
                confidence=0.95,
            )
            events.append(event)

        return events, []

    @classmethod
    def _gen_threat_info(cls, table: TableData, source: str) -> Tuple[List[Event], List[EventKnowledge]]:
        """Generate outcome events from threatened-object tables."""
        events = []
        for row in table.rows:
            zone_header, zone = cls._find_field_entry(row, ["分区", "变形区"])
            if not zone:
                continue

            attrs = {}
            for key, val in row.items():
                if val.strip():
                    attrs[key] = val

            event = Event(
                event_id=cls._next_event_id(),
                event_type=EventType.RESULT,
                name=f"{zone}威胁对象",
                description=cls._describe_row(zone, "威胁对象", row, zone_header),
                attributes=attrs,
                source_segment=table.table_id,
                source_text=f"[{table.title}] {zone}",
                confidence=0.95,
            )
            events.append(event)

        return events, []

    @classmethod
    def _gen_generic(cls, table: TableData, source: str) -> Tuple[List[Event], List[EventKnowledge]]:
        """Process a generic table by turning each data row into an observation event."""
        events = []
        for row in table.rows:
            # Use the first nonempty value as an identifier.
            first_val = ""
            for val in row.values():
                if val.strip():
                    first_val = val.strip()
                    break
            if not first_val:
                continue

            attrs = {k: v for k, v in row.items() if v.strip()}

            event = Event(
                event_id=cls._next_event_id(),
                event_type=EventType.OBSERVATION,
                name=f"{first_val[:20]}数据记录",
                description=f"来自表格{table.title}的数据记录",
                attributes=attrs,
                source_segment=table.table_id,
                source_text=f"[{table.title}] {first_val[:50]}",
                confidence=0.80,
            )
            events.append(event)

        return events, []

    # Utility methods

    @classmethod
    def _find_field(cls, row: Dict[str, str], candidates: List[str]) -> str:
        """Find a field in a row using fuzzy matching."""
        return cls._find_field_entry(row, candidates)[1]

    @classmethod
    def _find_field_entry(
        cls, row: Dict[str, str], candidates: List[str]
    ) -> Tuple[str, str]:
        """Return the matched header and original identifier without inferring sample type from an ID prefix."""
        for candidate in candidates:
            for key, val in row.items():
                if candidate in key and val.strip():
                    return key, val.strip()
        # Fall back to the first nonempty value.
        for key, val in row.items():
            if val.strip() and not cls._is_numeric(val):
                return key, val.strip()[:30]
        return "", ""

    @staticmethod
    def _sample_kind(header: str) -> str:
        """Identify sample category only from the current report's column headers."""
        compact = re.sub(r"\s+", "", header)
        if "滑带土" in compact:
            return "滑带土"
        if "土样" in compact:
            return "土样"
        return "样品"

    @staticmethod
    def _describe_row(
        subject: str, topic: str, row: Dict[str, str], identifier_header: str = ""
    ) -> str:
        fields = [
            header for header, value in row.items()
            if header != identifier_header and value.strip()
        ]
        description = f"{subject}的{topic}记录"
        return f"{description}；字段：{'、'.join(fields)}" if fields else description

    @classmethod
    def _is_numeric(cls, value: str) -> bool:
        """Check whether a string is purely numeric."""
        value = value.strip()
        if not value:
            return False
        return bool(re.match(r"^[\d\.\-＋\+\s～/×xX]+$", value))


# Main extractor

class TableExtractor:
    """Coordinate table parsing, classification and event generation."""

    def __init__(self, verbose: bool = True):
        self.verbose = verbose

    def extract_from_tables(
        self,
        stored_tables: List[Any],
        source_name: str = "",
    ) -> TableExtractionResult:
        """Generate table-event knowledge directly from StoredTable objects."""
        parsed_tables: List[TableData] = []
        skipped = 0

        for stored in stored_tables:
            headers = list(getattr(stored, "headers", []) or [])
            rows = [dict(row) for row in (getattr(stored, "data_rows", []) or [])]
            category = str(getattr(stored, "category", "unknown") or "unknown")
            if not headers or not rows or category == "image_caption":
                skipped += 1
                continue
            parsed_tables.append(TableData(
                table_id=str(getattr(stored, "table_id", "")),
                title=str(getattr(stored, "title", "") or "未命名表格"),
                category=category,
                headers=headers,
                rows=rows,
                raw_row_count=int(
                    getattr(stored, "row_count", len(rows)) or len(rows)
                ),
            ))

        if self.verbose:
            print(f"📊 表格知识抽取：有效 {len(parsed_tables)} 个，跳过 {skipped} 个")

        # Category statistics
        category_stats = {}
        for t in parsed_tables:
            category_stats[t.category] = category_stats.get(t.category, 0) + 1
        if self.verbose and category_stats:
            print(f"   表格分类:")
            for cat, count in sorted(category_stats.items(), key=lambda x: -x[1]):
                print(f"      {cat}: {count} 个")

        events, knowledge, table_details = TableEventGenerator.generate_events(
            parsed_tables, source_name
        )

        if self.verbose:
            print(f"   ✅ 生成事件: {len(events)} 个")
            print(f"   ✅ 生成关系: {len(knowledge)} 条")

        return TableExtractionResult(
            events=events,
            knowledge=knowledge,
            tables_parsed=len(parsed_tables),
            tables_skipped=skipped,
            table_details=table_details,
        )
