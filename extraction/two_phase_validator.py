# -*- coding: utf-8 -*-
"""Quality-control workflow for semantic consistency and schema/rule checking."""

import json
import re
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass, field

from schema.ontology_loader import OntologyLoader
from schema.schema_config import SchemaConfig
from extraction.event_extractor import Event, EventKnowledge, EventType, EventRelation


@dataclass
class ValidationReport:
    """A quality-control report with errors, warnings, repairs and review flags."""
    total_checked: int = 0              # Total checks
    passed: int = 0                     # Passed checks
    failed: int = 0                     # Failed checks
    errors: List[Dict] = field(default_factory=list)  # Error details
    warnings: List[Dict] = field(default_factory=list)  # Warning details
    repairs: List[Dict] = field(default_factory=list)  # Automatic repair records
    review_items: List[Dict] = field(default_factory=list)  # Recommended manual review


class TwoPhaseValidator:
    """Run semantic consistency screening and schema/rule checks."""

    # Expected units for numeric attributes
    NUMERIC_UNITS = {
        '体积': ['m³', '万m³', '×10⁴m³', 'km³'],
        '面积': ['m²', 'km²', '亩', 'ha'],
        '长度': ['m', 'km', 'cm', 'mm'],
        '宽度': ['m', 'km', 'cm', 'mm'],
        '厚度': ['m', 'cm', 'mm'],
        '深度': ['m', 'cm'],
        '高度': ['m'],
        '角度': ['°', '度'],
        '坡度': ['°', '度'],
        '坡向': ['°'],
        '速度': ['m/s', 'mm/d', 'cm/d'],
        '位移': ['mm', 'cm', 'm'],
        '降雨量': ['mm', 'mm/d', 'mm/h'],
        '水位': ['m'],
        '密度': ['g/cm³', 'kg/m³'],
        '强度': ['MPa', 'kPa', 'Pa'],
        '模量': ['MPa', 'GPa'],
        '渗透系数': ['m/s', 'cm/s', 'm/d'],
        '内摩擦角': ['°', '度'],
        '内聚力': ['kPa', 'MPa'],
        '人口': ['人', '万人'],
        '金额': ['元', '万元', '亿元'],
    }

    def __init__(self, ontology_loader: OntologyLoader = None):
        self.loader = ontology_loader or OntologyLoader()
        self.schema_config = SchemaConfig(self.loader)

    # Semantic consistency screening, with optional LLM support

    def semantic_validation(
        self,
        events: List[Event],
        knowledge: List[EventKnowledge],
        llm_caller=None,
    ) -> ValidationReport:
        """Screen event semantics, optionally using an LLM when configured."""
        report = ValidationReport()

        for event in events:
            report.total_checked += 1
            repairs = self._apply_safe_repairs(event)
            report.repairs.extend(repairs)
            issues = self._check_event_semantics(event)
            if llm_caller:
                issues.extend(self._llm_validate_event(event, llm_caller))
            errors = [i for i in issues if i.get("level", "error") == "error"]
            warnings = [i for i in issues if i.get("level") != "error"]
            report.warnings.extend(warnings)
            report.review_items.extend(warnings)
            if errors:
                report.failed += 1
                report.errors.extend(errors)
            else:
                report.passed += 1

        for kn in knowledge:
            report.total_checked += 1
            issues = self._check_knowledge_semantics(kn)
            errors = [i for i in issues if i.get("level", "error") == "error"]
            warnings = [i for i in issues if i.get("level") != "error"]
            report.warnings.extend(warnings)
            report.review_items.extend(warnings)
            if errors:
                report.failed += 1
                report.errors.extend(errors)
            else:
                report.passed += 1

        return report

    def _apply_safe_repairs(self, event: Event) -> List[Dict]:
        """Apply only meaning-preserving repairs and retain an audit record."""
        repairs = []
        for attr in ("name", "description", "trigger", "location", "time"):
            value = getattr(event, attr, "")
            if isinstance(value, str):
                cleaned = re.sub(r"\s+", " ", value).strip()
                if cleaned != value:
                    setattr(event, attr, cleaned)
                    repairs.append({
                        "type": "AUTO_TRIM",
                        "entity": event.event_id,
                        "field": attr,
                        "before": value,
                        "after": cleaned,
                    })
        return repairs

    def _llm_validate_event(self, event: Event, llm_caller) -> List[Dict]:
        """Optionally request LLM review; fall back to rule checks if the call fails."""
        prompt = (
            "你是滑坡事件抽取质检器。判断下列事件类型是否与名称和描述一致。"
            "仅返回JSON：{\"valid\":true/false,\"reason\":\"...\"}。\n"
            f"类型：{event.event_type.value}\n名称：{event.name}\n描述：{event.description}"
        )
        try:
            raw = llm_caller(prompt)
            if isinstance(raw, dict):
                result = raw
            else:
                match = re.search(r"\{.*\}", str(raw), re.S)
                result = json.loads(match.group(0)) if match else {}
            if result.get("valid") is False:
                return [{
                    "type": "SEMANTIC_LLM",
                    "level": "warning",
                    "entity": event.event_id,
                    "message": result.get("reason", "LLM建议复核事件类型"),
                }]
        except Exception as exc:
            return [{
                "type": "SEMANTIC_LLM_UNAVAILABLE",
                "level": "warning",
                "entity": event.event_id,
                "message": f"LLM语义复核不可用，已使用规则验证: {exc}",
            }]
        return []

    def _check_event_semantics(self, event: Event) -> List[Dict]:
        """Check event semantics."""
        errors = []

        # Check for a nonempty event name.
        if not event.name or not event.name.strip():
            errors.append({
                'type': 'VR002',
                'level': 'error',
                'entity': event.event_id,
                'message': '事件名称为空',
            })
        else:
            # Check event-name length; the suggested range is 3-50 characters.
            name_len = len(event.name.strip())
            if name_len < 3:
                errors.append({
                    'type': 'VR002',
                    'level': 'warning',
                    'entity': event.event_id,
                    'message': f'事件名称过短（{name_len}字符，建议 >= 3）: "{event.name}"',
                })
            elif name_len > 50:
                errors.append({
                    'type': 'VR002',
                    'level': 'warning',
                    'entity': event.event_id,
                    'message': f'事件名称过长（{name_len}字符，建议 <= 50）: "{event.name[:50]}..."',
                })

        # Check for a nonempty event description.
        if not event.description or not event.description.strip():
            errors.append({
                'type': 'VR002',
                'level': 'warning',
                'entity': event.event_id,
                'message': f'事件"{event.name}"缺少描述',
            })
        else:
            # Check consistency between the description and event type.
            errors.extend(self._check_type_description_consistency(event))

        # Check attribute-value plausibility.
        for attr_name, attr_value in event.attributes.items():
            unit_issues = self._check_numeric_unit(attr_name, attr_value)
            if unit_issues:
                for issue in unit_issues:
                    issue['entity'] = event.event_id
                    issue['field'] = attr_name
                errors.extend(unit_issues)

        return errors

    # Map event types to descriptive vocabulary for type/description consistency checks.
    TYPE_DESCRIPTOR_KEYWORDS = {
        EventType.DISASTER: [
            '破坏', '损毁', '变形', '开裂', '裂缝', '垮塌', '崩塌', '塌陷',
            '滑移', '滑动', '位移', '倾倒', '坠落', '掩埋', '堵塞',
        ],
        EventType.RESULT: [
            '伤亡', '损失', '死亡', '受伤', '失踪', '损毁', '倒塌', '中断',
            '转移', '安置', '受灾', '受损', '影响', '破坏',
        ],
        EventType.RESPONSE: [
            '治理', '防治', '监测', '预警', '撤离', '抢险', '修复', '加固',
            '锚固', '挡墙', '排水', '削坡', '护坡', '压脚', '应急',
        ],
        EventType.CONDITION: [
            '暴雨', '降雨', '地震', '风化', '侵蚀', '冲刷', '地质', '构造',
            '节理', '裂隙', '岩性', '坡度', '坡向', '水位', '地下水',
        ],
        EventType.OBSERVATION: [
            '观测', '勘查', '调查', '测量', '监测', '检测', '试验', '分析',
            '鉴定', '评估', '发现', '记录', '结果显示', '数据表明',
        ],
    }

    def _check_type_description_consistency(self, event: Event) -> List[Dict]:
        """Check consistency between an event type and its description."""
        errors = []
        if not event.description or not event.name:
            return errors

        expected_keywords = self.TYPE_DESCRIPTOR_KEYWORDS.get(event.event_type, [])
        if not expected_keywords:
            return errors

        desc = event.description
        has_keyword = any(kw in desc for kw in expected_keywords)

        if not has_keyword:
            errors.append({
                'type': 'VR003',
                'level': 'warning',
                'entity': event.event_id,
                'message': (
                    f'事件"{event.name}"的类型为"{event.event_type.value}"，'
                    f'但描述中未包含典型词汇'
                ),
            })

        return errors

    def _check_knowledge_semantics(self, kn: EventKnowledge) -> List[Dict]:
        """Check relationship semantics."""
        errors = []

        if not kn.description:
            errors.append({
                'type': 'VR002',
                'level': 'warning',
                'entity': kn.id,
                'message': f'关系缺少描述',
            })

        return errors

    def _check_numeric_unit(self, attr_name: str, attr_value: str) -> List[Dict]:
        """Check whether numeric attributes carry plausible units."""
        for key, valid_units in self.NUMERIC_UNITS.items():
            if key in attr_name:
                # Check for numeric values and units.
                has_number = bool(re.search(r'\d+', attr_value))
                has_unit = any(unit in attr_value for unit in valid_units)

                if has_number and not has_unit:
                    return [{
                        'type': 'VR005',
                        'level': 'warning',
                        'entity': attr_name,
                        'message': f'属性"{attr_name}"="值为{attr_value}"缺少单位，有效单位: {valid_units}',
                    }]
                break

        return []

    # Schema and rule checking

    def schema_validation(
        self,
        events: List[Event],
        knowledge: List[EventKnowledge],
    ) -> ValidationReport:
        """Run deterministic schema and rule checks."""
        report = ValidationReport()

        def record_rule(issues: List[Dict]):
            report.total_checked += 1
            errors = [item for item in issues if item.get("level", "error") == "error"]
            warnings = [item for item in issues if item.get("level") != "error"]
            report.errors.extend(errors)
            report.warnings.extend(warnings)
            report.review_items.extend(warnings)
            if errors:
                report.failed += 1
            else:
                report.passed += 1

        # VR001: unique entity identifiers
        record_rule(self._check_id_uniqueness(events, knowledge))

        # VR003: valid event types
        for event in events:
            report.total_checked += 1
            if not isinstance(event.event_type, EventType):
                report.failed += 1
                report.errors.append({
                    'type': 'VR003',
                    'level': 'error',
                    'entity': event.event_id,
                    'message': f'无效的事件类型: {event.event_type}',
                })
            else:
                report.passed += 1

        # VR004: valid relationship types
        for kn in knowledge:
            report.total_checked += 1
            if not isinstance(kn.relation, EventRelation):
                report.failed += 1
                report.errors.append({
                    'type': 'VR004',
                    'level': 'error',
                    'entity': kn.id,
                    'message': f'无效的关系类型: {kn.relation}',
                })
            else:
                report.passed += 1

        # VR006: cross-event consistency
        record_rule(self._check_cross_event_consistency(events, knowledge))

        # VR007: numeric-attribute plausibility
        record_rule(self._check_numeric_attribute_validity(events))

        # VR008: temporal consistency
        record_rule(self._check_temporal_consistency(events, knowledge))

        # VR009: spatial consistency
        record_rule(self._check_spatial_consistency(events))

        # VR010: relationship integrity
        record_rule(self._check_relation_integrity(knowledge, events))

        return report

    def _check_id_uniqueness(
        self,
        events: List[Event],
        knowledge: List[EventKnowledge],
    ) -> List[Dict]:
        """VR001: check identifier uniqueness."""
        errors = []
        event_ids = [e.event_id for e in events]
        knowledge_ids = [k.id for k in knowledge]

        duplicates = set()
        seen = set()
        for eid in event_ids:
            if eid in seen:
                duplicates.add(eid)
            seen.add(eid)

        for eid in duplicates:
            errors.append({
                'type': 'VR001',
                'level': 'error',
                'entity': eid,
                'message': f'事件 ID 重复: {eid}',
            })

        return errors

    def _check_cross_event_consistency(
        self,
        events: List[Event],
        knowledge: List[EventKnowledge],
    ) -> List[Dict]:
        """VR006: check consistency across events."""
        errors = []
        event_names = {e.name for e in events}
        knowledge_entities = set()

        for kn in knowledge:
            knowledge_entities.add(kn.head_event)
            knowledge_entities.add(kn.tail_event)

        # Check that referenced entities exist.
        for kn in knowledge:
            if kn.head_event not in event_names:
                errors.append({
                    'type': 'VR006',
                    'level': 'warning',
                    'entity': kn.id,
                    'message': f'关系引用了不存在的事件: {kn.head_event}',
                })
            if kn.tail_event not in event_names:
                errors.append({
                    'type': 'VR006',
                    'level': 'warning',
                    'entity': kn.id,
                    'message': f'关系引用了不存在的事件: {kn.tail_event}',
                })

        # Check event-name consistency using similarity.
        sorted_names = sorted(event_names)
        for i in range(len(sorted_names)):
            for j in range(i + 1, len(sorted_names)):
                if self._is_similar_name(sorted_names[i], sorted_names[j]):
                    errors.append({
                        'type': 'VR006',
                        'level': 'warning',
                        'entity': f'{sorted_names[i]}, {sorted_names[j]}',
                        'message': f'可能存在重复事件: "{sorted_names[i]}" 和 "{sorted_names[j]}"',
                    })

        return errors

    def _is_similar_name(self, name1: str, name2: str, threshold: float = 0.8) -> bool:
        """Check whether two names are similar."""
        if len(name1) < 3 or len(name2) < 3:
            return False

        # Simple character-overlap ratio
        chars1 = set(name1)
        chars2 = set(name2)
        if not chars1 or not chars2:
            return False

        overlap = len(chars1 & chars2) / min(len(chars1), len(chars2))
        return overlap > threshold

    # VR007: numeric-attribute plausibility checks

    # Configured plausible ranges for numeric attributes
    NUMERIC_ATTRIBUTE_RANGES = {
        '体积': (0, 1e8, 'm³'),       # Must not be negative.
        '面积': (0, 1e6, 'km²'),
        '坡度': (0, 90, '°'),         # Between 0 and 90 degrees
        '坡向': (0, 360, '°'),
        '内摩擦角': (0, 90, '°'),
        '厚度': (0, 1000, 'm'),
        '深度': (0, 5000, 'm'),
        '高度': (0, 10000, 'm'),
        '速度': (0, 1000, 'm/s'),
        '位移': (0, 1000, 'm'),
        '降雨量': (0, 5000, 'mm'),
        '人口': (0, 1e8, '人'),
        '金额': (0, 1e12, '元'),
    }

    def _check_numeric_attribute_validity(self, events: List[Event]) -> List[Dict]:
        """VR007: check numeric-attribute plausibility."""
        errors = []

        for event in events:
            for attr_name, attr_value in event.attributes.items():
                # Extract the numeric value.
                numbers = re.findall(r'[-+]?\d*\.?\d+', attr_value)
                if not numbers:
                    continue

                for key, (min_val, max_val, unit) in self.NUMERIC_ATTRIBUTE_RANGES.items():
                    if key in attr_name:
                        for num_str in numbers:
                            try:
                                num_val = float(num_str)
                            except ValueError:
                                continue

                            # Check whether the value lies within the plausible range.
                            if num_val < min_val:
                                errors.append({
                                    'type': 'VR007',
                                    'level': 'error',
                                    'entity': event.event_id,
                                    'message': (
                                        f'属性"{attr_name}"的数值 {num_val} 小于最小值 {min_val}'
                                        f'（事件: {event.name}）'
                                    ),
                                })
                            elif num_val > max_val:
                                errors.append({
                                    'type': 'VR007',
                                    'level': 'warning',
                                    'entity': event.event_id,
                                    'message': (
                                        f'属性"{attr_name}"的数值 {num_val} 超过范围上限 {max_val}'
                                        f'（事件: {event.name}）'
                                    ),
                                })

        return errors

    # VR008: temporal consistency checks

    def _check_temporal_consistency(
        self,
        events: List[Event],
        knowledge: List[EventKnowledge],
    ) -> List[Dict]:
        """VR008: check temporal consistency."""
        errors = []

        # Map event names to times.
        event_time_map = {e.name: e.time for e in events if e.time}

        # Check temporal order along causal chains.
        for kn in knowledge:
            if kn.relation == EventRelation.CAUSAL:
                head_time = event_time_map.get(kn.head_event)
                tail_time = event_time_map.get(kn.tail_event)

                if head_time and tail_time:
                    head_parsed = self._parse_time(head_time)
                    tail_parsed = self._parse_time(tail_time)

                    if head_parsed and tail_parsed:
                        # An outcome must not precede its cause.
                        if tail_parsed < head_parsed:
                            errors.append({
                                'type': 'VR008',
                                'level': 'error',
                                'entity': kn.id,
                                'message': (
                                    f'因果关系时间不一致: "{kn.head_event}"({head_time}) '
                                    f'晚于 "{kn.tail_event}"({tail_time})'
                                ),
                            })

            # Check temporal relationships.
            if kn.relation == EventRelation.TEMPORAL:
                head_time = event_time_map.get(kn.head_event)
                tail_time = event_time_map.get(kn.tail_event)

                if head_time and tail_time:
                    head_parsed = self._parse_time(head_time)
                    tail_parsed = self._parse_time(tail_time)

                    if head_parsed and tail_parsed:
                        if head_parsed == tail_parsed:
                            errors.append({
                                'type': 'VR008',
                                'level': 'warning',
                                'entity': kn.id,
                                'message': (
                                    f'时序关系引用了相同时间的事件: '
                                    f'"{kn.head_event}" 和 "{kn.tail_event}" 同为 {head_time}'
                                ),
                            })

        return errors

    def _parse_time(self, time_str: str) -> Optional[Tuple[int, int, int]]:
        """Parse time text into a year, month and day tuple."""
        # Match year-month-day or year-month expressions.
        match = re.search(r'(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})?\s*日?', time_str)
        if match:
            year = int(match.group(1))
            month = int(match.group(2))
            day = int(match.group(3)) if match.group(3) else 1
            return (year, month, day)

        # Format: 2019-07-15 or 2019-07
        match = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', time_str)
        if match:
            year = int(match.group(1))
            month = int(match.group(2))
            day = int(match.group(3))
            return (year, month, day)

        # Format: 2019-07
        match = re.search(r'(\d{4})-(\d{1,2})', time_str)
        if match:
            year = int(match.group(1))
            month = int(match.group(2))
            return (year, month, 1)

        # Year only
        match = re.search(r'(\d{4})', time_str)
        if match and 1900 <= int(match.group(1)) <= 2100:
            return (int(match.group(1)), 1, 1)

        return None

    def validate_temporal_consistency(
        self,
        events: List[Event],
        knowledge: List[EventKnowledge],
    ) -> ValidationReport:
        """Check the plausibility of an event timeline."""
        report = ValidationReport()

        # Call the internal checking method.
        report.errors = self._check_temporal_consistency(events, knowledge)
        report.total_checked = len(events) + len(knowledge)
        report.failed = len(report.errors)
        report.passed = report.total_checked - report.failed

        return report

    # VR009: spatial consistency checks

    def _check_spatial_consistency(self, events: List[Event]) -> List[Dict]:
        """VR009: check spatial consistency, including contradictory location descriptions."""
        errors = []

        for event in events:
            location = event.location
            if not location:
                continue

            # Check for contradictory descriptions.
            contradictory_pairs = [
                ('上游', '下游'),
                ('左岸', '右岸'),
                ('前缘', '后缘'),
                ('坡顶', '坡脚'),
                ('东', '西'),
                ('南', '北'),
            ]

            for term1, term2 in contradictory_pairs:
                if term1 in location and term2 in location:
                    errors.append({
                        'type': 'VR009',
                        'level': 'warning',
                        'entity': event.event_id,
                        'message': (
                            f'位置描述可能自相矛盾: "{location}" '
                            f'同时包含"{term1}"和"{term2}"'
                        ),
                    })

        return errors

    # VR010: relationship integrity checks

    def _check_relation_integrity(
        self,
        knowledge: List[EventKnowledge],
        events: List[Event],
    ) -> List[Dict]:
        """VR010: check relationship integrity, including both endpoints of causal links."""
        errors = []
        event_names = {e.name for e in events}

        for kn in knowledge:
            # A causal relationship requires both head and tail events.
            if kn.relation == EventRelation.CAUSAL:
                if not kn.head_event:
                    errors.append({
                        'type': 'VR010',
                        'level': 'error',
                        'entity': kn.id,
                        'message': '因果关系缺少原因事件（head_event为空）',
                    })
                if not kn.tail_event:
                    errors.append({
                        'type': 'VR010',
                        'level': 'error',
                        'entity': kn.id,
                        'message': '因果关系缺少结果事件（tail_event为空）',
                    })

            # Check whether head and tail refer to the same event.
            if kn.head_event and kn.tail_event and kn.head_event == kn.tail_event:
                errors.append({
                    'type': 'VR010',
                    'level': 'warning',
                    'entity': kn.id,
                    'message': f'关系自引用: "{kn.head_event}" 不能指向自身',
                })

            # Check for a relationship description.
            if not kn.description or not kn.description.strip():
                errors.append({
                    'type': 'VR010',
                    'level': 'warning',
                    'entity': kn.id,
                    'message': f'关系"{kn.relation.value}"缺少描述',
                })

        return errors

    # Quality-control report generation

    def generate_validation_report(
        self,
        semantic_report: ValidationReport = None,
        schema_report: ValidationReport = None,
        output_format: str = "json",
        output_path: str = None,
    ) -> str:
        """Generate a detailed quality-control report in JSON format."""
        def _build_report_section(report: ValidationReport) -> dict:
            if not report:
                return {'total_checked': 0, 'passed': 0, 'failed': 0, 'errors': [], 'warnings': []}

            # Aggregate errors by type.
            error_by_type = defaultdict(int)
            warning_by_type = defaultdict(int)
            error_levels = {'error': 0, 'warning': 0}

            for err in report.errors:
                error_by_type[err.get('type', 'unknown')] += 1
                error_levels[err.get('level', 'warning')] += 1

            for w in report.warnings:
                warning_by_type[w.get('type', 'unknown')] += 1

            total = report.total_checked
            passed = report.passed
            failed = report.failed
            pass_rate = round(passed / total * 100, 2) if total > 0 else 0
            fail_rate = round(failed / total * 100, 2) if total > 0 else 0

            return {
                'total_checked': total,
                'passed': passed,
                'failed': failed,
                'pass_rate': pass_rate,
                'fail_rate': fail_rate,
                'error_count': len(report.errors),
                'warning_count': len(report.warnings),
                'error_by_type': dict(error_by_type),
                'warning_by_type': dict(warning_by_type),
                'error_levels': error_levels,
                'errors': report.errors[:50],  # Limit the list to 50 entries.
                'warnings': report.warnings[:50],
            }

        report = {
            'phase1_semantic': _build_report_section(semantic_report),
            'phase2_schema': _build_report_section(schema_report),
        }

        # Summary statistics
        total_checked = (
            report['phase1_semantic']['total_checked']
            + report['phase2_schema']['total_checked']
        )
        total_passed = (
            report['phase1_semantic']['passed']
            + report['phase2_schema']['passed']
        )
        total_failed = (
            report['phase1_semantic']['failed']
            + report['phase2_schema']['failed']
        )
        total_errors = (
            report['phase1_semantic']['error_count']
            + report['phase2_schema']['error_count']
        )

        report['summary'] = {
            'total_checked': total_checked,
            'total_passed': total_passed,
            'total_failed': total_failed,
            'total_errors': total_errors,
            'overall_pass_rate': round(total_passed / total_checked * 100, 2) if total_checked > 0 else 0,
        }

        # Write the output file.
        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)

        if output_format == "dict":
            return report

        return json.dumps(report, ensure_ascii=False, indent=2)

    # Complete quality-control workflow

    def validate(
        self,
        events: List[Event],
        knowledge: List[EventKnowledge],
        llm_caller=None,
    ) -> Tuple[ValidationReport, ValidationReport]:
        """Run the complete quality-control workflow."""
        print("🔍 Phase 1: 语义验证...")
        semantic_report = self.semantic_validation(events, knowledge, llm_caller)

        print("🔍 Phase 2: Schema 规则检查...")
        schema_report = self.schema_validation(events, knowledge)

        # Print the summary.
        self._print_report(semantic_report, "语义验证")
        self._print_report(schema_report, "Schema 检查")

        return semantic_report, schema_report

    def _print_report(self, report: ValidationReport, title: str):
        """Print the quality-control report."""
        print(f"\n  === {title} ===")
        print(f"    总计: {report.total_checked} | 通过: {report.passed} | 失败: {report.failed}")
        if report.errors:
            print(f"    错误: {len(report.errors)}")
            for err in report.errors[:5]:
                print(f"      [{err['type']}] {err['message'][:80]}")
        if report.warnings:
            print(f"    警告: {len(report.warnings)}")
            for w in report.warnings[:3]:
                print(f"      {w['message'][:80]}")

    # Minimum confidence thresholds by event type
    EVENT_TYPE_CONFIDENCE_THRESHOLDS = {
        EventType.DISASTER: 0.6,      # Disaster event
        EventType.RESULT: 0.5,         # Outcome event
        EventType.RESPONSE: 0.7,       # Response event
        EventType.CONDITION: 0.4,      # Condition event
        EventType.OBSERVATION: 0.8,    # Observation event
    }

    def filter_valid_events(
        self,
        events: List[Event],
        knowledge: List[EventKnowledge],
        min_confidence: float = 0.5,
    ) -> Tuple[List[Event], List[EventKnowledge]]:
        """Filter events and relationships using the quality-control results."""
        valid_events = []
        for e in events:
            # Get the minimum confidence for this event type.
            type_threshold = self.EVENT_TYPE_CONFIDENCE_THRESHOLDS.get(
                e.event_type, min_confidence
            )
            # Use the stricter of the type-specific and global thresholds.
            effective_threshold = max(type_threshold, min_confidence)

            if (
                e.confidence >= effective_threshold
                and e.name.strip()
                and e.description.strip()
            ):
                valid_events.append(e)

        valid_event_names = {e.name for e in valid_events}
        valid_knowledge = [
            k for k in knowledge
            if k.confidence >= min_confidence
            and k.head_event in valid_event_names
            and k.tail_event in valid_event_names
        ]

        return valid_events, valid_knowledge

    def classify_events(
        self,
        events: List[Event],
        knowledge: List[EventKnowledge],
        min_confidence: float = 0.5,
        semantic_report: ValidationReport = None,
        schema_report: ValidationReport = None,
    ) -> Dict[str, List]:
        """Separate accepted, review and rejected events."""
        reports = [report for report in (semantic_report, schema_report) if report]
        event_ids = {event.event_id for event in events}
        event_names = {event.name: event.event_id for event in events}
        relation_ids = {item.id for item in knowledge}

        event_errors: Dict[str, List[Dict]] = {event_id: [] for event_id in event_ids}
        event_warnings: Dict[str, List[Dict]] = {event_id: [] for event_id in event_ids}
        relation_errors: Dict[str, List[Dict]] = {item_id: [] for item_id in relation_ids}
        relation_warnings: Dict[str, List[Dict]] = {item_id: [] for item_id in relation_ids}

        def attach_issue(issue: Dict, target: Dict[str, List[Dict]]) -> None:
            entity = str(issue.get("entity", "")).strip()
            if entity in target:
                target[entity].append(issue)
                return
            # Some cross-event checks locate issues by one event name or a pair of names.
            for name, event_id in event_names.items():
                if name and name in entity and event_id in target:
                    target[event_id].append(issue)

        for report in reports:
            for issue in report.errors:
                entity = str(issue.get("entity", "")).strip()
                if entity in relation_errors:
                    relation_errors[entity].append(issue)
                else:
                    attach_issue(issue, event_errors)
            for issue in report.warnings:
                entity = str(issue.get("entity", "")).strip()
                if entity in relation_warnings:
                    relation_warnings[entity].append(issue)
                else:
                    attach_issue(issue, event_warnings)

        accepted, review, rejected = [], [], []
        event_decisions: Dict[str, Dict] = {}
        for event in events:
            threshold = max(
                self.EVENT_TYPE_CONFIDENCE_THRESHOLDS.get(event.event_type, min_confidence),
                min_confidence,
            )
            reasons = []
            errors = event_errors.get(event.event_id, [])
            warnings = event_warnings.get(event.event_id, [])
            if errors:
                status = "rejected"
                reasons.extend(
                    f"{item.get('type', 'ERROR')}: {item.get('message', '')}"
                    for item in errors
                )
                rejected.append(event)
            elif not event.name.strip() or not event.description.strip():
                status = "rejected"
                reasons.append("VR002: 名称或描述为空")
                rejected.append(event)
            elif warnings:
                status = "review"
                reasons.extend(
                    f"{item.get('type', 'WARNING')}: {item.get('message', '')}"
                    for item in warnings
                )
                review.append(event)
            elif event.confidence >= threshold:
                status = "accepted"
                reasons.append(f"验证无错误或警告，置信度{event.confidence:.3f}达到阈值{threshold:.3f}")
                accepted.append(event)
            elif event.confidence >= max(0.3, threshold - 0.2):
                status = "review"
                reasons.append(f"验证无错误，但置信度{event.confidence:.3f}低于阈值{threshold:.3f}")
                review.append(event)
            else:
                status = "rejected"
                reasons.append(f"置信度{event.confidence:.3f}低于复核下限{max(0.3, threshold - 0.2):.3f}")
                rejected.append(event)
            event_decisions[event.event_id] = {
                "status": status,
                "confidence": float(event.confidence),
                "threshold": float(threshold),
                "reasons": reasons,
            }

        accepted_names = {event.name for event in accepted}
        review_names = {event.name for event in review}
        accepted_knowledge, review_knowledge, rejected_knowledge = [], [], []
        relation_decisions: Dict[str, Dict] = {}
        relation_review_floor = max(0.3, min_confidence - 0.2)
        for item in knowledge:
            reasons = []
            errors = relation_errors.get(item.id, [])
            warnings = relation_warnings.get(item.id, [])
            endpoints_accepted = (
                item.head_event in accepted_names and item.tail_event in accepted_names
            )
            endpoint_under_review = (
                item.head_event in review_names or item.tail_event in review_names
            )
            endpoint_missing = not (
                item.head_event in accepted_names | review_names
                and item.tail_event in accepted_names | review_names
            )

            if errors:
                status = "rejected"
                reasons.extend(
                    f"{row.get('type', 'ERROR')}: {row.get('message', '')}"
                    for row in errors
                )
                rejected_knowledge.append(item)
            elif endpoint_missing:
                status = "rejected"
                reasons.append("关系端点事件未通过验证")
                rejected_knowledge.append(item)
            elif warnings or endpoint_under_review:
                status = "review"
                reasons.extend(
                    f"{row.get('type', 'WARNING')}: {row.get('message', '')}"
                    for row in warnings
                )
                if endpoint_under_review:
                    reasons.append("关系至少有一个端点事件处于待复核状态")
                review_knowledge.append(item)
            elif endpoints_accepted and item.confidence >= min_confidence:
                status = "accepted"
                reasons.append("关系无验证问题、两端事件已通过且置信度达标")
                accepted_knowledge.append(item)
            elif item.confidence >= relation_review_floor:
                status = "review"
                reasons.append(f"关系置信度{item.confidence:.3f}低于阈值{min_confidence:.3f}")
                review_knowledge.append(item)
            else:
                status = "rejected"
                reasons.append(f"关系置信度{item.confidence:.3f}低于复核下限{relation_review_floor:.3f}")
                rejected_knowledge.append(item)
            relation_decisions[item.id] = {
                "status": status,
                "confidence": float(item.confidence),
                "threshold": float(min_confidence),
                "reasons": reasons,
            }

        return {
            "accepted_events": accepted,
            "review_events": review,
            "rejected_events": rejected,
            "accepted_knowledge": accepted_knowledge,
            "review_knowledge": review_knowledge,
            "rejected_knowledge": rejected_knowledge,
            "event_decisions": event_decisions,
            "relation_decisions": relation_decisions,
        }


