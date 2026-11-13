# -*- coding: utf-8 -*-
"""Orchestrate the standalone Neo4j QA service."""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from py2neo import Graph

from qa.answer_generator import EvidenceAnswerGenerator
from qa.modality_router import ModalityRouter
from qa.models import QAResult
from qa.retriever import EvidenceRetriever


class GraphQAService:
    def __init__(
        self,
        project_root: str | Path,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        api_key: str | None = None,
        provider: str = "deepseek",
        api_base: str | None = None,
        model: str = "deepseek-chat",
        temperature: float = 0.1,
        max_tokens: int = 900,
        timeout_seconds: int = 60,
        top_p: float | None = None,
        report_id: str | None = None,
        graph=None,
    ):
        self.project_root = Path(project_root).resolve()
        self.graph = graph or Graph(
            neo4j_uri, auth=(neo4j_user, neo4j_password)
        )
        self.graph.run("RETURN 1").evaluate()
        reports = self.graph.run(
            "MATCH (report:Report) RETURN report.report_id AS report_id ORDER BY report.report_id"
        ).data()
        report_ids = [str(row["report_id"]) for row in reports if row.get("report_id")]
        if report_id is None:
            if len(report_ids) != 1:
                raise ValueError("请指定报告ID；当前图谱中的报告数量为 %s" % len(report_ids))
            report_id = report_ids[0]
        elif report_id not in report_ids:
            raise ValueError(f"图谱中不存在报告：{report_id}")
        self.report_id = report_id
        self.router = ModalityRouter()
        self.retriever = EvidenceRetriever(self.graph, self.project_root, report_id)
        self.generator = EvidenceAnswerGenerator(
            api_key=api_key,
            provider=provider,
            api_base=api_base,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            top_p=top_p,
        )
        self.history: List[Dict[str, str]] = []
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.log_path = self.project_root / "output" / "qa_sessions" / f"{session_id}.jsonl"

    def ask(
        self,
        question: str,
        top_k: int | None = None,
        *,
        generation_mode: str = "constrained",
        table_format: str = "legacy",
    ) -> QAResult:
        started = time.perf_counter()
        original_question = (question or "").strip()
        if not original_question:
            return QAResult(
                question="",
                answer="问题不能为空。",
                analysis=self.router.analyze(""),
                evidence=[],
            )

        analysis, evidence, queries, retrieval_info = self.retrieve_evidence(
            original_question, top_k=top_k
        )
        result = self.answer_from_evidence(
            original_question,
            analysis,
            evidence,
            generation_mode=generation_mode,
            table_format=table_format,
            conversation_history=self._history_text(),
            cypher_queries=queries,
            retrieval_info=retrieval_info,
        )
        result.elapsed_seconds = round(time.perf_counter() - started, 3)
        self.history.append({"question": original_question, "answer": result.answer})
        self.history = self.history[-5:]
        self._write_log(result)
        return result

    def retrieve_evidence(
        self,
        question: str,
        top_k: int | None = None,
    ):
        """Retrieve once and return freezable analysis, evidence, queries and selection metadata."""
        retrieval_question = self._resolve_context((question or "").strip())
        analysis = self.router.analyze(retrieval_question)
        evidence = self.retriever.retrieve(analysis, top_k=top_k)
        return (
            analysis,
            evidence,
            list(self.retriever.executed_queries),
            dict(self.retriever.selection_info),
        )

    def answer_from_evidence(
        self,
        question: str,
        analysis,
        evidence,
        *,
        generation_mode: str = "constrained",
        table_format: str = "legacy",
        conversation_history: str = "",
        cypher_queries=None,
        retrieval_info=None,
    ) -> QAResult:
        """Generate an answer from existing evidence without querying the graph again."""
        started = time.perf_counter()
        answer, used_llm = self.generator.generate(
            question,
            analysis,
            evidence,
            conversation_history,
            generation_mode=generation_mode,
            table_format=table_format,
        )
        return QAResult(
            question=question,
            answer=answer,
            analysis=analysis,
            evidence=evidence,
            cypher_queries=list(cypher_queries or []),
            used_llm=used_llm,
            elapsed_seconds=round(time.perf_counter() - started, 3),
            retrieval_info=dict(retrieval_info or {}),
            generation_info=dict(self.generator.last_call_metadata),
        )

    def health_check(self) -> Dict[str, int]:
        counts = {}
        for key, label, relation in (
            ("events", "Event", "HAS_KNOWLEDGE"),
            ("tables", "Table", "HAS_CONTENT"),
            ("figures", "Figure", "HAS_CONTENT"),
            ("text_blocks", "TextBlock", "HAS_CONTENT"),
        ):
            counts[key] = int(self.graph.run(
                f"MATCH (:Report {{report_id: $report_id}})-[:{relation}]->(n:{label}) RETURN count(n)",
                report_id=self.report_id,
            ).evaluate() or 0)
        return counts

    def clear_history(self) -> None:
        self.history.clear()

    def _resolve_context(self, question: str) -> str:
        pronouns = ("它", "该滑坡", "这个滑坡", "上述滑坡", "其中", "这张图", "这张表")
        if self.history and any(word in question for word in pronouns):
            return f"上一问：{self.history[-1]['question']}；本次追问：{question}"
        return question

    def _history_text(self) -> str:
        lines = []
        for item in self.history[-5:]:
            lines.append(f"用户：{item['question']}")
            lines.append(f"助手：{item['answer']}")
        return "\n".join(lines)

    def _write_log(self, result: QAResult) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as stream:
            record = asdict(result)
            record["report_id"] = self.report_id
            stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
