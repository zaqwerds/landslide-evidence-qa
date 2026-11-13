# -*- coding: utf-8 -*-
"""Retrieve and rank multimodal evidence from the current Neo4j content model."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from qa.models import Evidence, QueryAnalysis


class EvidenceRetriever:
    """Execute fixed Cypher only; the LLM cannot generate or modify database queries."""

    TABLE_QUERY = """
    MATCH (report:Report {report_id: $report_id})-[:HAS_CONTENT]->(table:Table)
    OPTIONAL MATCH (table)-[:HAS_ROW]->(row:TableRow)-[:HAS_CELL]->(cell:TableCell)
    WITH table, row, cell
    ORDER BY row.row_index, cell.column_index
    WITH table, row, collect(properties(cell)) AS cells
    WITH table, collect({row_id: row.row_id, row_index: row.row_index,
                         row_type: row.row_type, cells: cells}) AS rows
    RETURN properties(table) AS item, rows
    LIMIT 200
    """

    FIGURE_QUERY = """
    MATCH (report:Report {report_id: $report_id})-[:HAS_CONTENT]->(figure:Figure)
    RETURN properties(figure) AS item
    LIMIT 500
    """

    TEXT_QUERY = """
    MATCH (report:Report {report_id: $report_id})-[:HAS_CONTENT]->(block:TextBlock)
    RETURN properties(block) AS item
    ORDER BY block.source_order
    LIMIT 1000
    """

    EVENT_QUERY = """
    MATCH (report:Report {report_id: $report_id})-[:HAS_KNOWLEDGE]->(event:Event)
    OPTIONAL MATCH (event)-[:EXTRACTED_FROM]->(source)
    WITH event, collect({labels: labels(source), properties: properties(source)}) AS sources
    RETURN properties(event) AS item, sources
    LIMIT 1000
    """

    PREFIX = {"table": "T", "figure": "F", "event": "E", "text": "X"}

    def __init__(self, graph, project_root: str | Path, report_id: str):
        self.graph = graph
        self.project_root = Path(project_root).resolve()
        self.report_id = report_id
        self.executed_queries: List[str] = []
        self.selection_info: Dict[str, Any] = {}

    def retrieve(self, analysis: QueryAnalysis, top_k: int | None = None) -> List[Evidence]:
        """Retrieve evidence and adaptively choose the evidence count."""
        self.executed_queries = []
        self.selection_info = {}
        candidates: List[Evidence] = []
        if "table" in analysis.modalities:
            candidates.extend(self._retrieve_tables(analysis))
        if "figure" in analysis.modalities:
            candidates.extend(self._retrieve_figures(analysis))
        if "event" in analysis.modalities:
            candidates.extend(self._retrieve_events(analysis))
        if "text" in analysis.modalities:
            candidates.extend(self._retrieve_text(analysis))

        self._apply_bm25(analysis, candidates)
        candidates.sort(key=lambda item: (-item.score, item.modality, item.source_id))
        selected = self._select_adaptive(analysis, candidates, top_k)
        counters: Dict[str, int] = {}
        for item in selected:
            counters[item.modality] = counters.get(item.modality, 0) + 1
            item.evidence_id = f"{self.PREFIX[item.modality]}{counters[item.modality]}"
        return selected

    def _select_adaptive(
        self,
        analysis: QueryAnalysis,
        candidates: List[Evidence],
        requested_limit: int | None,
    ) -> List[Evidence]:
        """Truncate evidence using question complexity, relative scores and score drops."""
        automatic_budget = self._adaptive_budget(analysis)
        if requested_limit is None:
            budget = automatic_budget
            strategy = "adaptive"
        else:
            budget = min(automatic_budget, max(1, int(requested_limit)))
            strategy = "adaptive_with_manual_cap"

        positive = [item for item in candidates if item.score > 0]
        if not positive:
            self.selection_info = {
                "strategy": strategy,
                "automatic_budget": automatic_budget,
                "manual_cap": requested_limit,
                "effective_budget": budget,
                "candidate_count": len(candidates),
                "positive_candidate_count": 0,
                "selected_count": 0,
                "score_threshold": 0.0,
                "stop_reason": "no_positive_candidate",
            }
            return []

        best_score = float(positive[0].score)
        explicit_reference = bool(
            analysis.explicit_table_ref or analysis.explicit_figure_ref
        )
        if explicit_reference:
            relative_floor = 0.50
            absolute_floor = 3.0
        elif analysis.intent in {"list", "evidence", "overview"}:
            relative_floor = 0.16
            absolute_floor = 0.8
        else:
            relative_floor = 0.24
            absolute_floor = 1.0
        score_threshold = max(absolute_floor, best_score * relative_floor)

        selected: List[Evidence] = []
        stop_reason = "budget_reached"
        previous_score = best_score
        for candidate in positive:
            score = float(candidate.score)
            if len(selected) >= budget:
                break
            if score < score_threshold:
                stop_reason = "below_relevance_threshold"
                break
            # Retain at least the first two strong matches; stop after a clear score drop thereafter.
            if (
                len(selected) >= 2
                and score < previous_score * 0.52
                and score < best_score * 0.45
            ):
                stop_reason = "score_gap_detected"
                break
            selected.append(candidate)
            previous_score = score
        else:
            stop_reason = "all_relevant_candidates_used"

        # For multimodal questions, try to retain a strong candidate from each retrieved modality.
        if len(analysis.modalities) > 1 and len(selected) < budget:
            present = {item.modality for item in selected}
            for modality in analysis.modalities:
                if modality in present:
                    continue
                fallback = next(
                    (
                        item for item in positive
                        if item.modality == modality
                        and item.score >= max(0.8, best_score * 0.12)
                    ),
                    None,
                )
                if fallback is not None and fallback not in selected:
                    selected.append(fallback)
                    present.add(modality)
                if len(selected) >= budget:
                    break
            selected.sort(key=lambda item: (-item.score, item.modality, item.source_id))

        self.selection_info = {
            "strategy": strategy,
            "automatic_budget": automatic_budget,
            "manual_cap": requested_limit,
            "effective_budget": budget,
            "candidate_count": len(candidates),
            "positive_candidate_count": len(positive),
            "selected_count": len(selected),
            "best_score": round(best_score, 4),
            "score_threshold": round(score_threshold, 4),
            "stop_reason": stop_reason,
        }
        return selected

    @staticmethod
    def _adaptive_budget(analysis: QueryAnalysis) -> int:
        """Assign an interpretable maximum evidence budget of 3-14 items by question type."""
        if analysis.explicit_table_ref or analysis.explicit_figure_ref:
            budget = 3
        elif analysis.intent in {"location", "time", "parameter"}:
            budget = 4
        elif analysis.intent in {"cause", "prevention"}:
            budget = 7
        elif analysis.intent in {"list", "evidence"}:
            budget = 10
        else:
            budget = 6

        question = analysis.question
        if re.search(r"综合|对比|比较|分别|全部|所有|归纳|分析|关系|趋势|过程|多方面", question):
            budget += 2
        if len(analysis.modalities) >= 3:
            budget += 2
        return max(3, min(14, budget))

    def _run(self, query: str) -> List[Dict[str, Any]]:
        self.executed_queries.append(" ".join(query.split()))
        return self.graph.run(query, report_id=self.report_id).data()

    def _retrieve_tables(self, analysis: QueryAnalysis) -> List[Evidence]:
        result: List[Evidence] = []
        for row in self._run(self.TABLE_QUERY):
            table = row.get("item") or {}
            rows = [item for item in (row.get("rows") or []) if item.get("row_id")]
            title = str(table.get("title") or table.get("table_id") or "未命名表格")
            section = str(table.get("section_title") or "")
            row_matches = self._best_table_rows(rows, analysis.keywords)
            matched_row_indices = [item[0] for item in row_matches]
            structured_rows = [
                item for row_index in matched_row_indices
                for item in rows
                if int(item.get("row_index") or 0) == row_index
            ]
            row_text = "\n".join(item[1] for item in row_matches)
            searchable = " ".join([
                title,
                section,
                str(table.get("category") or ""),
                row_text,
            ])
            score = self._lexical_score(
                analysis,
                title=title,
                body=searchable,
                section=section,
                explicit_reference=analysis.explicit_table_ref,
            )
            snippet = row_text or (
                f"表格共{table.get('row_count', 0)}行、{table.get('column_count', 0)}列"
            )
            result.append(Evidence(
                evidence_id="",
                modality="table",
                source_id=str(table.get("table_id") or ""),
                title=title,
                snippet=snippet[:1800],
                path=self._absolute_path(table.get("html_path") or table.get("json_path")),
                score=score,
                metadata={
                    "section_title": section,
                    "page": table.get("page", 0),
                    "category": table.get("category", ""),
                    "json_path": self._absolute_path(table.get("json_path")),
                    "html_path": self._absolute_path(table.get("html_path")),
                    "matched_rows": matched_row_indices,
                    # Retain source table rows and cells with their summary for answer display.
                    "structured_rows": structured_rows,
                    "search_text": searchable,
                },
            ))
        return result

    def _retrieve_figures(self, analysis: QueryAnalysis) -> List[Evidence]:
        result: List[Evidence] = []
        for row in self._run(self.FIGURE_QUERY):
            figure = row.get("item") or {}
            title = str(figure.get("caption") or figure.get("filename") or "未命名图片")
            section = str(figure.get("section_title") or "")
            analysis_text = str(figure.get("analysis_text") or "")
            searchable = " ".join([
                title,
                str(figure.get("figure_type") or ""),
                section,
                analysis_text,
            ])
            score = self._lexical_score(
                analysis,
                title=title,
                body=searchable,
                section=section,
                explicit_reference=analysis.explicit_figure_ref,
            )
            description = analysis_text
            if not description:
                description = "当前只有图题和图片路径，尚未分析图片内部内容。"
            result.append(Evidence(
                evidence_id="",
                modality="figure",
                source_id=str(figure.get("figure_id") or ""),
                title=title,
                snippet=description[:1200],
                path=self._absolute_path(figure.get("relative_path")),
                score=score,
                metadata={
                    "section_title": section,
                    "page": figure.get("page", 0),
                    "figure_type": figure.get("figure_type", ""),
                    "has_analysis": bool(analysis_text),
                    "search_text": searchable,
                },
            ))
        return result

    def _retrieve_text(self, analysis: QueryAnalysis) -> List[Evidence]:
        result: List[Evidence] = []
        for row in self._run(self.TEXT_QUERY):
            block = row.get("item") or {}
            title = str(block.get("section_title") or "报告正文")
            text = str(block.get("text") or "")
            score = self._lexical_score(
                analysis, title=title, body=text, section=title
            )
            result.append(Evidence(
                evidence_id="",
                modality="text",
                source_id=str(block.get("block_id") or ""),
                title=title,
                snippet=text[:1600],
                score=score,
                metadata={
                    "page": block.get("page", 0),
                    "source_order": block.get("source_order", 0),
                    "search_text": f"{title} {text}",
                },
            ))
        return result

    def _retrieve_events(self, analysis: QueryAnalysis) -> List[Evidence]:
        result: List[Evidence] = []
        for row in self._run(self.EVENT_QUERY):
            event = row.get("item") or {}
            title = str(event.get("name") or event.get("event_id") or "未命名事件")
            description = str(event.get("description") or "")
            source_text = str(event.get("source_text") or "")
            properties_text = json.dumps(event, ensure_ascii=False, default=str)
            searchable = f"{title} {description} {source_text} {properties_text}"
            score = self._lexical_score(
                analysis, title=title, body=searchable, section=""
            )
            sources = [item for item in (row.get("sources") or []) if item.get("properties")]
            path, source_summary = self._event_source_summary(sources)
            snippet = description or source_text or source_summary
            result.append(Evidence(
                evidence_id="",
                modality="event",
                source_id=str(event.get("event_id") or ""),
                title=title,
                snippet=snippet[:1600],
                path=path,
                score=score + (0.8 if sources else 0.0),
                metadata={
                    "event_type": event.get("event_type", ""),
                    "location": event.get("location", ""),
                    "time": event.get("time", ""),
                    "trigger": event.get("trigger", ""),
                    "confidence": event.get("confidence", 0),
                    "source_segment": event.get("source_segment", ""),
                    "sources": sources,
                    "search_text": searchable,
                },
            ))
        return result

    def _lexical_score(
        self,
        analysis: QueryAnalysis,
        title: str,
        body: str,
        section: str,
        explicit_reference: str = "",
    ) -> float:
        normalized_title = self._normalize(title)
        normalized_body = self._normalize(body)
        normalized_section = self._normalize(section)
        score = 0.0
        if explicit_reference:
            reference = self._normalize(explicit_reference)
            if reference and reference in normalized_title:
                score += 100.0
            elif reference and reference in normalized_body:
                score += 60.0
        for keyword in analysis.keywords:
            token = self._normalize(keyword)
            if not token:
                continue
            if token in normalized_title:
                score += 8.0
            if token in normalized_section:
                score += 3.0
            occurrences = normalized_body.count(token)
            score += min(occurrences, 4) * 1.5

        question_grams = self._ngrams(self._normalize(analysis.question))
        title_grams = self._ngrams(normalized_title)
        if question_grams and title_grams:
            score += 4.0 * len(question_grams & title_grams) / len(question_grams)
        return round(score, 4)

    def _apply_bm25(self, analysis: QueryAnalysis, candidates: List[Evidence]) -> None:
        if not candidates or not analysis.keywords:
            return
        try:
            from rank_bm25 import BM25Okapi

            corpus = [self._tokens(self._search_text(item)) for item in candidates]
            bm25 = BM25Okapi(corpus)
            scores = bm25.get_scores(self._tokens(" ".join(analysis.keywords)))
            max_score = max(scores) if len(scores) else 0
            if max_score > 0:
                for item, value in zip(candidates, scores):
                    item.score += round(float(value) / float(max_score) * 6.0, 4)
        except Exception:
            return

    def _best_table_rows(
        self,
        rows: List[Dict[str, Any]],
        keywords: List[str],
    ) -> List[Tuple[int, str, float]]:
        scored: List[Tuple[int, str, float]] = []
        for row in rows:
            cells = [cell for cell in (row.get("cells") or []) if cell]
            parts = []
            for cell in cells:
                header = str(cell.get("header") or "")
                value = str(cell.get("raw_text") or "")
                unit = str(cell.get("unit") or "")
                parts.append(f"{header}={value}{unit if unit and unit not in value else ''}")
            text = "；".join(parts)
            normalized = self._normalize(text)
            score = sum(
                1.0 for word in keywords
                if self._normalize(word) and self._normalize(word) in normalized
            )
            if row.get("row_type") == "header":
                score += 0.25
            scored.append((int(row.get("row_index") or 0), text, score))
        matched = [item for item in scored if item[2] > 0.25]
        if matched:
            return sorted(matched, key=lambda item: (-item[2], item[0]))[:4]
        return scored[:3]

    def _event_source_summary(
        self, sources: List[Dict[str, Any]]
    ) -> Tuple[str, str]:
        summaries: List[str] = []
        path = ""
        for source in sources:
            labels = source.get("labels") or []
            props = source.get("properties") or {}
            if "TextBlock" in labels:
                summaries.append(str(props.get("text") or "")[:300])
            elif "Table" in labels:
                summaries.append(str(props.get("title") or "表格证据"))
                path = path or self._absolute_path(props.get("html_path"))
            elif "Figure" in labels:
                summaries.append(str(props.get("caption") or "图片证据"))
                path = path or self._absolute_path(props.get("relative_path"))
        return path, "；".join(item for item in summaries if item)

    def _absolute_path(self, value: Any) -> str:
        if not value:
            return ""
        path = Path(str(value))
        if not path.is_absolute():
            path = self.project_root / path
        return str(path.resolve())

    @staticmethod
    def _normalize(value: Any) -> str:
        return re.sub(r"[\s，。；：、,.;:（）()\[\]【】_—-]+", "", str(value or "")).lower()

    @staticmethod
    def _ngrams(text: str, size: int = 2) -> set[str]:
        if len(text) < size:
            return {text} if text else set()
        return {text[index:index + size] for index in range(len(text) - size + 1)}

    @staticmethod
    def _tokens(text: str) -> List[str]:
        try:
            import jieba

            return [item.strip().lower() for item in jieba.lcut(text) if item.strip()]
        except Exception:
            return re.findall(r"[A-Za-z0-9_.-]+|[\u4e00-\u9fff]{2,}", text.lower())

    @staticmethod
    def _search_text(evidence: Evidence) -> str:
        return str(evidence.metadata.get("search_text") or f"{evidence.title} {evidence.snippet}")
