# -*- coding: utf-8 -*-
"""Identify question intent, keywords and content modalities."""

from __future__ import annotations

import re
from typing import List

from qa.models import QueryAnalysis


class ModalityRouter:
    TABLE_WORDS = {
        "表", "表格", "统计表", "计算表", "数据表", "表中", "哪张表",
        "行", "列", "单元格", "测点", "监测点", "稳定系数",
    }
    FIGURE_WORDS = {
        "图", "图片", "图件", "照片", "剖面图", "平面图", "示意图",
        "曲线图", "矢量图", "insar", "哪张图", "图中",
    }
    EVIDENCE_WORDS = {"证据", "依据", "来源", "原文", "支撑", "证明"}

    INTENT_RULES = [
        ("location", r"位置|位于|哪里|地点|方位|坐标"),
        ("cause", r"原因|成因|为什么|诱发|导致|触发"),
        ("time", r"时间|何时|什么时候|年份|日期|时间线"),
        ("prevention", r"治理|防治|措施|建议|处置|监测预警"),
        ("parameter", r"参数|数值|多少|系数|位移|角度|厚度|体积|面积|高程"),
        ("evidence", r"证据|依据|来源|原文|支撑|证明"),
        ("list", r"有哪些|包含什么|列出|几张|多少张"),
    ]

    STOP_WORDS = {
        "什么", "哪些", "如何", "是否", "这个", "那个", "报告", "请问",
        "一下", "其中", "可以", "有关", "相关", "情况", "内容", "信息",
    }

    TABLE_REF = re.compile(r"表\s*[0-9一二三四五六七八九十]+(?:[.．\-—_][0-9]+)*", re.I)
    FIGURE_REF = re.compile(r"图\s*[0-9一二三四五六七八九十]+(?:[.．\-—_][0-9]+)*", re.I)

    def analyze(self, question: str) -> QueryAnalysis:
        clean_question = (question or "").strip()
        lower = clean_question.lower()
        table_ref = self._first_match(self.TABLE_REF, clean_question)
        figure_ref = self._first_match(self.FIGURE_REF, clean_question)

        modalities: List[str] = []
        if table_ref or any(word in lower for word in self.TABLE_WORDS):
            modalities.append("table")
        if figure_ref or any(word in lower for word in self.FIGURE_WORDS):
            modalities.append("figure")
        if any(word in lower for word in self.EVIDENCE_WORDS):
            modalities.extend(["event", "text", "table", "figure"])
        if not modalities:
            modalities.extend(["event", "text"])
        modalities = list(dict.fromkeys(modalities))

        intent = "overview"
        for candidate, pattern in self.INTENT_RULES:
            if re.search(pattern, clean_question, re.I):
                intent = candidate
                break

        return QueryAnalysis(
            question=clean_question,
            modalities=modalities,
            intent=intent,
            keywords=self._extract_keywords(clean_question, table_ref, figure_ref),
            explicit_table_ref=table_ref,
            explicit_figure_ref=figure_ref,
        )

    def _extract_keywords(
        self,
        question: str,
        table_ref: str,
        figure_ref: str,
    ) -> List[str]:
        words: List[str] = []
        try:
            import jieba

            words.extend(jieba.lcut(question, cut_all=False))
        except Exception:
            pass
        words.extend(re.findall(r"[A-Za-z][A-Za-z0-9_.-]*|[0-9]+(?:\.[0-9]+)?|[\u4e00-\u9fff]{2,}", question))

        result: List[str] = []
        for word in words:
            token = word.strip().lower()
            if not token or token in self.STOP_WORDS or len(token) == 1:
                continue
            if token not in result:
                result.append(token)

        for reference in (table_ref, figure_ref):
            normalized = reference.replace(" ", "").lower()
            if normalized and normalized not in result:
                result.insert(0, normalized)
        return result[:20]

    @staticmethod
    def _first_match(pattern: re.Pattern, text: str) -> str:
        match = pattern.search(text)
        return match.group(0).replace(" ", "") if match else ""
