# -*- coding: utf-8 -*-
"""Extract event knowledge using deterministic rules."""

import re
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field

# Import event models from event_extractor.
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from extraction.event_extractor import (
    Event, EventKnowledge, EventType, EventRelation, ExtractionResult
)


@dataclass
class RuleMatch:
    """A rule match with its extracted value and context."""
    pattern_name: str
    value: str
    unit: str = ""
    context: str = ""
    confidence: float = 0.8


class RuleBasedExtractor:
    """Rule-based knowledge extractor for report text and tables."""

    # Maximum event-name length
    MAX_EVENT_NAME_LENGTH = 30

    # Numeric-parameter extraction patterns

    NUMERIC_PATTERNS = {
        # Volume
        '体积': [
            (r'体积[约约为为]?\s*(\d+\.?\d*)\s*[×xX]\s*(\d+)\s*[⁴⁰¹²³⁵⁶⁷⁸⁹]?\s*m[³3]', 'm³', 0.9),
            (r'体积[约约为为]?\s*(\d+\.?\d*)\s*万?\s*m[³3]', 'm³', 0.85),
            (r'方量[约约为为]?\s*(\d+\.?\d*)\s*[×xX]\s*(\d+)\s*[⁴⁰¹²³⁵⁶⁷⁸⁹]?\s*m[³3]', 'm³', 0.9),
            (r'方量[约约为为]?\s*(\d+\.?\d*)\s*万?\s*m[³3]', 'm³', 0.85),
            (r'总体积[约约为为]?\s*(\d+\.?\d*)\s*[×xX]\s*(\d+)\s*[⁴⁰¹²³⁵⁶⁷⁸⁹]?\s*m[³3]', 'm³', 0.9),
        ],
        # Area
        '面积': [
            (r'面积[约约为为]?\s*(\d+\.?\d*)\s*[×xX]\s*(\d+)\s*[⁴⁰¹²³⁵⁶⁷⁸⁹]?\s*m[²2]', 'm²', 0.9),
            (r'面积[约约为为]?\s*(\d+\.?\d*)\s*万?\s*m[²2]', 'm²', 0.85),
            (r'分布面积[约约为为]?\s*(\d+\.?\d*)\s*[×xX]\s*(\d+)\s*[⁴⁰¹²³⁵⁶⁷⁸⁹]?\s*m[²2]', 'm²', 0.9),
            (r'分布面积[约约为为]?\s*(\d+\.?\d*)\s*万?\s*m[²2]', 'm²', 0.9),
        ],
        # Length, width, thickness and depth
        '长度': [
            (r'(?:长约|长度[约约为为]?|长\s*)\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*(m|km|cm|mm|米|千米|厘米|毫米)', 'm', 0.85),
            (r'(?:长\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*)m', 'm', 0.85),
        ],
        '宽度': [
            (r'(?:宽约|宽度[约约为为]?|宽\s*)\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*(m|km|cm|mm|米|千米|厘米|毫米)', 'm', 0.85),
            (r'(?:宽\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*)m', 'm', 0.85),
        ],
        '厚度': [
            (r'(?:厚约|厚度[约约为为]?|厚\s*)\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*(m|km|cm|mm|米|千米|厘米|毫米)', 'm', 0.85),
            (r'(?:厚\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*)m', 'm', 0.85),
            (r'滑体[厚厚度]+[约约为为]?\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*m', 'm', 0.9),
        ],
        '深度': [
            (r'(?:深约|深度[约约为为]?|深\s*)\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*(m|km|cm|mm|米|千米|厘米|毫米)', 'm', 0.85),
        ],
        '高度': [
            (r'(?:高约|高度[约约为为]?|高\s*)\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*(m|km|cm|mm|米|千米|厘米|毫米)', 'm', 0.85),
        ],
        '高程': [
            (r'高程[约约为为]?\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*m', 'm', 0.85),
            (r'海拔[约约为为]?\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*m', 'm', 0.85),
        ],
        # Angle
        '坡度': [
            (r'坡度[约约为为]?\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*[°度]', '°', 0.85),
            (r'([\d.]+)[°度][\s，,]*坡度', '°', 0.8),
        ],
        '坡向': [
            (r'坡向[约约为为]?\s*(\d+\.?\d*)\s*[°度]', '°', 0.85),
            (r'坡向[约约为为]?\s*([东南西北]+)', '', 0.8),
        ],
        '倾角': [
            (r'倾角[约约为为]?\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*[°度]', '°', 0.85),
        ],
        # Mechanical parameters
        '内摩擦角': [
            (r'内摩擦角[φφ]?\s*[约约为为]?\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*[°度]', '°', 0.9),
        ],
        '内聚力': [
            (r'内聚力[约约为为]?\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*(kPa|MPa|Pa|千帕)', 'kPa', 0.9),
            (r'[Cc]?\s*[=＝]\s*(\d+\.?\d*)\s*(kPa|MPa)', 'kPa', 0.85),
        ],
        '抗剪强度': [
            (r'抗剪强度[约约为为]?\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*(kPa|MPa|Pa)', 'kPa', 0.9),
        ],
        '弹性模量': [
            (r'弹性模量[约约为为]?\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*(MPa|GPa|Pa)', 'MPa', 0.9),
        ],
        '渗透系数': [
            (r'渗透系数[约约为为]?\s*(\d+\.?\d*)\s*[×xX]\s*(\d+)\s*[⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]*\s*(cm/s|m/s|m/d|cm/d)', 'cm/s', 0.9),
        ],
        # Cracks
        '裂缝宽度': [
            (r'裂缝[宽宽度]*\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*(cm|mm|m)', 'cm', 0.85),
            (r'拉张裂缝[宽宽度]*\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*(cm|mm)', 'cm', 0.9),
        ],
        '裂缝长度': [
            (r'裂缝[长长度]*\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*(m|cm)', 'm', 0.85),
        ],
        # Displacement
        '位移': [
            (r'位移[量约约为为]?\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*(mm|cm|m)', 'mm', 0.85),
            (r'变形[量约约为为]?\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*(mm|cm|m)', 'mm', 0.8),
        ],
        # Rainfall
        '降雨量': [
            (r'(?:降雨量|降水量|日降雨|年降雨)[约约为为]?\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*mm', 'mm', 0.85),
        ],
        # Population
        '人口': [
            (r'(\d+)\s*户\s*(\d+)\s*人', '人', 0.85),
            (r'人口[约约为为]?\s*(\d+)\s*人', '人', 0.8),
        ],
        # Groundwater level
        '地下水位': [
            (r'地下[水]*位[埋深]*\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*m', 'm', 0.85),
        ],
        # Safety or stability factor
        '安全系数': [
            (r'安全系数[约约为为]?\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?', '', 0.9),
            (r'稳定[性]*系数[约约为为]?\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?', '', 0.9),
            (r'[FfKk]\s*[=＝]\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?', '', 0.85),
        ],
        # Sliding velocity or deformation rate
        '滑动速度': [
            (r'滑动速度[约约为为]?\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*(mm/d|cm/d|m/d|mm/月|cm/月|m/月)', 'mm/d', 0.9),
            (r'蠕滑[速度速率]*[约约为为]?\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*(mm/d|cm/d|m/d)', 'mm/d', 0.9),
        ],
        '变形速率': [
            (r'变形[速度速率]*[约约为为]?\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*(mm/d|cm/d|m/d|mm/月)', 'mm/d', 0.9),
            (r'位移[速度速率]*[约约为为]?\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*(mm/d|cm/d)', 'mm/d', 0.9),
        ],
        # Seismic parameters
        '地震烈度': [
            (r'地震烈度[约约为为]?\s*([IVXLCDMⅣⅤⅥⅦⅧⅨⅩⅪⅫ]+)', '', 0.9),
            (r'地震[基本]*烈度[约约为为]?\s*(\d+\.?\d*)\s*度', '度', 0.9),
            (r'设防烈度[约约为为]?\s*(\d+\.?\d*)\s*度', '度', 0.9),
        ],
        '地震加速度': [
            (r'地震[动]*加速度[约约为为]?\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*(g|gal|Gal|cm/s[²2])', 'g', 0.9),
            (r'峰值加速度[约约为为]?\s*(\d+\.?\d*)\s*[～~-]*\s*(\d+\.?\d*)?\s*(g|gal)', 'g', 0.9),
        ],
        # Stratigraphic age
        '地层年代': [
            (r'(?:侏罗系|三叠系|二叠系|白垩系|寒武系|奥陶系|志留系|泥盆系|石炭系|第四系|第三系|震旦系|前震旦系)\s*(?:下统|中统|上统|下段|中段|上段)?', '', 0.9),
            (r'([\u4e00-\u9fa5]+(?:系|统|组|段))\s*(?:下统|中统|上统|下段|中段|上段)?', '', 0.85),
        ],
        # Scientific notation, for example 1.7 x 10^3
        '科学记数': [
            (r'([\d.]+)\s*[×xX]\s*(\d+)\s*[⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]*', '', 0.9),
        ],
    }

    # Section-keyword mappings for event-type classification

    SECTION_TYPE_KEYWORDS = {
        # Disaster events: deformation, failure and landslide occurrence
        EventType.DISASTER: [
            '变形破坏', '滑坡特征', '灾害特征', '裂缝', '变形', '破坏', '滑动',
            '崩塌', '塌陷', '鼓胀', '隆起', '沉降', '滑移', '错动', '垮塌',
            '滑坡发生', '灾害发生', '变形加速', '裂缝扩展', '滑动面', '破坏模式',
            '拉张', '剪切', '压扭', '蠕滑', '倾倒',
        ],
        # Outcome events: losses and affected areas
        EventType.RESULT: [
            '损失', '危害', '影响', '后果', '破坏', '伤亡', '受损',
            '经济损失', '影响范围', '危害程度', '危险性', '风险',
            '损毁', '开裂', '威胁', '房屋受损', '公路受损', '农田受损',
        ],
        # Response events: prevention, mitigation and remedial works
        EventType.RESPONSE: [
            '防治', '治理', '措施', '工程', '监测', '预警', '应急',
            '抗滑桩', '挡土墙', '排水', '锚固', '削坡', '减载',
            '加固', '搬迁', '避让', '群测群防', '专业监测', '施工',
            '布设', '设置', '修建', '实施', '方案', '设计',
        ],
        # Condition events: geological, hydrological and meteorological conditions
        EventType.CONDITION: [
            '地质条件', '地层', '岩性', '构造', '水文', '气象',
            '地形地貌', '地貌', '地形', '地下水', '降雨', '地震',
            '岩土体', '地质', '环境', '条件', '背景', '概况',
            '地理位置', '交通', '气候', '水系', '植被', '人类活动',
        ],
        # Observation events: numeric parameters and measurements
        EventType.OBSERVATION: [
            '参数', '指标', '试验', '测试', '测量', '观测', '监测',
            '钻探', '物探', '勘查', '调查', '取样', '分析',
            '报告', '结论', '数据', '结果', '统计', '记录',
            '数值', '计算', '评价', '评估', '判断',
        ],
    }

    # Multi-hop causal-chain patterns

    CAUSAL_CHAIN_PATTERNS = [
        # Two-hop chain: X causes Y, which then triggers Z.
        (r'([\u4e00-\u9fa5]{3,20}?)\s*(?:导致|引发|诱发|造成|引起)\s*([\u4e00-\u9fa5]{3,20}?)\s*[,，]\s*\2\s*(?:进一步|又|进而|继而)\s*(?:导致|引发|诱发|造成|引起)\s*([\u4e00-\u9fa5]{3,20}?)', 0.75),
        # Three-hop chain: X->Y->Z->W.
        (r'([\u4e00-\u9fa5]{3,20}?)\s*(?:导致|引发|诱发|造成|引起)\s*([\u4e00-\u9fa5]{3,20}?)\s*[,，]\s*\2\s*(?:导致|引发|诱发|造成|引起)\s*([\u4e00-\u9fa5]{3,20}?)\s*[,，]\s*\3\s*(?:最终|最后|进而)\s*(?:导致|引发|诱发|造成|引起)\s*([\u4e00-\u9fa5]{3,20}?)', 0.7),
        # Chained causality: X induces Y and leads to Z.
        (r'(?:由于|受|因为|因)\s*([\u4e00-\u9fa5]{3,20}?)\s*,?\s*(?:引起|造成|导致)\s*([\u4e00-\u9fa5]{3,20}?)\s*,?\s*(?:并|进而|进一步|最终)\s*(?:导致|引发|诱发|造成|引起)\s*([\u4e00-\u9fa5]{3,20}?)', 0.75),
    ]

    # Location patterns

    LOCATION_PATTERNS = [
        (r'位于\s*([\u4e00-\u9fa5]{2,10}(?:市|县|区|镇|乡|村|组))', 0.85),
        (r'地处\s*([\u4e00-\u9fa5]{2,10}(?:市|县|区|镇|乡|村|组))', 0.85),
        (r'([\u4e00-\u9fa5]{2,6}(?:市|县|区))\s*([\u4e00-\u9fa5]{2,6}(?:镇|乡))\s*([\u4e00-\u9fa5]{2,6}(?:村|组))', 0.9),
        (r'地理位置[：:]\s*([\u4e00-\u9fa5\d，,、\s]+)', 0.8),
    ]

    # Longitude and latitude patterns

    COORDINATE_PATTERNS = [
        # Chinese east-longitude/north-latitude expressions in degrees, minutes and seconds
        (r'东经\s*(\d{1,3})\s*[°°]\s*(\d{1,2})\s*[\'′]\s*(\d{1,2})\s*[\"″]', 'lng', 0.95),
        (r'北纬\s*(\d{1,3})\s*[°°]\s*(\d{1,2})\s*[\'′]\s*(\d{1,2})\s*[\"″]', 'lat', 0.95),
        # Chinese longitude/latitude expressions in degrees and minutes
        (r'东经\s*(\d{1,3})\s*[°°]\s*(\d{1,2})\s*[\'′]', 'lng', 0.9),
        (r'北纬\s*(\d{1,3})\s*[°°]\s*(\d{1,2})\s*[\'′]', 'lat', 0.9),
        # Chinese longitude/latitude expressions in decimal degrees
        (r'东经\s*(\d{1,3}\.?\d*)\s*[°°]', 'lng', 0.9),
        (r'北纬\s*(\d{1,3}\.?\d*)\s*[°°]', 'lat', 0.9),
        # English N/E expressions in degrees, minutes and seconds
        (r'[Nn]\s*(\d{1,3})\s*[°°]\s*(\d{1,2})\s*[\'′]\s*(\d{1,2})\s*[\"″]', 'lat', 0.95),
        (r'[Ee]\s*(\d{1,3})\s*[°°]\s*(\d{1,2})\s*[\'′]\s*(\d{1,2})\s*[\"″]', 'lng', 0.95),
        # Combined N/E decimal-degree expressions
        (r'[Nn]\s*(\d{1,3}\.?\d*)\s*[°°]\s*[,，\s]+[Ee]\s*(\d{1,3}\.?\d*)\s*[°°]', 'latlng', 0.95),
    ]

    # Relative-position patterns

    RELATIVE_POSITION_PATTERNS = [
        # Direction or place name followed by distance
        (r'(?:距|距离|离)\s*([\u4e00-\u9fa5]{2,10}?(?:村|镇|县|市|区|路|道|河|江|公路|铁路|国道)?)\s*[约约为为]?\s*(\d+\.?\d*)\s*(m|km|米|千米)', 0.85),
        # Direction descriptions
        (r'([\u4e00-\u9fa5]{2,10}?(?:体|缘|部|侧|端|坡|面|区|段))\s*([东南西北]{1,2})(?:侧|部|端|缘|面|方)', 0.85),
        # Adjacent-to or near relationships
        (r'(?:紧邻|靠近|临近|毗邻|相接)\s*([\u4e00-\u9fa5]{2,10}?(?:村|镇|路|道|河|江|公路|铁路|国道))', 0.8),
        # Between two locations
        (r'位于\s*([\u4e00-\u9fa5]{2,10}?(?:村|镇|县|市|区|路))\s*(?:与|和|及)\s*([\u4e00-\u9fa5]{2,10}?(?:村|镇|县|市|区|路))\s*之间', 0.85),
        # Distance from a location
        (r'距\s*([\u4e00-\u9fa5]{2,6}?(?:县城|市区|城区|镇区|集镇))\s*[约约为为]?\s*(\d+\.?\d*)\s*(km|公里|m|米)', 0.85),
    ]

    # Time-expression patterns

    TIME_PATTERNS = [
        (r'(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日', 0.95),
        (r'(\d{4})\s*年\s*(\d{1,2})\s*月', 0.9),
        (r'(\d{4})\s*年', 0.85),
        (r'(\d{4})[年.](\d{1,2})[月.](\d{1,2})[日]?', 0.9),
        (r'发生于\s*(\d{4}\s*年\s*\d{1,2}\s*月)', 0.9),
        (r'发生[于在]\s*(\d{4}\s*年)', 0.85),
        # Compact numeric dates
        (r'(\d{4})(\d{2})(\d{2})(?:\s|$|[,，。；;])', 0.7),
    ]

    # Geological-condition patterns

    GEOLOGY_PATTERNS = [
        # Lithology
        (r'岩性[为以主要是]+([\u4e00-\u9fa5、，,\s]+?)(?:[。，；;]|$)', 0.85),
        (r'(?:出露|分布)[地层岩性为以主要是]+([\u4e00-\u9fa5、，,\s]+?)(?:[。，；;]|$)', 0.85),
        # Stratigraphy
        (r'([\u4e00-\u9fa5]+(?:组|段|系|统|群))\s*(?:地层|砂岩|页岩|灰岩|泥岩|白云岩)', 0.8),
        (r'(?:侏罗系|三叠系|二叠系|白垩系|寒武系|奥陶系|志留系|泥盆系|石炭系|第四系)', 0.9),
        # Geological structures
        (r'(?:断层|褶皱|节理|裂隙|劈理|片理)', 0.85),
        (r'地质构造[：:]\s*([\u4e00-\u9fa5，,、\s\d]+?)(?:[。；;]|$)', 0.8),
    ]

    # Causal-relationship patterns

    CAUSAL_PATTERNS = [
        (r'(?:受|由于|因为|因)\s*([\u4e00-\u9fa5]{3,20}?)\s*(?:影响|作用|导致|引发|诱发|造成)', 0.8),
        (r'([\u4e00-\u9fa5]{3,15}?)\s*(?:导致|引发|诱发|造成|引起)\s*([\u4e00-\u9fa5]{3,20}?)', 0.75),
        (r'(?:在|当)\s*([\u4e00-\u9fa5]{3,20}?)\s*(?:条件下|情况下|作用下)', 0.75),
    ]

    # Deformation and failure patterns

    DEFORMATION_PATTERNS = [
        (r'(?:出现|产生|形成|发育)\s*([\u4e00-\u9fa5]{2,10}?(?:裂缝|裂隙|塌陷|鼓胀|隆起|沉降|滑移|错动|垮塌))', 0.85),
        (r'(?:变形|破坏)[特征表现为为以主要是]+([\u4e00-\u9fa5、，,\s]{3,40}?)(?:[。；;]|$)', 0.8),
        (r'(?:拉张|剪切|压扭|鼓胀|蠕滑|滑移|倾倒|崩塌|错落)', 0.85),
    ]

    # Mitigation-measure patterns

    PREVENTION_PATTERNS = [
        (r'(?:采用|实施|设置|布设|修建)\s*([\u4e00-\u9fa5]{2,15}?(?:桩|墙|沟|网|锚|坝|堤|排水|监测))', 0.85),
        (r'(?:治理|防治|整治)[措施方案为以主要是]+([\u4e00-\u9fa5、，,\s]{3,40}?)(?:[。；;]|$)', 0.8),
    ]

    def __init__(self):
        self.stats = {
            'numeric_params': 0,
            'locations': 0,
            'times': 0,
            'geology': 0,
            'causal': 0,
            'causal_chains': 0,
            'deformation': 0,
            'prevention': 0,
            'coordinates': 0,
            'relative_positions': 0,
            'table_params': 0,
        }

    def _classify_event_type(
        self,
        section_title: str,
        text: str,
        extracted_items: dict,
    ) -> EventType:
        """Classify events from section keywords and extracted content."""
        # Match keywords against the title and first 200 text characters.
        context = (section_title + " " + text[:200]).lower()

        # Compute the match score for each event type.
        scores = {}
        for etype, keywords in self.SECTION_TYPE_KEYWORDS.items():
            score = 0
            for kw in keywords:
                if kw.lower() in context:
                    score += 1
            scores[etype] = score

        # Return the highest-scoring type when there is an explicit match.
        best_type = max(scores, key=scores.get)
        if scores[best_type] > 0:
            return best_type

        # Otherwise infer the type from the extracted content.
        if extracted_items.get('deformation'):
            return EventType.DISASTER
        if extracted_items.get('prevention'):
            return EventType.RESPONSE
        if extracted_items.get('numeric_params'):
            return EventType.OBSERVATION
        if extracted_items.get('geology'):
            return EventType.CONDITION
        if extracted_items.get('causal'):
            return EventType.DISASTER

        # Default to a condition event.
        return EventType.CONDITION

    def _truncate_name(self, name: str) -> str:
        """Truncate overlong names."""
        if len(name) <= self.MAX_EVENT_NAME_LENGTH:
            return name
        return name[:self.MAX_EVENT_NAME_LENGTH - 3] + "..."

    # Main extraction method

    def extract_from_text(
        self,
        text: str,
        section_title: str = "",
        segment_id: str = "rule_0000",
    ) -> ExtractionResult:
        """Extract typed events and relationships from report text."""
        result = ExtractionResult()

        # Extract all candidate items before classifying them.
        numeric_params = self._extract_numeric_params(text)
        locations = self._extract_locations(text)
        times = self._extract_times(text)
        geology_items = self._extract_geology(text)
        deformation_items = self._extract_deformation(text)
        prevention_items = self._extract_prevention(text)
        coordinates = self._extract_coordinates(text)
        relative_positions = self._extract_relative_positions(text)

        # Build a dictionary of extracted items for classification.
        extracted_items = {
            'numeric_params': numeric_params,
            'locations': locations,
            'times': times,
            'geology': geology_items,
            'deformation': deformation_items,
            'prevention': prevention_items,
            'causal': bool(self._extract_causal(text)),
        }

        # Classify the event type.
        default_type = self._classify_event_type(section_title, text, extracted_items)

        # 1. Extract numeric parameters as observation events.
        if numeric_params:
            event = Event(
                event_id=f"evt_{segment_id}_params",
                event_type=EventType.OBSERVATION,
                name=self._truncate_name(f"{section_title}_参数观测"),
                description=f"从章节「{section_title}」中提取的数值参数",
                attributes=dict(numeric_params),
                source_segment=segment_id,
                source_text=text[:500],
                confidence=0.85,
            )
            result.events.append(event)
            self.stats['numeric_params'] += len(numeric_params)

        # 2. Extract locations, including administrative divisions, as condition events.
        if locations:
            event = Event(
                event_id=f"evt_{segment_id}_loc",
                event_type=EventType.CONDITION,
                name=self._truncate_name(f"{section_title}_位置信息"),
                description=f"位置：{'；'.join(locations)}",
                location=locations[0] if locations else "",
                source_segment=segment_id,
                source_text=text[:500],
                confidence=0.85,
            )
            result.events.append(event)
            self.stats['locations'] += len(locations)

        # 2.1. Extract longitude and latitude as observation events.
        if coordinates:
            event = Event(
                event_id=f"evt_{segment_id}_coord",
                event_type=EventType.OBSERVATION,
                name=self._truncate_name(f"{section_title}_经纬度坐标"),
                description=f"坐标：{'；'.join(coordinates)}",
                attributes={'坐标': coordinates[0]} if len(coordinates) == 1 else {'坐标': '；'.join(coordinates)},
                source_segment=segment_id,
                source_text=text[:500],
                confidence=0.95,
            )
            result.events.append(event)
            self.stats['coordinates'] += len(coordinates)

        # 2.2. Extract relative positions.
        if relative_positions:
            pos_attrs = {}
            for i, pos in enumerate(relative_positions):
                pos_attrs[f'相对位置_{i+1}'] = pos
            event = Event(
                event_id=f"evt_{segment_id}_relpos",
                event_type=EventType.CONDITION,
                name=self._truncate_name(f"{section_title}_相对位置"),
                description=f"相对位置：{'；'.join(relative_positions)}",
                attributes=pos_attrs,
                source_segment=segment_id,
                source_text=text[:500],
                confidence=0.85,
            )
            result.events.append(event)
            self.stats['relative_positions'] += len(relative_positions)

        # 3. Extract temporal information as observation events.
        if times:
            event = Event(
                event_id=f"evt_{segment_id}_time",
                event_type=EventType.OBSERVATION,
                name=self._truncate_name(f"{section_title}_时间信息"),
                description=f"时间：{'；'.join(times)}",
                time=times[0] if times else "",
                source_segment=segment_id,
                source_text=text[:500],
                confidence=0.9,
            )
            result.events.append(event)
            self.stats['times'] += len(times)

        # 4. Extract geological conditions as condition events.
        if geology_items:
            event = Event(
                event_id=f"evt_{segment_id}_geo",
                event_type=EventType.CONDITION,
                name=self._truncate_name(f"{section_title}_地质条件"),
                description=f"地质条件：{'；'.join(geology_items)}",
                source_segment=segment_id,
                source_text=text[:500],
                confidence=0.8,
            )
            result.events.append(event)
            self.stats['geology'] += len(geology_items)

        # 5. Extract causal information as relationships.
        causal_relations = self._extract_causal(text)
        for i, (cause, effect) in enumerate(causal_relations):
            # Create the cause event.
            cause_event = Event(
                event_id=f"evt_{segment_id}_cause_{i}",
                event_type=EventType.CONDITION,
                name=cause,
                description=cause,
                source_segment=segment_id,
                source_text=text[:500],
                confidence=0.75,
            )
            result.events.append(cause_event)

            # Create the outcome event.
            effect_event = Event(
                event_id=f"evt_{segment_id}_effect_{i}",
                event_type=EventType.DISASTER,
                name=effect,
                description=effect,
                source_segment=segment_id,
                source_text=text[:500],
                confidence=0.75,
            )
            result.events.append(effect_event)

            # Create the causal relationship.
            knowledge = EventKnowledge(
                id=f"kn_{segment_id}_causal_{i}",
                head_event=cause,
                relation=EventRelation.CAUSAL,
                tail_event=effect,
                description=f"{cause}导致{effect}",
                confidence=0.75,
            )
            result.knowledge.append(knowledge)
            self.stats['causal'] += 1

        # 5.1. Extract multi-hop causal chains A->B->C.
        causal_chains = self._extract_causal_chain(text, segment_id)
        for chain in causal_chains:
            for j, link in enumerate(chain['links']):
                cause_event = Event(
                    event_id=f"evt_{segment_id}_chain_{chain['chain_id']}_cause_{j}",
                    event_type=EventType.CONDITION if j == 0 else EventType.DISASTER,
                    name=link['cause'],
                    description=link['cause'],
                    source_segment=segment_id,
                    source_text=text[:500],
                    confidence=link.get('confidence', 0.75),
                )
                result.events.append(cause_event)

                effect_event = Event(
                    event_id=f"evt_{segment_id}_chain_{chain['chain_id']}_effect_{j}",
                    event_type=EventType.DISASTER,
                    name=link['effect'],
                    description=link['effect'],
                    source_segment=segment_id,
                    source_text=text[:500],
                    confidence=link.get('confidence', 0.75),
                )
                result.events.append(effect_event)

                knowledge = EventKnowledge(
                    id=f"kn_{segment_id}_chain_{chain['chain_id']}_link_{j}",
                    head_event=link['cause'],
                    relation=EventRelation.CAUSAL,
                    tail_event=link['effect'],
                    description=link['description'],
                    confidence=link.get('confidence', 0.75),
                    attributes={'chain_id': chain['chain_id'], 'hop': str(j)},
                )
                result.knowledge.append(knowledge)
            self.stats['causal_chains'] += 1

        # 6. Extract deformation and failure features as disaster events.
        if deformation_items:
            for item in deformation_items:
                event = Event(
                    event_id=f"evt_{segment_id}_def_{len(result.events)}",
                    event_type=EventType.DISASTER,
                    name=self._truncate_name(f"{section_title}_{item}"),
                    description=item,
                    source_segment=segment_id,
                    source_text=text[:500],
                    confidence=0.85,
                )
                result.events.append(event)
            self.stats['deformation'] += len(deformation_items)

        # 7. Extract mitigation measures as response events.
        if prevention_items:
            for item in prevention_items:
                event = Event(
                    event_id=f"evt_{segment_id}_prev_{len(result.events)}",
                    event_type=EventType.RESPONSE,
                    name=self._truncate_name(f"{section_title}_{item}"),
                    description=item,
                    source_segment=segment_id,
                    source_text=text[:500],
                    confidence=0.8,
                )
                result.events.append(event)
            self.stats['prevention'] += len(prevention_items)

        return result

    # Extraction methods by information type

    def _extract_numeric_params(self, text: str) -> List[Tuple[str, str]]:
        """Extract numeric parameters."""
        params = []
        for param_name, patterns in self.NUMERIC_PATTERNS.items():
            for pattern, default_unit, confidence in patterns:
                matches = re.findall(pattern, text)
                for match in matches:
                    if isinstance(match, tuple):
                        # Check whether the pattern uses scientific notation with a multiplication sign.
                        if '×' in pattern or 'x' in pattern or 'X' in pattern:
                            # Preserve a scientific-notation value, for example 1700 x 10^4 m^3.
                            base = match[0] if match[0] else ''
                            exponent = match[1] if len(match) > 1 and match[1] else ''
                            superscript = match[2] if len(match) > 2 and match[2] else ''

                            # A three-digit exponent such as 104 may reflect a lost superscript in 10^4.
                            if len(exponent) == 3 and exponent.startswith('10'):
                                superscript = exponent[2]
                                exponent = '10'

                            if superscript:
                                value = f"{base}×{exponent}{superscript}"
                            elif exponent:
                                value = f"{base}×{exponent}"
                            else:
                                value = base
                            unit = default_unit
                        else:
                            # Ordinary numeric pattern, for example 1500 m
                            value = match[0] if match[0] else ''
                            # Range value, for example 5-15 cm
                            if len(match) > 1 and match[1]:
                                value = f"{value}～{match[1]}"
                            unit = match[-1] if len(match) > 1 and match[-1] and len(match[-1]) <= 3 else default_unit
                    else:
                        value = match
                        unit = default_unit
                    value_str = f"{value}{unit}" if unit else value
                    params.append((param_name, value_str))
                    break  # Keep the first match for each parameter type.
        return params

    def _extract_locations(self, text: str) -> List[str]:
        """Extract location information."""
        locations = []
        for pattern, confidence in self.LOCATION_PATTERNS:
            matches = re.findall(pattern, text)
            for match in matches:
                if isinstance(match, tuple):
                    loc = ''.join(filter(None, match))
                else:
                    loc = match
                if loc and len(loc) >= 2:
                    locations.append(loc.strip())
        return list(set(locations))  # Deduplicate.

    def _extract_times(self, text: str) -> List[str]:
        """Extract temporal information."""
        times = []
        for pattern, confidence in self.TIME_PATTERNS:
            matches = re.findall(pattern, text)
            for match in matches:
                if isinstance(match, tuple):
                    # Extract year, month and day from a compact date.
                    if len(match) == 3 and all(len(m) <= 4 for m in match):
                        time_str = f"{match[0]}年{int(match[1])}月{int(match[2])}日"
                        # Filter invalid dates.
                        if 1 <= int(match[1]) <= 12 and 1 <= int(match[2]) <= 31:
                            times.append(time_str)
                    else:
                        time_str = ''.join(filter(None, match))
                        if time_str:
                            times.append(time_str.strip())
                else:
                    if match:
                        times.append(match.strip())
        return list(set(times))

    def _extract_geology(self, text: str) -> List[str]:
        """Extract geological conditions."""
        items = []
        for pattern, confidence in self.GEOLOGY_PATTERNS:
            matches = re.findall(pattern, text)
            for match in matches:
                if isinstance(match, tuple):
                    item = ''.join(filter(None, match))
                else:
                    item = match
                if item and len(item.strip()) >= 2:
                    items.append(item.strip())
        return list(set(items))

    def _extract_causal(self, text: str) -> List[Tuple[str, str]]:
        """Extract causal relationships."""
        relations = []
        for pattern, confidence in self.CAUSAL_PATTERNS:
            matches = re.findall(pattern, text)
            for match in matches:
                if isinstance(match, tuple) and len(match) >= 2:
                    cause, effect = match[0], match[1]
                    if cause.strip() and effect.strip():
                        relations.append((cause.strip(), effect.strip()))
                elif isinstance(match, str):
                    relations.append((match.strip(), "滑坡发生"))
        return relations

    def _extract_deformation(self, text: str) -> List[str]:
        """Extract deformation and failure features."""
        items = []
        for pattern, confidence in self.DEFORMATION_PATTERNS:
            matches = re.findall(pattern, text)
            for match in matches:
                if isinstance(match, tuple):
                    item = ''.join(filter(None, match))
                else:
                    item = match
                if item and len(item.strip()) >= 2:
                    items.append(item.strip())
        return list(set(items))

    def _extract_prevention(self, text: str) -> List[str]:
        """Extract mitigation measures."""
        items = []
        for pattern, confidence in self.PREVENTION_PATTERNS:
            matches = re.findall(pattern, text)
            for match in matches:
                if isinstance(match, tuple):
                    item = ''.join(filter(None, match))
                else:
                    item = match
                if item and len(item.strip()) >= 2:
                    items.append(item.strip())
        return list(set(items))

    def _extract_causal_chain(self, text: str, segment_id: str) -> List[dict]:
        """Extract multi-hop causal chains A->B->C."""
        chains = []
        chain_count = 0

        for pattern, base_confidence in self.CAUSAL_CHAIN_PATTERNS:
            matches = re.findall(pattern, text)
            for match in matches:
                try:
                    if isinstance(match, tuple):
                        # Filter empty values.
                        parts = [p for p in match if p and len(p.strip()) >= 2]
                        if len(parts) < 3:
                            continue

                        chain_id = f"chain_{segment_id}_{chain_count}"
                        links = []

                        # Build multi-hop links.
                        for i in range(len(parts) - 1):
                            cause = parts[i].strip()
                            effect = parts[i + 1].strip()
                            if cause and effect:
                                links.append({
                                    'cause': cause,
                                    'effect': effect,
                                    'description': f"{cause}导致{effect}",
                                    'confidence': base_confidence,
                                })

                        if len(links) >= 2:
                            chains.append({
                                'chain_id': chain_id,
                                'links': links,
                            })
                            chain_count += 1
                except Exception:
                    continue

        return chains

    def _extract_coordinates(self, text: str) -> List[str]:
        """Extract longitude and latitude coordinates."""
        coordinates = []
        lng_parts = []
        lat_parts = []

        for pattern, coord_type, confidence in self.COORDINATE_PATTERNS:
            matches = re.findall(pattern, text)
            for match in matches:
                try:
                    if coord_type == 'latlng':
                        # Combined longitude/latitude format
                        if isinstance(match, tuple) and len(match) >= 2:
                            lat_val = match[0]
                            lng_val = match[1]
                            coord_str = f"N{lat_val}°, E{lng_val}°"
                            coordinates.append(coord_str)
                    elif coord_type == 'lng':
                        if isinstance(match, tuple):
                            parts = [p for p in match if p]
                            if len(parts) == 3:
                                lng_parts.append(f"东经{parts[0]}°{parts[1]}'{parts[2]}\"")
                            elif len(parts) == 2:
                                lng_parts.append(f"东经{parts[0]}°{parts[1]}'")
                            elif len(parts) == 1:
                                lng_parts.append(f"东经{parts[0]}°")
                        else:
                            lng_parts.append(f"东经{match}°")
                    elif coord_type == 'lat':
                        if isinstance(match, tuple):
                            parts = [p for p in match if p]
                            if len(parts) == 3:
                                lat_parts.append(f"北纬{parts[0]}°{parts[1]}'{parts[2]}\"")
                            elif len(parts) == 2:
                                lat_parts.append(f"北纬{parts[0]}°{parts[1]}'")
                            elif len(parts) == 1:
                                lat_parts.append(f"北纬{parts[0]}°")
                        else:
                            lat_parts.append(f"北纬{match}°")
                except Exception:
                    continue

        # Try to pair longitude and latitude.
        if lng_parts and lat_parts:
            for i in range(min(len(lng_parts), len(lat_parts))):
                coordinates.append(f"{lat_parts[i]}, {lng_parts[i]}")
            # Remaining individual coordinates
            for p in lng_parts[min(len(lng_parts), len(lat_parts)):]:
                coordinates.append(p)
            for p in lat_parts[min(len(lng_parts), len(lat_parts)):]:
                coordinates.append(p)
        else:
            coordinates.extend(lng_parts)
            coordinates.extend(lat_parts)

        return list(set(coordinates))

    def _extract_relative_positions(self, text: str) -> List[str]:
        """Extract relative positions."""
        positions = []
        for pattern, confidence in self.RELATIVE_POSITION_PATTERNS:
            matches = re.findall(pattern, text)
            for match in matches:
                if isinstance(match, tuple):
                    parts = [p for p in match if p]
                    if len(parts) >= 2:
                        # Combine direction and distance.
                        positions.append(''.join(parts))
                    elif len(parts) == 1:
                        positions.append(parts[0])
                else:
                    if match and len(match.strip()) >= 2:
                        positions.append(match.strip())
        return list(set(positions))

    def extract_from_table(
        self,
        table_data: List[dict],
        table_title: str = "",
        segment_id: str = "table_0000",
    ) -> ExtractionResult:
        """Extract structured parameters from table data."""
        result = ExtractionResult()

        if not table_data:
            return result

        # Normalize headers across languages and letter case.
        header_mapping = {
            '参数': ['参数', '指标', '项目', '名称', '属性', 'parameter', 'name', 'item'],
            '数值': ['数值', '值', '数据', '结果', 'value', 'result', 'data'],
            '单位': ['单位', '量纲', 'unit', 'dimension'],
            '备注': ['备注', '说明', '注释', 'note', 'remark', 'comment', 'description'],
        }

        def normalize_key(key: str) -> str:
            """Normalize a table-header key."""
            key_lower = key.strip().lower()
            for std_key, aliases in header_mapping.items():
                if key_lower in aliases or key_lower == std_key.lower():
                    return std_key
            return key.strip()

        # Extract parameters from all rows.
        all_params = []
        for row in table_data:
            # Normalize row data.
            norm_row = {normalize_key(k): v for k, v in row.items()}

            param_name = norm_row.get('参数', '')
            param_value = norm_row.get('数值', '')
            param_unit = norm_row.get('单位', '')
            param_note = norm_row.get('备注', '')

            if not param_name or not param_value:
                continue

            # Build a complete parameter value including its unit.
            full_value = str(param_value)
            if param_unit:
                full_value = f"{full_value}{param_unit}"

            all_params.append((param_name, full_value))

            # Try numeric patterns to identify the specific parameter type.
            for pattern_name, patterns in self.NUMERIC_PATTERNS.items():
                for pattern, default_unit, confidence in patterns:
                    # Check whether the parameter name matches.
                    param_name_lower = param_name.lower()
                    pattern_name_lower = pattern_name.lower()
                    if param_name_lower in pattern_name_lower or pattern_name_lower in param_name_lower:
                        # Use the pattern name as the parameter name after a match.
                        break

        if all_params:
            event = Event(
                event_id=f"evt_{segment_id}_table",
                event_type=EventType.OBSERVATION,
                name=self._truncate_name(f"{table_title}_表格参数"),
                description=f"从表格「{table_title}」中提取的{len(all_params)}项参数",
                attributes=dict(all_params),
                source_segment=segment_id,
                source_text=f"表格：{table_title}",
                confidence=0.9,
            )
            result.events.append(event)
            self.stats['table_params'] += len(all_params)

        return result

    def get_stats(self) -> dict:
        """Return extraction statistics."""
        return dict(self.stats)


