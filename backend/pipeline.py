# -*- coding: utf-8 -*-
"""Orchestrate the report-specific knowledge graph pipeline."""

from __future__ import annotations

import os
import io
import time
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict

from backend.document_parser import UnifiedDocumentParser
from backend.fusion import BasicKnowledgeFusion
from backend.ingest import ReportIngestor
from backend.knowledge_extraction import KnowledgeExtractionService
from backend.models import ReportWorkspace
from backend.serialization import write_json
from backend.storage_service import UnifiedNeo4jStorage
from backend.validation_service import KnowledgeValidationService
from extraction.event_extractor import Event, EventKnowledge
from schema.ontology_loader import OntologyLoader


@dataclass(frozen=True)
class BackendPipelineConfig:
    document: Path
    project_root: Path
    ttl_path: Path
    mode: str = "offline"
    provider: str = "deepseek"
    api_base: str | None = None
    model: str | None = None
    max_segments: int = 0
    max_segment_length: int = 1500
    extraction_temperature: float = 0.1
    extraction_max_tokens: int = 4096
    extraction_timeout_seconds: int = 120
    enable_validation: bool = True
    min_confidence: float = 0.3
    write_neo4j: bool = True
    clear_events: bool = True
    neo4j_uri: str = "neo4j://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""


class BackendPipeline:
    """Single backend orchestrator; entry points only assemble configuration and invoke it."""

    STAGES = (
        "ingest",
        "parse",
        "extract",
        "fuse",
        "validate",
        "store",
    )

    def __init__(
        self,
        config: BackendPipelineConfig,
        progress_callback: Callable[[str, str], None] | None = None,
    ):
        self.config = config
        self.progress_callback = progress_callback
        self.stage_seconds: Dict[str, float] = {}
        self.workspace: ReportWorkspace | None = None
        self.started_at = datetime.now()

    def run(self) -> Dict[str, Any]:
        self._validate_config()
        summary: Dict[str, Any] = {
            "status": "running",
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "flow": list(self.STAGES),
        }

        try:
            self._notify("ingest", "接入外部报告并创建单报告工作区")
            workspace = self._timed(
                "ingest",
                ReportIngestor(self.config.project_root).ingest,
                self.config.document,
            )
            self.workspace = workspace
            # Never persist the database password in run checkpoints.
            write_json(
                workspace.run_dir / "00_run_config.json",
                {key: value for key, value in vars(self.config).items() if key != "neo4j_password"},
            )

            ontology_loader = OntologyLoader(str(self.config.ttl_path))

            self._notify("parse", "解析文字、表格和图片")
            parser = UnifiedDocumentParser(
                self.config.project_root,
                max_segment_length=self.config.max_segment_length,
            )
            bundle = self._timed(
                "parse", parser.parse, workspace, self.config.max_segments
            )

            self._notify("extract", "从三类内容中抽取知识")
            extraction = KnowledgeExtractionService(
                ontology_loader=ontology_loader,
                mode=self.config.mode,
                provider=self.config.provider,
                api_base=self.config.api_base,
                model=self.config.model,
                temperature=self.config.extraction_temperature,
                max_tokens=self.config.extraction_max_tokens,
                timeout_seconds=self.config.extraction_timeout_seconds,
            )
            events, knowledge, extraction_stats = self._timed(
                "extract", extraction.extract, workspace, bundle
            )

            self._notify("fuse", "执行基础去重和证据汇合")
            fused_events, fused_knowledge, fusion_stats = self._timed(
                "fuse",
                BasicKnowledgeFusion().fuse,
                workspace,
                events,
                knowledge,
            )

            self._notify("validate", "执行语义和 Schema 验证")
            if self.config.enable_validation:
                accepted_events, accepted_knowledge, validation_stats = self._timed(
                    "validate",
                    KnowledgeValidationService(
                        ontology_loader, min_confidence=self.config.min_confidence
                    ).validate,
                    workspace,
                    fused_events,
                    fused_knowledge,
                )
            else:
                accepted_events, accepted_knowledge, validation_stats = (
                    fused_events,
                    fused_knowledge,
                    {"skipped": True},
                )
                write_json(
                    workspace.run_dir / "04_validation.json",
                    {"skipped": True, "reason": "配置关闭验证"},
                )
                write_json(
                    workspace.run_dir / "05_accepted_knowledge.json",
                    {"events": accepted_events, "knowledge": accepted_knowledge},
                )
                self.stage_seconds["validate"] = 0.0

            self._notify("store", "写入统一存储")
            if self.config.write_neo4j:
                neo4j_stats = self._timed(
                    "store",
                    UnifiedNeo4jStorage(
                        ontology_loader=ontology_loader,
                        uri=self.config.neo4j_uri,
                        user=self.config.neo4j_user,
                        password=self.config.neo4j_password,
                        clear_events=self.config.clear_events,
                    ).store,
                    workspace,
                    bundle,
                    accepted_events,
                    accepted_knowledge,
                )
            else:
                neo4j_stats = {
                    "skipped": True,
                    "reason": "配置关闭 Neo4j 写入，本地知识包仍已生成",
                }
                self.stage_seconds["store"] = 0.0
                write_json(workspace.run_dir / "06_neo4j_result.json", neo4j_stats)

            knowledge_package = workspace.run_dir / "05_accepted_knowledge.json"
            summary.update({
                "status": "success",
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "report_id": workspace.report_id,
                "source_name": workspace.source_name,
                "source_format": workspace.source_format,
                "run_dir": str(workspace.run_dir),
                "knowledge_package": str(knowledge_package),
                "content": bundle.stats,
                "extraction": extraction_stats,
                "fusion": fusion_stats,
                "validation": self._validation_summary(validation_stats),
                "neo4j": neo4j_stats,
                "stage_seconds": self.stage_seconds,
            })
            write_json(workspace.run_dir / "99_run_summary.json", summary)
            self._notify("complete", "后端链路已完成")
            return summary
        except Exception as exc:
            summary.update({
                "status": "failed",
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "error_type": type(exc).__name__,
                "error": str(exc),
                "stage_seconds": self.stage_seconds,
            })
            if self.workspace is not None:
                summary["report_id"] = self.workspace.report_id
                summary["run_dir"] = str(self.workspace.run_dir)
                write_json(self.workspace.run_dir / "99_run_summary.json", summary)
            raise

    def _validate_config(self) -> None:
        document = Path(self.config.document)
        if not document.exists() or not document.is_file():
            raise FileNotFoundError(f"输入报告不存在: {document}")
        if document.suffix.lower() not in ReportIngestor.SUPPORTED_FORMATS:
            raise ValueError("当前仅支持 DOCX 和 PDF 报告")
        if not Path(self.config.ttl_path).exists():
            raise FileNotFoundError(f"本体文件不存在: {self.config.ttl_path}")
        if self.config.mode not in {"offline", "llm"}:
            raise ValueError("mode 必须为 offline 或 llm")
        if not 0 <= self.config.extraction_temperature <= 2:
            raise ValueError("抽取温度必须在 0 到 2 之间")
        if self.config.extraction_max_tokens < 1 or self.config.extraction_timeout_seconds < 1:
            raise ValueError("抽取 token 上限和超时时间必须大于 0")
        if not 0 <= self.config.min_confidence <= 1:
            raise ValueError("最低置信度必须在 0 到 1 之间")
        if self.config.mode == "llm" and self.config.provider != "local":
            key_name = (
                "OPENAI_API_KEY"
                if self.config.provider == "openai"
                else "DEEPSEEK_API_KEY"
            )
            if not os.environ.get(key_name):
                raise RuntimeError(f"LLM 模式需要设置环境变量 {key_name}")
        if self.config.write_neo4j and not self.config.neo4j_password:
            raise RuntimeError(
                "写入 Neo4j 需要设置 NEO4J_PASSWORD；调试时可使用 --no-neo4j"
            )

    def _timed(self, stage: str, function: Callable[..., Any], *args: Any) -> Any:
        started = time.perf_counter()
        try:
            # Legacy components print emoji that can trigger UnicodeEncodeError on Windows GBK consoles.
            # The unified entry point uses progress callbacks, so suppress internal component printing.
            with redirect_stdout(io.StringIO()):
                return function(*args)
        finally:
            self.stage_seconds[stage] = round(time.perf_counter() - started, 3)

    def _notify(self, stage: str, message: str) -> None:
        if self.progress_callback:
            self.progress_callback(stage, message)

    @staticmethod
    def _validation_summary(validation: Dict[str, Any]) -> Dict[str, Any]:
        if validation.get("skipped"):
            return validation
        return {
            "counts": validation.get("counts", {}),
            "semantic_report": validation.get("semantic_report"),
            "schema_report": validation.get("schema_report"),
        }


# Keep the original entry-point aliases for existing callers.
PipelineConfig = BackendPipelineConfig
CorePipeline = BackendPipeline
