# -*- coding: utf-8 -*-
"""Derive QA configuration from the ontology schema."""

from typing import Dict, List, Set

try:
    from .ontology_loader import OntologyLoader
except ImportError:
    from ontology_loader import OntologyLoader


class SchemaConfig:
    """Shared ontology-based configuration."""

    def __init__(self, loader: OntologyLoader = None):
        self.loader = loader or OntologyLoader()

        # Entity-type to ontology-class mapping
        # Map QA entity types to corresponding ontology classes.
        self.ENTITY_TYPE_TO_ONTOLOGY_CLASSES: Dict[str, List[str]] = {
            # Landslide-related concepts
            "disaster": [
                "滑坡本体", "b.破坏阶段", "e.滑动机理",
                "体积类型", "受力形式", "层面关系", "物质类型",
                "结构分类", "速度类型",
            ],
            # Geographical locations
            "location": [
                "地理位置", "发生区", "易发区", "地貌特征",
                "临空区", "地形海拔", "坡向", "坡度", "坡形", "坡重", "坡高",
                "斜坡类型", "斜坡结构",
            ],
            # Geology
            "geology": [
                "地层地貌", "地质构造", "地层岩土",
                "地层岩土强度", "地层岩土厚度", "地层岩土含水率",
                "地层土体类型", "地层岩石类型",
                "岩土矿物成分", "岩土颗粒组分",
                "节理", "裂隙", "断裂带", "地震",
            ],
            # Hydrology
            "hydrology": [
                "地表水", "地下水", "含/隔水层", "水文力",
                "地表水入渗", "地表水冲刷", "地表水径流",
                "地下水埋深", "地下水排泄", "地下水补给",
                "泉水出露",
            ],
            # Mechanics and models
            "mechanics": [
                "本构模型", "经验模型", "物理模型", "数值模拟模型",
                "Bishop模型", "Cam-clay模型", "Drucker-Prager模型",
                "Mohr-Coulomb模型", "Spencer模型", "Janbu模型",
                "Fellenius模型", "Terzaghi-Wegman模型",
                "刚体极限平衡法（RLEM）", "有限元法（FEM）",
                "离散元法（DEM）", "边界元法（BEM）",
            ],
            # Physical parameters
            "parameter": [
                "内摩擦角", "内聚力", "剪切模量", "压缩模量",
                "弹性模量", "泊松比", "渗透率", "渗透系数",
                "抗压强度", "抗剪强度", "抗切强度",
                "孔隙水压", "摩擦系数", "黏聚力",
                "材料参数",
            ],
            # Investigation
            "survey": [
                "地质勘查", "地质探测", "地质钻探",
                "勘查地表", "勘查地貌", "勘查岩性", "勘查构造", "勘查水文",
                "地层地震波", "地质雷达", "电法勘探",
                "地下水实验", "地层钻探",
                "压水试验", "抽水试验",
            ],
            # Mitigation and monitoring
            "prevention": [
                "勘查地表", "表征力学量",
                "地表位移", "地表破裂程度",
                "地裂缝空间分布", "滑坡体解体程度",
            ],
            # Environmental factors
            "environment": [
                "环境因素", "植被", "气候", "环境",
                "植被参数", "降雨参数",
            ],
            # Losses and classifications
            "loss": [
                "等级判定", "灾情等级划分", "险情等级划分",
                "次生灾害",
            ],
        }

        # Automatically derived inverse class-to-entity-type mapping
        self.CLASS_TO_ENTITY_TYPE: Dict[str, str] = {}
        for entity_type, class_names in self.ENTITY_TYPE_TO_ONTOLOGY_CLASSES.items():
            for cls_name in class_names:
                self.CLASS_TO_ENTITY_TYPE[cls_name] = entity_type

        # Intent to allowed-entity-type mapping
        self.INTENT_ALLOWED_ENTITY_TYPES: Dict[str, List[str]] = {
            "cause":        ["disaster", "geology", "hydrology"],
            "time":         ["disaster"],
            "feature":      ["disaster", "parameter"],
            "stability":    ["disaster", "mechanics"],
            "scale":        ["disaster", "parameter"],
            "prevention":   ["disaster", "prevention"],
            "include":      ["disaster", "location", "geology"],
            "location":     ["disaster", "location"],
            "threat":       ["disaster", "loss"],
            "monitoring":   ["disaster", "prevention"],
            "report":       ["disaster", "survey"],
            "geology":      ["disaster", "geology"],
            "hydrology":    ["disaster", "hydrology"],
            "mechanics":    ["disaster", "mechanics"],
            "parameter":    ["disaster", "parameter"],
            "model":        ["disaster", "mechanics"],
            "environment":  ["disaster", "environment"],
            "loss":         ["disaster", "loss"],
        }

        # Intent to answer-template mapping
        self.INTENT_TEMPLATES: Dict[str, List[str]] = {
            "location":     ["{entity}位于{values}。", "{entity}地处{values}。"],
            "cause":        ["{entity}的成因主要有{values}。", "引发{entity}的因素包括{values}。"],
            "time":         ["{entity}发生于{values}。", "{entity}的发生时间为{values}。"],
            "threat":       ["{entity}会威胁{values}。", "{entity}危及的对象包括{values}。"],
            "feature":      ["{entity}的变形特征包括{values}。", "{entity}主要表现为{values}。"],
            "stability":    ["{entity}当前处于{values}状态。", "{entity}的稳定性为{values}。"],
            "scale":        ["{entity}的规模为{values}。", "{entity}的大小为{values}。"],
            "prevention":   ["{entity}的防治措施有{values}。", "针对{entity}的治理方案包括{values}。"],
            "include":      ["{entity}包含{values}。", "{entity}的组成部分有{values}。"],
            "monitoring":   ["相关监测点包括{values}。", "布设的监测点有{values}。"],
            "report":       ["{entity}相关资料有{values}。", "查询到{entity}的相关文档有{values}。"],
            "geology":      ["{entity}的地质条件包括{values}。", "{entity}涉及的地质要素有{values}。"],
            "hydrology":    ["{entity}的水文特征包括{values}。", "{entity}的水文条件有{values}。"],
            "mechanics":    ["{entity}的力学特征包括{values}。"],
            "parameter":    ["{entity}的物理参数为{values}。"],
            "model":        ["{entity}相关的力学模型包括{values}。"],
            "environment":  ["{entity}的孕灾环境包括{values}。"],
            "loss":         ["{entity}的损失情况为{values}。", "查询到{entity}的损失数据：{values}。"],
        }

        # Default configuration for core entities
        self.AUTO_DEFAULT_ENTITY_LABEL = "滑坡本体"

    # Query interface

    def get_entity_type(self, class_name: str) -> str:
        """Map an ontology class name to an entity type."""
        return self.CLASS_TO_ENTITY_TYPE.get(class_name, "unknown")

    def get_entity_types(self, class_names: List[str]) -> List[str]:
        """Map ontology class names to entity types."""
        types = set()
        for cn in class_names:
            t = self.get_entity_type(cn)
            if t:
                types.add(t)
        return list(types) if types else ["unknown"]

    def get_allowed_entity_types(self, intent_id: str) -> List[str]:
        """Return entity types permitted for an intent."""
        return self.INTENT_ALLOWED_ENTITY_TYPES.get(intent_id, ["unknown"])

    def get_intent_template(self, intent_id: str) -> str:
        """Return the answer template for an intent."""
        import random
        templates = self.INTENT_TEMPLATES.get(intent_id, ["{entity}的相关信息：{values}。"])
        return random.choice(templates)

    def is_entity_valid_for_intent(self, class_names: List[str], intent_id: str) -> bool:
        """Check whether an entity type is permitted for an intent."""
        allowed_types = self.get_allowed_entity_types(intent_id)
        if "unknown" in allowed_types:
            return True
        entity_types = self.get_entity_types(class_names)
        if "unknown" in entity_types:
            return True
        return any(t in allowed_types for t in entity_types)

    def get_all_class_names(self) -> List[str]:
        """Return all ontology class names."""
        return list(self.loader.classes.keys())

    def get_all_property_names(self) -> List[str]:
        """Return all object-property names."""
        return list(self.loader.object_properties.keys())

    def get_all_data_property_names(self) -> List[str]:
        """Return all datatype-property names."""
        return list(self.loader.data_properties.keys())


