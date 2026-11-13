# -*- coding: utf-8 -*-
"""Extract ontology-guided events from geological investigation text."""

import json
import os
import re
import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum

from schema.ontology_loader import OntologyLoader
from schema.schema_config import SchemaConfig


# Event model

class EventType(Enum):
    """Task event categories extending the event-classification scheme."""
    DISASTER = "灾害事件"       # Landslide occurrence, crack propagation or accelerated deformation
    RESULT = "结果事件"          # Damage consequences, casualties or property losses
    RESPONSE = "处置事件"        # Mitigation, monitoring, warning or emergency response
    CONDITION = "条件事件"       # Geological, hydrological or meteorological conditions
    OBSERVATION = "观测事件"     # Investigation findings, test results or measurements


class EventRelation(Enum):
    """Event relationships following the KGE3 and LHOM relationship categories."""
    CAUSAL = "因果"             # A causes B.
    TEMPORAL = "时序"           # A occurs before or after B.
    CONCURRENT = "共时"         # A occurs concurrently with B.
    SPATIAL = "空间"            # A is located in a specified direction from B.
    PART_OF = "组成"            # A is part of B.
    ATTRIBUTE = "属性"          # A has property B.
    CONDITIONAL = "条件"        # B occurs under condition A.


@dataclass
class Event:
    """An event with arguments, attributes, confidence and provenance."""
    event_id: str
    event_type: EventType
    name: str                           # Event name extracted from the current report
    description: str                    # Event description
    # Event arguments, following the KGE3 argument concept
    trigger: str = ""                   # Trigger conditions stated in the current report
    location: str = ""                  # Location
    time: str = ""                      # Time
    # Multiple attributes in a HyperGraphRAG-style representation
    attributes: Dict[str, str] = field(default_factory=dict)
    normalized_attributes: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # Read attribute values and units from the current report; do not preset measurements.
    # Provenance
    source_segment: str = ""            # Source segment identifier
    source_text: str = ""               # Original text
    confidence: float = 1.0             # Confidence


@dataclass
class EventKnowledge:
    """Event knowledge record representing a potentially n-ary relationship."""
    id: str
    head_event: str                     # Head-event identifier
    relation: EventRelation             # Relationship type
    tail_event: str                     # Tail-event identifier
    description: str = ""               # Relationship description
    attributes: Dict[str, str] = field(default_factory=dict)  # Additional attributes
    confidence: float = 1.0


@dataclass
class ExtractionResult:
    """Results from one extraction call."""
    events: List[Event] = field(default_factory=list)
    knowledge: List[EventKnowledge] = field(default_factory=list)
    raw_response: str = ""              # Raw LLM response
    token_usage: int = 0                # Token usage
    cost: float = 0.0                   # Estimated cost


# Event ontology definition

class EventOntology:
    """Landslide event definitions and argument templates following KGE3 and LHOM concepts."""

    # Event-type definitions
    EVENT_TYPES = {
        "灾害事件": "滑坡、崩塌、泥石流等地质灾害的发生、发展和演化过程",
        "结果事件": "地质灾害造成的破坏、人员伤亡、财产损失、环境影响等后果",
        "处置事件": "针对地质灾害的勘查、监测、预警、防治、治理、应急响应等活动",
        "条件事件": "地质条件、水文条件、气象条件、地形地貌等孕灾环境描述",
        "观测事件": "钻探、物探、试验、测量等勘查活动中的发现和数据",
    }

    # Event-relationship definitions
    EVENT_RELATIONS = {
        "因果": "事件甲导致事件乙发生",
        "时序": "事件甲先于事件乙发生",
        "共时": "事件甲与事件乙同时发生",
        "空间": "事件甲与地点乙存在空间关系",
        "组成": "实体甲是实体乙的组成部分",
        "属性": "实体甲具有原文记载的属性",
        "条件": "条件甲成立时发生事件乙",
    }

    # Landslide event-argument templates
    ARGUMENT_TEMPLATE = {
        "灾害事件": ["触发条件", "滑动面", "滑动方向", "滑动速度", "体积", "物质组成", "破坏模式"],
        "结果事件": ["影响对象", "影响范围", "损失程度", "伤亡人数", "经济损失"],
        "处置事件": ["措施类型", "工程规模", "实施时间", "效果评估", "投入资金"],
        "条件事件": ["地质条件", "水文条件", "地形特征", "气象条件", "人类活动"],
        "观测事件": ["观测方法", "观测指标", "观测值", "观测时间", "观测结论"],
    }


class OntologyGuidedEventExtractor:
    """Build ontology-constrained prompts, invoke a model and parse structured events."""

    # Default LLM configuration
    LLM_CONFIGS = {
        "openai": {
            "api_base": "https://api.openai.com/v1",
            "model": "gpt-4o",
            "temperature": 0.1,
            "max_tokens": 4096,
        },
        "deepseek": {
            "api_base": "https://api.deepseek.com",
            "model": "deepseek-chat",
            "temperature": 0.1,
            "max_tokens": 4096,
        },
        "local": {
            "api_base": "http://localhost:8000/v1",
            "model": "qwen3-14b",
            "temperature": 0.1,
            "max_tokens": 4096,
        },
    }

    # Estimated cost in USD per 1,000 tokens
    COST_PER_1K = {
        "gpt-4o": {"input": 0.0025, "output": 0.01},
        "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
        # Do not hard-code potentially outdated DeepSeek prices; continue recording token usage.
        "deepseek-chat": {"input": 0, "output": 0},
        "qwen3-14b": {"input": 0, "output": 0},
    }

    def __init__(
        self,
        llm_provider: str = "deepseek",
        api_key: str = None,
        api_base: str = None,
        model: str = None,
        ontology_loader: OntologyLoader = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_seconds: int = 120,
    ):
        self.llm_provider = llm_provider
        self.config = dict(self.LLM_CONFIGS.get(llm_provider, self.LLM_CONFIGS["deepseek"]))

        if api_key:
            self.api_key = api_key
        else:
            self.api_key = os.environ.get(
                "OPENAI_API_KEY" if llm_provider == "openai" else "DEEPSEEK_API_KEY", ""
            )

        if api_base:
            self.config["api_base"] = api_base
        if model:
            self.config["model"] = model
        if temperature is not None:
            self.config["temperature"] = float(temperature)
        if max_tokens is not None:
            self.config["max_tokens"] = int(max_tokens)
        self.timeout_seconds = int(timeout_seconds)

        self.loader = ontology_loader or OntologyLoader()
        self.schema_config = SchemaConfig(self.loader)
        self.event_ontology = EventOntology()

        self.total_tokens = 0
        self.total_cost = 0.0

    # Main workflow

    def extract_from_segment(
        self,
        segment_text: str,
        section_title: str,
        segment_id: str,
    ) -> ExtractionResult:
        """Extract event knowledge from one text segment."""
        # 1. Build the ontology-guided prompt.
        prompt = self._build_extraction_prompt(segment_text, section_title)

        # 2. Call the LLM.
        raw_response = self._call_llm(prompt)

        # 3. Parse structured output.
        result = self._parse_extraction_result(raw_response, segment_id, segment_text)

        return result

    def extract_from_segments(
        self,
        segments: list,
        batch_size: int = 3,
        progress_callback=None,
    ) -> List[ExtractionResult]:
        """Extract event knowledge from multiple segments."""
        results = []
        total = len(segments)

        for i in range(0, total, batch_size):
            batch = segments[i:i + batch_size]

            for seg in batch:
                result = self.extract_from_segment(
                    seg.content,
                    seg.section_title,
                    seg.segment_id,
                )
                results.append(result)

                if progress_callback:
                    progress_callback(i + batch.index(seg) + 1, total)

            # Pause briefly between batches to reduce API rate-limit pressure.
            if i + batch_size < total:
                time.sleep(0.5)

        return results

    # Prompt construction

    def _build_extraction_prompt(self, text: str, section_title: str) -> str:
        """Build the extraction prompt using ontology constraints and event argument templates."""
        # Build the domain-ontology summary.
        ontology_summary = self._build_ontology_summary()

        # Build the event-type descriptions.
        event_types_desc = self._build_event_types_description()

        # Build ontology constraints.
        ontology_constraints = self._build_ontology_constraints()

        # Build the argument-template descriptions.
        argument_template_desc = self._build_argument_template_description()

        prompt = f"""你是一个地质灾害知识图谱构建专家。请从以下地质勘查报告文本中提取结构化的灾害事件知识。
本提示词中的“事件甲”“地点乙”等均为虚构占位词，不是报告事实；不得将占位词或示意结构复制到抽取结果。事件名称、地点、时间、测量值和单位只能来自下方的当前报告文本。

## 领域本体约束

{ontology_summary}

## 本体约束规则

{ontology_constraints}

## 事件类型定义

{event_types_desc}

## 事件关系定义

- **因果**: 事件甲导致事件乙发生；头尾事件必须来自原文
- **时序**: 事件甲先于事件乙发生；顺序必须有原文依据
- **共时**: 事件甲与事件乙同时发生
- **空间**: 原文中的事件、实体或地点存在方位、距离或拓扑关系
- **组成**: 实体甲是实体乙的一部分
- **属性**: 实体甲具有原文明确记载的属性
- **条件**: 原文条件成立时发生相应事件

## 滑坡事件论元模板

{argument_template_desc}

## 数值提取精确要求

1. **单位完整性**: 提取原文给出的数值及其单位；原文没有单位时不得补造
2. **数量级保持**: 保留原文的科学记数法或数量级表达，不自行换算或引入示例值
3. **范围值处理**: 对于区间值，保留原文的范围表达和单位
4. **精度保持**: 保持原文中的数值精度，不要自行四舍五入
5. **量纲验证**: 检查原文给出的数值与单位是否匹配；无法确认时保留原文表述
6. **缺失值标注**: 如果文本中未提及某项数值，不要编造，直接省略该属性

## 空间关系提取要求

1. **方位关系**: 仅提取原文明确给出的方向信息
2. **距离关系**: 仅提取原文明确给出的距离及单位
3. **拓扑关系**: 识别原文明确给出的包含、相邻或相交关系
4. **高程信息**: 提取原文给出的海拔或高程及单位
5. **坐标信息**: 提取原文给出的经纬度或平面坐标，不补写缺失位数
6. **空间参考**: 记录原文明确给出的参照对象或坐标系

## 时间关系提取要求

1. **绝对时间**: 仅提取原文明确给出的日期或年份
2. **相对时间**: 保留原文对时间先后的描述
3. **时间区间**: 保留原文给出的起止时间或时段表达
4. **时序关系**: 仅在原文明确支持时标注事件顺序
5. **时间精度**: 保留原文给出的时间精度，不要推断具体日期
6. **时间锚点**: 仅使用原文给出的时间锚点

## 置信度标注要求

1. **高置信度 (0.85-1.0)**: 文本明确陈述的事实，数值精确标注
2. **中等置信度 (0.6-0.85)**: 文本间接提及，需要一定推理
3. **低置信度 (0.3-0.6)**: 文本暗示，需较大程度推断
4. **不确定 (0.0-0.3)**: 高度推测，缺乏明确文本支撑
5. 置信度取值精确到小数点后两位

## 当前章节

{section_title}

## 文本内容

{text}

## 输出格式

请以 JSON 格式输出，严格遵循以下结构：

```json
{{
  "events": [
    {{
      "event_name": "事件名称（简洁描述，10字以内）",
      "event_type": "灾害事件|结果事件|处置事件|条件事件|观测事件",
      "description": "事件详细描述，包含关键数值和单位",
      "trigger": "触发条件（如有，否则为空字符串）",
      "location": "位置信息，含方位、距离、坐标（如有，否则为空字符串）",
      "time": "时间信息，含绝对时间、相对时间、时间区间（如有，否则为空字符串）",
      "attributes": {{
        "属性名1（含单位）": "属性值1（含单位）",
        "属性名2（含单位）": "属性值2（含单位）"
      }},
      "confidence": 0.95
    }}
  ],
  "relations": [
    {{
      "head_event": "头事件名称（必须与events中的event_name完全一致）",
      "relation": "因果|时序|共时|空间|组成|属性|条件",
      "tail_event": "尾事件名称（必须与events中的event_name完全一致）",
      "description": "关系描述，说明为什么这两者之间存在该关系",
      "confidence": 0.90
    }}
  ]
}}
```

**重要提醒**:
- 如果文本中没有事件或关系，返回空数组 `{{"events": [], "relations": []}}`
- 所有字符串使用双引号，不要使用单引号
- 不要输出任何 JSON 之外的内容
- 输出字段中的事实只能来自“文本内容”；不要照抄本提示词中的占位词或格式说明"""

        return prompt

    def _build_ontology_summary(self) -> str:
        """Summarize the ontology as constraints for the extraction prompt."""
        lines = []

        # 1. Landslide-domain class hierarchy
        lines.append("### 滑坡领域类层次结构")
        # Locate the landslide ontology class and its descendants.
        landslide_root_candidates = ["滑坡本体", "滑坡"]
        for root_name in landslide_root_candidates:
            if root_name in self.loader.classes:
                lines.append(f"\n**{root_name} → 分类体系**")
                children = self.loader.get_class_children(root_name)
                if children:
                    for child in children[:15]:
                        child_info = self.loader.get_class(child)
                        desc = child_info.get('desc', '') if child_info else ''
                        desc_suffix = f" - {desc[:60]}" if desc else ""
                        lines.append(f"  - {child}{desc_suffix}")
                        # Display one more descendant level.
                        grandchildren = self.loader.get_class_children(child)
                        if grandchildren:
                            gc_str = ', '.join(grandchildren[:5])
                            if len(grandchildren) > 5:
                                gc_str += f" ... (共{len(grandchildren)}个)"
                            lines.append(f"    └─ {gc_str}")
                break

        # Display other root classes.
        lines.append(f"\n**其他领域根类**: {', '.join(self.loader.root_classes[:10])}")
        if len(self.loader.root_classes) > 10:
            lines.append(f"  ... 共 {len(self.loader.root_classes)} 个根类")

        # 2. Core entity types grouped by category
        lines.append("\n### 核心实体类型（按领域分组）")
        for entity_type, class_names in list(self.schema_config.ENTITY_TYPE_TO_ONTOLOGY_CLASSES.items()):
            sample = class_names[:8]
            lines.append(f"- **{entity_type}** ({len(class_names)}个类): {', '.join(sample)}{'...' if len(class_names) > 8 else ''}")

        # 3. Object properties and relationship types
        lines.append("\n### 可用对象属性（关系类型）")
        for idx, (prop_name, prop_info) in enumerate(self.loader.object_properties.items()):
            if idx >= 15:
                lines.append(f"  ... 共 {len(self.loader.object_properties)} 个对象属性")
                break
            domains = ', '.join(prop_info['domains'][:3]) if prop_info['domains'] else '全部'
            ranges = ', '.join(prop_info['ranges'][:3]) if prop_info['ranges'] else '全部'
            comment = prop_info.get('comment', '')
            comment_suffix = f" // {comment[:50]}" if comment else ""
            lines.append(f"- **{prop_name}**: domain=[{domains}], range=[{ranges}]{comment_suffix}")

        # 4. Datatype properties
        lines.append("\n### 可用数据属性（数值/文本属性）")
        if self.loader.data_properties:
            dp_items = list(self.loader.data_properties.items())
            for idx, (dp_name, dp_info) in enumerate(dp_items):
                if idx >= 20:
                    lines.append(f"  ... 共 {len(self.loader.data_properties)} 个数据属性")
                    break
                super_prop = dp_info.get('super_property', '')
                sp_suffix = f" (父属性: {super_prop})" if super_prop else ""
                lines.append(f"- **{dp_name}**{sp_suffix}")
        else:
            lines.append("(未从本体中提取到数据属性，请根据上下文推断数值属性)")

        # 5. Constraint descriptions
        lines.append("\n### 约束条件说明")
        lines.append("- **domain/range 约束**: 对象属性只能连接指定 domain 类型的实体到指定 range 类型的实体")
        lines.append("- **属性适用范围**: 某些属性只能用于特定类型的实体，如力学参数（内摩擦角、内聚力）仅适用于岩土体")
        lines.append("- **层次约束**: 滑坡分类需遵循本体层次结构，如\"滑坡本体→体积类型→巨型/大型/中型/小型\"")
        lines.append("- **数值约束**: 仅提取原文中的数值、单位和数量级；缺失时不得补造")

        return '\n'.join(lines)

    def _build_event_types_description(self) -> str:
        """Describe supported event categories."""
        lines = []
        for etype, desc in self.event_ontology.EVENT_TYPES.items():
            lines.append(f"- **{etype}**: {desc}")
        return '\n'.join(lines)

    def _build_argument_template_description(self) -> str:
        """Describe landslide event-argument templates."""
        lines = []
        lines.append("每种事件类型有其对应的核心论元（Argument），提取时请尽量覆盖：\n")

        template = self.event_ontology.ARGUMENT_TEMPLATE
        type_descriptions = {
            "灾害事件": "滑坡、崩塌、泥石流等地质灾害的发生、发展和演化过程",
            "结果事件": "地质灾害造成的破坏、人员伤亡、财产损失、环境影响等后果",
            "处置事件": "针对地质灾害的勘查、监测、预警、防治、治理、应急响应等活动",
            "条件事件": "地质条件、水文条件、气象条件、地形地貌等孕灾环境描述",
            "观测事件": "钻探、物探、试验、测量等勘查活动中的发现和数据",
        }

        for etype, args in template.items():
            desc = type_descriptions.get(etype, "")
            lines.append(f"**{etype}** - {desc}")
            lines.append(f"  核心论元: {' | '.join(args)}")
            lines.append("")

        return '\n'.join(lines)

    def _build_ontology_constraints(self) -> str:
        """Generate textual constraints from TTL property domains and ranges."""
        lines = []

        lines.append("### 本体约束规则（Domain/Range 约束）")

        # Group object properties by domain.
        domain_groups: Dict[str, List[str]] = {}
        for prop_name, prop_info in self.loader.object_properties.items():
            for domain_class in prop_info['domains']:
                if domain_class not in domain_groups:
                    domain_groups[domain_class] = []
                domain_groups[domain_class].append(prop_name)

        # Generate constraint rules.
        constraint_count = 0
        max_constraints = 20

        # Prioritize constraints related to the landslide ontology.
        priority_domains = ["滑坡本体", "灾害体", "岩土体", "地质构造", "地层岩土"]
        for pd in priority_domains:
            if pd in domain_groups and constraint_count < max_constraints:
                props = domain_groups[pd][:8]
                if len(domain_groups[pd]) > 8:
                    props.append(f"... (共{len(domain_groups[pd])}个属性)")
                lines.append(f"- **{pd}** 可用的属性: {', '.join(props)}")
                constraint_count += 1

        # Display other domain constraints.
        for domain_class, props in domain_groups.items():
            if constraint_count >= max_constraints:
                break
            if domain_class in priority_domains:
                continue
            props_sample = props[:5]
            if len(props) > 5:
                props_sample.append(f"... (共{len(props)}个属性)")
            lines.append(f"- **{domain_class}** 可用的属性: {', '.join(props_sample)}")
            constraint_count += 1

        if constraint_count >= max_constraints:
            lines.append(f"  ... 其余 {len(domain_groups) - max_constraints} 个 domain 类的约束已省略")

        # Group object properties by range for inverse constraints.
        lines.append("\n### 本体约束规则（Range 约束）")
        range_groups: Dict[str, List[str]] = {}
        for prop_name, prop_info in self.loader.object_properties.items():
            for range_class in prop_info['ranges']:
                if range_class not in range_groups:
                    range_groups[range_class] = []
                range_groups[range_class].append(prop_name)

        constraint_count = 0
        for range_class, props in sorted(range_groups.items(), key=lambda x: -len(x[1])):
            if constraint_count >= 12:
                lines.append(f"  ... 共 {len(range_groups)} 个 range 约束")
                break
            props_sample = props[:5]
            if len(props) > 5:
                props_sample.append(f"... (共{len(props)}个属性)")
            lines.append(f"- **{range_class}** 作为值域被以下属性引用: {', '.join(props_sample)}")
            constraint_count += 1

        # Guidance for constrained generation
        lines.append("\n### 约束遵循指导")
        lines.append("在提取知识时，请严格遵循以上 domain/range 约束：")
        lines.append("1. 使用对象属性连接实体时，头实体必须属于该属性的 domain 类")
        lines.append("2. 尾实体必须属于该属性的 range 类")
        lines.append("3. 如果文本中提到的关系在本体中无对应属性，请使用最接近的父类属性")
        lines.append("4. 数值属性应使用本体的数据属性（datatype property）作为属性名")

        return '\n'.join(lines)

    # LLM invocation

    def _call_llm(self, prompt: str) -> str:
        """Call an OpenAI-compatible LLM endpoint."""
        try:
            import requests
        except ImportError:
            raise ImportError("请安装 requests: pip install requests")

        api_base = self.config["api_base"].rstrip('/')
        model = self.config["model"]

        url = f"{api_base}/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "你是一个地质灾害知识图谱构建专家，擅长从地质勘查报告中提取结构化知识。请始终以严格的 JSON 格式输出。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.config["temperature"],
            "max_tokens": self.config["max_tokens"],
        }

        try:
            response = requests.post(
                url, headers=headers, json=payload, timeout=self.timeout_seconds
            )
            response.raise_for_status()
            data = response.json()

            # Record token usage.
            usage = data.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)
            self.total_tokens += input_tokens + output_tokens

            # Estimate cost.
            cost_info = self.COST_PER_1K.get(model, {"input": 0, "output": 0})
            cost = (input_tokens * cost_info["input"] + output_tokens * cost_info["output"]) / 1000
            self.total_cost += cost

            return data["choices"][0]["message"]["content"]

        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"LLM API 调用失败: {e}")

    # Result parsing

    def _parse_extraction_result(
        self,
        raw_response: str,
        segment_id: str,
        source_text: str,
    ) -> ExtractionResult:
        """Parse structured event JSON, attempting local repairs and non-JSON fallback extraction."""
        result = ExtractionResult(raw_response=raw_response)

        # 1. Extract JSON using multiple strategies.
        json_str = self._extract_json_block(raw_response)
        if not json_str:
            # Fallback: extract structured information from non-JSON text.
            return self._fallback_text_extraction(raw_response, segment_id, source_text, result)

        # 2. Parse JSON with repair strategies.
        data = self._robust_json_parse(json_str)

        if data is None:
            # If JSON repair fails, try text-based fallback extraction.
            return self._fallback_text_extraction(raw_response, segment_id, source_text, result)

        # 3. Parse events.
        event_map = {}  # event_name → Event
        for evt_data in data.get("events", []):
            try:
                event = Event(
                    event_id=f"evt_{segment_id}_{len(result.events):03d}",
                    event_type=self._parse_event_type(evt_data.get("event_type", "")),
                    name=evt_data.get("event_name", ""),
                    description=evt_data.get("description", ""),
                    trigger=evt_data.get("trigger", ""),
                    location=evt_data.get("location", ""),
                    time=evt_data.get("time", ""),
                    attributes=evt_data.get("attributes", {}),
                    source_segment=segment_id,
                    source_text=source_text[:500],
                    confidence=float(evt_data.get("confidence", 0.8)),
                )
                result.events.append(event)
                if event.name:
                    event_map[event.name] = event
            except Exception:
                continue

        # 4. Parse relationships.
        for rel_data in data.get("relations", []):
            try:
                knowledge = EventKnowledge(
                    id=f"kn_{segment_id}_{len(result.knowledge):03d}",
                    head_event=rel_data.get("head_event", ""),
                    relation=self._parse_event_relation(rel_data.get("relation", "")),
                    tail_event=rel_data.get("tail_event", ""),
                    description=rel_data.get("description", ""),
                    confidence=float(rel_data.get("confidence", 0.8)),
                )
                result.knowledge.append(knowledge)
            except Exception:
                continue

        return result

    def _robust_json_parse(self, json_str: str) -> Optional[dict]:
        """Try multiple JSON parsing and repair strategies."""
        # Strategy 1: direct parsing
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

        # Strategy 2: repair common JSON errors
        repaired = self._repair_json_errors(json_str)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

        # Strategy 3: complete missing brackets after truncation
        completed = self._complete_truncated_json(json_str)
        for candidate in completed:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

        # Strategy 4: extract independent JSON objects
        try:
            return self._extract_json_objects_loosely(json_str)
        except Exception:
            pass

        return None

    def _repair_json_errors(self, json_str: str) -> str:
        """Repair common JSON formatting errors."""
        s = json_str.strip()

        # Remove the BOM and invisible characters.
        s = s.lstrip('\ufeff')

        # Repair trailing commas before closing braces or brackets.
        s = re.sub(r',\s*}', '}', s)
        s = re.sub(r',\s*]', ']', s)

        # Remove redundant commas at array or object ends.
        s = re.sub(r',\s*$', '', s)

        # Replace Chinese quotation marks with standard JSON quotation marks.
        s = s.replace('\u201c', '"').replace('\u201d', '"')
        s = s.replace('\u2018', "'").replace('\u2019', "'")

        # Repair single-quoted keys and values when applicable.
        # Apply only when the entire JSON representation uses single quotes.
        if '"' not in s or s.count("'") > s.count('"') * 2:
            s = self._fix_single_quoted_json(s)

        # Repair unescaped control characters.
        s = s.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')

        # Leading zeros are invalid JSON numbers, for example 0123.
        # Do not repair leading zeros here because doing so could corrupt scientific notation.

        return s

    def _fix_single_quoted_json(self, s: str) -> str:
        """Try converting single-quoted JSON keys and values to standard double quotes."""
        result = []
        in_double = False
        in_single = False
        escaped = False
        i = 0

        while i < len(s):
            ch = s[i]

            if escaped:
                escaped = False
                result.append(ch)
                i += 1
                continue

            if ch == '\\':
                escaped = True
                result.append(ch)
                i += 1
                continue

            if ch == '"' and not in_single:
                in_double = not in_double
                result.append(ch)
            elif ch == "'" and not in_double:
                in_single = not in_single
                result.append('"')  # Replace single quotes with double quotes.
            else:
                result.append(ch)

            i += 1

        return ''.join(result)

    def _complete_truncated_json(self, json_str: str) -> List[str]:
        """Try completing truncated JSON."""
        candidates = []
        s = json_str.strip()

        # Count brackets.
        open_braces = s.count('{') - s.count('}')
        open_brackets = s.count('[') - s.count(']')

        # An odd quote count suggests truncation inside a string.
        in_string = False
        for ch in s:
            if ch == '"':
                in_string = not in_string

        # Candidate 1: complete the string and closing brackets.
        candidate1 = s
        if in_string:
            candidate1 += '"'
        candidate1 += ']' * max(0, open_brackets)
        candidate1 += '}' * max(0, open_braces)
        candidates.append(candidate1)

        # Candidate 2: when a string is truncated, retain the last complete object.
        if in_string:
            # Find the last complete comma or bracket position.
            try:
                last_comma = s.rindex(',')
                prefix = s[:last_comma]
                suffix = ']' * max(0, prefix.count('[') - prefix.count(']'))
                suffix += '}' * max(0, prefix.count('{') - prefix.count('}'))
                candidates.append(prefix + suffix)
            except ValueError:
                pass

        # Candidate 3: complete only the final incomplete key-value pair.
        try:
            # Find the last complete key-value pair.
            last_complete = max(
                s.rfind('"}'),
                s.rfind('"]'),
                s.rfind('"}'),
            )
            if last_complete > 0:
                prefix = s[:last_complete + 2]
                suffix = ']' * max(0, prefix.count('[') - prefix.count(']'))
                suffix += '}' * max(0, prefix.count('{') - prefix.count('}'))
                candidates.append(prefix + suffix)
        except ValueError:
            pass

        return candidates

    def _extract_json_objects_loosely(self, json_str: str) -> Optional[dict]:
        """Loosely recover JSON objects from matching key-value pairs."""
        result = {"events": [], "relations": []}

        # Try to match the events array.
        event_pattern = r'"event_name"\s*:\s*"([^"]*)"'
        event_names = re.findall(event_pattern, json_str)

        # Try to match complete event objects.
        event_blocks = re.findall(r'\{[^{}]*?"event_name"[^{}]*?\}', json_str, re.DOTALL)
        if not event_blocks:
            # Use a more permissive match.
            event_blocks = re.findall(r'\{[^{}]*?"event_type"[^{}]*?\}', json_str, re.DOTALL)

        for block in event_blocks:
            try:
                evt = {}
                for key in ['event_name', 'event_type', 'description', 'trigger', 'location', 'time']:
                    match = re.search(rf'"{key}"\s*:\s*"([^"]*)"', block)
                    if match:
                        evt[key] = match.group(1)
                # Try to extract confidence.
                conf_match = re.search(r'"confidence"\s*:\s*([\d.]+)', block)
                if conf_match:
                    evt['confidence'] = float(conf_match.group(1))
                else:
                    evt['confidence'] = 0.7
                # Extract attributes.
                attr_match = re.search(r'"attributes"\s*:\s*(\{[^}]*\})', block, re.DOTALL)
                if attr_match:
                    try:
                        evt['attributes'] = json.loads(attr_match.group(1))
                    except json.JSONDecodeError:
                        evt['attributes'] = {}
                else:
                    evt['attributes'] = {}

                if evt.get('event_name'):
                    result["events"].append(evt)
            except Exception:
                continue

        # Try to match relationships.
        rel_blocks = re.findall(r'\{[^{}]*?"head_event"[^{}]*?\}', json_str, re.DOTALL)
        for block in rel_blocks:
            try:
                rel = {}
                for key in ['head_event', 'relation', 'tail_event', 'description']:
                    match = re.search(rf'"{key}"\s*:\s*"([^"]*)"', block)
                    if match:
                        rel[key] = match.group(1)
                conf_match = re.search(r'"confidence"\s*:\s*([\d.]+)', block)
                if conf_match:
                    rel['confidence'] = float(conf_match.group(1))
                else:
                    rel['confidence'] = 0.7

                if rel.get('head_event') and rel.get('tail_event'):
                    result["relations"].append(rel)
            except Exception:
                continue

        if result["events"] or result["relations"]:
            return result
        return None

    def _fallback_text_extraction(
        self,
        raw_response: str,
        segment_id: str,
        source_text: str,
        result: ExtractionResult,
    ) -> ExtractionResult:
        """Recover lower-confidence structured information from non-JSON output."""
        # Try to recover structured information from text.
        text = raw_response.strip()

        # Pattern 1: event-keyword matching
        event_patterns = [
            (r'事件[：:]\s*(.+?)(?:。|$|\n)', EventType.DISASTER),
            (r'灾害[：:]\s*(.+?)(?:。|$|\n)', EventType.DISASTER),
            (r'结果[：:]\s*(.+?)(?:。|$|\n)', EventType.RESULT),
            (r'处置[：:]\s*(.+?)(?:。|$|\n)', EventType.RESPONSE),
            (r'条件[：:]\s*(.+?)(?:。|$|\n)', EventType.CONDITION),
            (r'观测[：:]\s*(.+?)(?:。|$|\n)', EventType.OBSERVATION),
        ]

        for pattern, etype in event_patterns:
            matches = re.findall(pattern, text)
            for m in matches:
                try:
                    event = Event(
                        event_id=f"evt_{segment_id}_{len(result.events):03d}",
                        event_type=etype,
                        name=m[:50],
                        description=m,
                        source_segment=segment_id,
                        source_text=source_text[:500],
                        confidence=0.5,  # Assign lower confidence to fallback extraction.
                    )
                    result.events.append(event)
                except Exception:
                    continue

        # Pattern 2: numeric-attribute extraction
        num_patterns = [
            (r'(体积|方量)[：:=\s]*([\d.]+×?\d*[⁰⁴⁵⁶⁷⁸⁹]*\s*[mM]³?)', '体积'),
            (r'(厚度|深度)[：:=\s]*([\d.]+\s*[mM])', None),
            (r'(坡向)[：:=\s]*([\d.]+°?)', None),
            (r'(坡度)[：:=\s]*([\d.]+[-~]\d+°?)', None),
            (r'(宽度)[：:=\s]*([\d.]+[-~]\d+[cC]?[mM])', None),
            (r'(长度)[：:=\s]*([\d.]+[-~]\d*[mM])', None),
        ]

        if result.events:
            evt = result.events[0]
            for pattern, attr_name in num_patterns:
                match = re.search(pattern, text)
                if match:
                    key = attr_name or match.group(1)
                    val = match.group(2)
                    evt.attributes[key] = val

        return result

    def _extract_json_block(self, text: str) -> Optional[str]:
        """Extract a JSON block from fenced output or an outer object."""
        if not text:
            return None

        s = text.strip()

        # Strategy 1: match a fenced JSON block.
        match = re.search(r'```json\s*([\s\S]*?)\s*```', s)
        if match:
            return match.group(1).strip()

        # Strategy 2: match a generic fenced code block.
        match = re.search(r'```\s*([\s\S]*?)\s*```', s)
        if match:
            content = match.group(1).strip()
            if content.startswith('{'):
                return content

        # Strategy 3: greedily match the outermost JSON object to preserve completeness.
        # Use the first opening brace through the last closing brace.
        start = s.find('{')
        end = s.rfind('}')
        if start != -1 and end != -1 and end > start:
            return s[start:end + 1]

        return None

    def _parse_event_type(self, type_str: str) -> EventType:
        """Parse an event-type string."""
        for etype in EventType:
            if etype.value in type_str:
                return etype
        return EventType.DISASTER  # Default

    def _parse_event_relation(self, rel_str: str) -> EventRelation:
        """Parse an event-relationship string."""
        for rel in EventRelation:
            if rel.value in rel_str:
                return rel
        return EventRelation.ATTRIBUTE  # Default

    # Statistics

    def get_stats(self) -> dict:
        """Return extraction statistics."""
        return {
            "total_tokens": self.total_tokens,
            "total_cost_usd": round(self.total_cost, 4),
            "total_cost_cny": round(self.total_cost * 7.2, 2),
            "llm_provider": self.llm_provider,
            "model": self.config["model"],
        }


