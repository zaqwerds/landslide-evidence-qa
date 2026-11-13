# -*- coding: utf-8 -*-
"""Streamlit interface for uploads, graph construction, result browsing and QA."""

from __future__ import annotations

import os
import re
import hashlib
import sys
import html as html_lib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote

import pandas as pd
import streamlit as st
from py2neo import Graph
from rdflib import Graph as RDFGraph


PROGRAM_DIR = Path(__file__).resolve().parents[1]
if str(PROGRAM_DIR) not in sys.path:
    sys.path.insert(0, str(PROGRAM_DIR))

from backend.pipeline import BackendPipeline, BackendPipelineConfig
from backend.cleanup_service import clear_local_extracted_artifacts
from backend.storage_service import clear_instance_graph
from qa.models import collect_media_supports
from qa.service import GraphQAService


st.set_page_config(
    page_title="滑坡勘查报告知识图谱",
    page_icon="⛰️",
    layout="wide",
)


STAGE_PROGRESS = {
    "ingest": 8,
    "parse": 24,
    "extract": 48,
    "fuse": 62,
    "validate": 76,
    "store": 94,
    "complete": 100,
}


def init_state() -> None:
    defaults = {
        "build_result": None,
        "qa_messages": [],
        "qa_service": None,
        "qa_signature": None,
        "preferred_report_id": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def safe_filename(filename: str) -> str:
    name = Path(filename or "report.docx").name
    return re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", name)


def save_upload(uploaded_file) -> Path:
    upload_dir = PROGRAM_DIR / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = upload_dir / f"{stamp}_{safe_filename(uploaded_file.name)}"
    target.write_bytes(uploaded_file.getvalue())
    return target


def active_ontology() -> Path | None:
    """Select the uploaded or saved TTL ontology for this graph-building run."""
    st.sidebar.subheader("滑坡本体")
    uploaded = st.sidebar.file_uploader("上传本体文件（TTL）", type=["ttl"])
    saved_path = PROGRAM_DIR / "input" / "ontology.ttl"

    if uploaded is not None:
        content = uploaded.getvalue()
        try:
            RDFGraph().parse(data=content.decode("utf-8-sig"), format="turtle")
        except Exception as exc:
            st.sidebar.error(f"本体文件无法解析：{exc}")
            return None
        saved_path.parent.mkdir(parents=True, exist_ok=True)
        if not saved_path.exists() or saved_path.read_bytes() != content:
            saved_path.write_bytes(content)

    if saved_path.exists():
        st.sidebar.caption(f"当前本体：{saved_path.name}")
        return saved_path
    st.sidebar.warning("首次构图前请上传滑坡本体 TTL 文件。")
    return None


def connect_graph(uri: str, user: str, password: str) -> Graph:
    graph = Graph(uri, auth=(user, password))
    graph.run("RETURN 1").evaluate()
    return graph


def resolve_path(value: Any) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    if not path.is_absolute():
        path = PROGRAM_DIR / path
    return path.resolve()


def temporary_api_key(provider: str, value: str):
    """Temporarily set API environment variables and restore them on context exit."""
    key_name = "OPENAI_API_KEY" if provider == "openai" else "DEEPSEEK_API_KEY"

    class KeyContext:
        def __enter__(self):
            self.previous = os.environ.get(key_name)
            if value:
                os.environ[key_name] = value
            return key_name

        def __exit__(self, exc_type, exc, traceback):
            if self.previous is None:
                os.environ.pop(key_name, None)
            else:
                os.environ[key_name] = self.previous

    return KeyContext()


def sidebar_settings() -> Dict[str, Any]:
    st.sidebar.header("运行配置")
    st.sidebar.caption("模型与数据库设置用于当前会话；上传的本体保存在本机。")
    ontology_path = active_ontology()

    st.sidebar.subheader("模型与知识抽取")
    extraction_mode = st.sidebar.selectbox(
        "正文抽取方式", ["大模型", "本地规则"], index=0
    )
    provider = st.sidebar.selectbox(
        "服务商", ["deepseek", "openai", "local"], index=0
    )
    default_model = {
        "deepseek": "deepseek-chat",
        "openai": "gpt-4o-mini",
        "local": "qwen3-14b",
    }[provider]
    model = st.sidebar.text_input("模型", value=default_model)
    default_api_base = {
        "deepseek": "https://api.deepseek.com",
        "openai": "https://api.openai.com/v1",
        "local": "http://localhost:8000/v1",
    }[provider]
    api_base = st.sidebar.text_input("API地址", value=default_api_base)
    api_key = st.sidebar.text_input(
        "API Key",
        value="",
        type="password",
        placeholder="留空则使用系统环境变量",
    )
    key_name = "OPENAI_API_KEY" if provider == "openai" else "DEEPSEEK_API_KEY"
    if extraction_mode == "本地规则":
        st.sidebar.caption("正文使用本地规则；填写API Key后仍可用于问答回答。")
    elif provider == "local":
        st.sidebar.success("本地接口不要求云端API Key")
    elif api_key or os.environ.get(key_name):
        st.sidebar.success(f"已检测到 {key_name}")
    else:
        st.sidebar.warning(f"尚未配置 {key_name}")

    st.sidebar.subheader("Neo4j")
    neo4j_uri = st.sidebar.text_input("URI", value="neo4j://127.0.0.1:7687")
    neo4j_user = st.sidebar.text_input("用户名", value="neo4j")
    neo4j_password = st.sidebar.text_input(
        "密码", value=os.environ.get("NEO4J_PASSWORD", ""), type="password"
    )
    if st.sidebar.button("测试 Neo4j 连接", width="stretch"):
        try:
            connect_graph(neo4j_uri.strip(), neo4j_user.strip(), neo4j_password)
            st.sidebar.success("Neo4j 连接成功")
        except Exception as exc:
            st.sidebar.error(f"连接失败：{type(exc).__name__}: {exc}")

    st.sidebar.caption("以下两个清理操作互相独立，均保留原始报告。")
    if st.sidebar.button(
        "清理Neo4j数据",
        width="stretch",
        help="删除报告、文字、表格、图片和事件实例，保留本体/Schema。",
    ):
        try:
            graph = connect_graph(neo4j_uri.strip(), neo4j_user.strip(), neo4j_password)
            deleted_nodes = clear_instance_graph(graph)
            st.session_state.build_result = None
            st.session_state.qa_service = None
            st.session_state.qa_messages = []
            st.sidebar.success(f"Neo4j清理完成：删除 {deleted_nodes} 个实例节点。")
        except Exception as exc:
            st.sidebar.error(f"Neo4j清理失败：{type(exc).__name__}: {exc}")

    if st.sidebar.button(
        "清理本地表格和图片",
        width="stretch",
        help="只删除artifacts中的提取表格和图片，不删除output运行记录及原始报告。",
    ):
        try:
            local_stats = clear_local_extracted_artifacts(PROGRAM_DIR)
            st.session_state.build_result = None
            st.session_state.qa_service = None
            st.session_state.qa_messages = []
            st.sidebar.success(
                f"本地表格和图片清理完成：删除 {local_stats['deleted_files']} 个文件，"
                f"释放 {local_stats['deleted_bytes'] / 1024 / 1024:.2f} MB。"
            )
        except Exception as exc:
            st.sidebar.error(f"本地清理失败：{type(exc).__name__}: {exc}")

    st.sidebar.subheader("处理参数")
    max_segments = st.sidebar.number_input(
        "文字分段上限（0表示全部）", min_value=0, max_value=100000, value=0, step=1
    )
    max_segment_length = st.sidebar.number_input(
        "每段最大字符数", min_value=200, max_value=10000, value=1500, step=100
    )
    enable_validation = st.sidebar.checkbox("执行知识验证", value=True)
    write_neo4j = st.sidebar.checkbox("写入Neo4j", value=True)

    with st.sidebar.expander("知识抽取高级参数"):
        extraction_temperature = st.number_input(
            "抽取温度", min_value=0.0, max_value=2.0, value=0.1, step=0.1,
            help="数值越低，模型输出通常越稳定。仅对大模型抽取生效。",
        )
        extraction_max_tokens = st.number_input(
            "单段抽取输出 Token 上限", min_value=1, max_value=100000,
            value=4096, step=100,
        )
        extraction_timeout_seconds = st.number_input(
            "单次抽取请求超时（秒）", min_value=1, max_value=3600,
            value=120, step=10,
        )
        min_confidence = st.number_input(
            "验证最低置信度", min_value=0.0, max_value=1.0,
            value=0.3, step=0.05,
            help="仅在启用知识验证时生效；部分事件类型还受自身阈值约束。",
        )

    with st.sidebar.expander("问答高级参数"):
        qa_temperature = st.number_input(
            "回答温度", min_value=0.0, max_value=2.0, value=0.1, step=0.1,
        )
        qa_max_tokens = st.number_input(
            "回答输出 Token 上限", min_value=1, max_value=100000,
            value=900, step=100,
        )
        qa_timeout_seconds = st.number_input(
            "回答请求超时（秒）", min_value=1, max_value=3600,
            value=60, step=10,
        )
        qa_top_k = st.number_input(
            "最多检索证据数（0为自动）", min_value=0, max_value=100,
            value=0, step=1,
        )
        table_format = st.selectbox(
            "表格证据格式", ["结构化", "传统文本"], index=0,
        )

    return {
        "ttl_path": ontology_path,
        "provider": provider,
        "extraction_mode": "llm" if extraction_mode == "大模型" else "offline",
        "model": model.strip(),
        "api_base": api_base.strip(),
        "api_key": api_key.strip(),
        "neo4j_uri": neo4j_uri.strip(),
        "neo4j_user": neo4j_user.strip(),
        "neo4j_password": neo4j_password,
        "max_segments": int(max_segments),
        "max_segment_length": int(max_segment_length),
        "extraction_temperature": float(extraction_temperature),
        "extraction_max_tokens": int(extraction_max_tokens),
        "extraction_timeout_seconds": int(extraction_timeout_seconds),
        "enable_validation": enable_validation,
        "min_confidence": float(min_confidence),
        "write_neo4j": write_neo4j,
        "qa_temperature": float(qa_temperature),
        "qa_max_tokens": int(qa_max_tokens),
        "qa_timeout_seconds": int(qa_timeout_seconds),
        "qa_top_k": int(qa_top_k),
        "table_format": "structured" if table_format == "结构化" else "legacy",
        # Rebuilding a report replaces only its own instances and preserves other reports.
        "clear_events": True,
    }


def available_reports() -> Dict[str, Path]:
    candidates: List[Path] = []
    input_root = PROGRAM_DIR / "input"
    if input_root.exists():
        candidates.extend(input_root.glob("report_*/source.docx"))
        candidates.extend(input_root.glob("report_*/source.pdf"))
    unique: Dict[str, Path] = {}
    for path in sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True):
        label = f"{path.name}  —  {path.parent}"
        unique.setdefault(label, path.resolve())
    return unique


def render_build_tab(settings: Dict[str, Any]) -> None:
    st.subheader("上传勘查报告并构建知识图谱")
    st.write("选择 DOCX/PDF 报告，在左侧设置模型、解析参数和 Neo4j 连接，再开始处理。")
    source_mode = st.radio(
        "报告来源",
        ["上传新报告", "使用已有报告"],
        horizontal=True,
        help="已有报告不会重复上传；新报告会保存到当前项目的 uploads 目录。",
    )
    uploaded = None
    selected_existing: Path | None = None
    if source_mode == "上传新报告":
        uploaded = st.file_uploader("选择勘查报告", type=["docx", "pdf"])
    else:
        reports = available_reports()
        if reports:
            selected_label = st.selectbox("选择已有报告", list(reports))
            selected_existing = reports[selected_label]
        else:
            st.warning("没有找到已有报告，请切换到“上传新报告”。")

    left, right = st.columns([2, 1])
    with left:
        if source_mode == "上传新报告" and uploaded:
            st.info(f"已选择：{uploaded.name}（{uploaded.size / 1024 / 1024:.2f} MB）")
        elif selected_existing:
            st.info(f"已选择：{selected_existing}")
        else:
            st.caption("请选择一个已有报告，或上传新的DOCX/PDF。")
    with right:
        source_ready = uploaded is not None or selected_existing is not None
        start = st.button(
            "开始解析并构建图谱",
            type="primary",
            width="stretch",
            disabled=not source_ready,
        )

    if start and source_ready:
        if settings["ttl_path"] is None:
            st.error("请先在左侧上传滑坡本体 TTL 文件。")
            return
        key_value = settings["api_key"]
        if not key_value and settings["provider"] != "local":
            key_name = (
                "OPENAI_API_KEY"
                if settings["provider"] == "openai"
                else "DEEPSEEK_API_KEY"
            )
            key_value = os.environ.get(key_name, "")
        if settings["extraction_mode"] == "llm" and settings["provider"] != "local" and not key_value:
            st.error("缺少API Key。请在左侧填写，或配置对应的系统环境变量。")
            return
        if settings["write_neo4j"] and not settings["neo4j_password"]:
            st.error("写入 Neo4j 需要在左侧填写密码。")
            return

        report_path = save_upload(uploaded) if uploaded is not None else selected_existing
        if report_path is None:
            st.error("没有选择报告。")
            return
        progress = st.progress(0, text="准备处理")
        status = st.empty()

        def on_progress(stage: str, message: str) -> None:
            value = STAGE_PROGRESS.get(stage, 0)
            progress.progress(value, text=message)
            status.info(f"当前阶段：{message}")

        config = BackendPipelineConfig(
            document=report_path,
            project_root=PROGRAM_DIR,
            ttl_path=settings["ttl_path"],
            mode=settings["extraction_mode"],
            provider=settings["provider"],
            api_base=settings["api_base"] or None,
            model=settings["model"] or None,
            max_segments=settings["max_segments"],
            max_segment_length=settings["max_segment_length"],
            extraction_temperature=settings["extraction_temperature"],
            extraction_max_tokens=settings["extraction_max_tokens"],
            extraction_timeout_seconds=settings["extraction_timeout_seconds"],
            enable_validation=settings["enable_validation"],
            min_confidence=settings["min_confidence"],
            write_neo4j=settings["write_neo4j"],
            clear_events=settings["clear_events"],
            neo4j_uri=settings["neo4j_uri"],
            neo4j_user=settings["neo4j_user"],
            neo4j_password=settings["neo4j_password"],
        )
        try:
            with temporary_api_key(settings["provider"], key_value):
                result = BackendPipeline(config, progress_callback=on_progress).run()
            st.session_state.build_result = result
            st.session_state.qa_service = None
            st.session_state.preferred_report_id = result["report_id"]
            st.session_state.pop("qa_report", None)
            st.session_state.pop("results_report", None)
            progress.progress(100, text="构图完成")
            status.success(
                "报告处理完成，知识已写入Neo4j。"
                if settings["write_neo4j"] else "报告处理完成，本地知识包已生成。"
            )
        except Exception as exc:
            status.error(f"处理失败：{type(exc).__name__}: {exc}")

    result = st.session_state.build_result
    if result:
        st.divider()
        st.subheader("最近一次构图结果")
        content = result.get("content", {})
        extraction = result.get("extraction", {})
        fusion = result.get("fusion", {})
        validation = result.get("validation", {}).get("counts", {})
        columns = st.columns(6)
        values = [
            ("文字块", content.get("text_blocks", 0)),
            ("表格", content.get("tables", 0)),
            ("图片", content.get("figures", 0)),
            ("原始事件", extraction.get("total_events", 0)),
            ("融合后事件", fusion.get("output_events", 0)),
            ("验证通过", validation.get("accepted_events", 0)),
        ]
        for column, (label, value) in zip(columns, values):
            column.metric(label, value)
        st.code(result.get("run_dir", ""), language=None)


def table_dataframe(graph: Graph, table_id: str) -> pd.DataFrame:
    rows = graph.run(
        """
        MATCH (:Table {table_id: $table_id})-[:HAS_ROW]->(row:TableRow)
              -[:HAS_CELL]->(cell:TableCell)
        RETURN row.row_index AS row_index, row.row_type AS row_type,
               cell.column_index AS column_index, cell.header AS header,
               cell.raw_text AS value
        ORDER BY row.row_index, cell.column_index
        """,
        table_id=table_id,
    ).data()
    grouped: Dict[int, Dict[str, Any]] = {}
    for item in rows:
        row_index = int(item.get("row_index") or 0)
        header = str(item.get("header") or f"列{item.get('column_index', 0) + 1}")
        key = header
        if key in grouped.setdefault(row_index, {}):
            key = f"{header}_{item.get('column_index', 0) + 1}"
        grouped[row_index][key] = item.get("value", "")
    return pd.DataFrame([grouped[index] for index in sorted(grouped)])


def figure_display_name(item: Dict[str, Any]) -> str:
    """Prefer the report caption; otherwise generate a stable, recognizable figure name."""
    caption = str(item.get("caption") or "").strip()
    if caption:
        return caption
    section = str(item.get("section_title") or "").strip()
    figure_type = str(item.get("figure_type") or "图片").strip()
    page = int(item.get("page") or 0)
    if section and section not in {"未知章节", "文档开头"}:
        return f"{section}－{figure_type}"
    return f"第{page}页{figure_type}" if page else figure_type


def table_view_url(table_id: str) -> str:
    """Generate an HTML-table viewing URL within the same web application."""
    return f"?table_html={quote(str(table_id or ''), safe='')}"


def render_table_html_page(settings: Dict[str, Any], table_id: str) -> None:
    """Read and display an extracted HTML table in a separate browser tab."""
    st.title("HTML表格查看")
    try:
        graph = connect_graph(
            settings["neo4j_uri"], settings["neo4j_user"], settings["neo4j_password"]
        )
        record = graph.run(
            """
            MATCH (table:Table {table_id: $table_id})
            RETURN table.title AS title, table.html_path AS html_path
            """,
            table_id=table_id,
        ).data()
    except Exception as exc:
        st.error(f"无法读取表格节点：{exc}")
        return

    if not record:
        st.error(f"Neo4j中没有找到表格：{table_id}")
        return
    title = str(record[0].get("title") or table_id)
    html_path = resolve_path(record[0].get("html_path"))
    if not html_path or not html_path.exists():
        st.error("对应的HTML表格文件不存在，可能已经清理了本地提取结果。")
        return

    st.subheader(title)
    st.caption(str(html_path))
    st.html(html_path.read_text(encoding="utf-8"))


def render_results_tab(settings: Dict[str, Any]) -> None:
    st.subheader("Neo4j结果浏览")
    if not settings["neo4j_password"]:
        st.info("请先在左侧填写 Neo4j 密码，再浏览构图结果。")
        return
    try:
        graph = connect_graph(
            settings["neo4j_uri"], settings["neo4j_user"], settings["neo4j_password"]
        )
    except Exception as exc:
        st.error(f"无法连接Neo4j：{exc}")
        return

    reports = graph.run(
        "MATCH (r:Report) RETURN r.report_id AS report_id, r.name AS name ORDER BY r.name"
    ).data()
    if not reports:
        st.info("图谱中没有报告。")
        return
    report_labels = {f"{row.get('name') or row['report_id']} [{row['report_id']}]": row["report_id"] for row in reports}
    preferred = st.session_state.preferred_report_id
    report_ids = list(report_labels.values())
    selected_index = report_ids.index(preferred) if preferred in report_ids else 0
    report_id = report_labels[st.selectbox(
        "选择报告", list(report_labels), index=selected_index, key="results_report"
    )]
    counts = {}
    for key, label, relation in (
        ("events", "Event", "HAS_KNOWLEDGE"),
        ("tables", "Table", "HAS_CONTENT"),
        ("figures", "Figure", "HAS_CONTENT"),
        ("text_blocks", "TextBlock", "HAS_CONTENT"),
    ):
        counts[key] = int(graph.run(
            f"MATCH (:Report {{report_id: $report_id}})-[:{relation}]->(n:{label}) RETURN count(n)",
            report_id=report_id,
        ).evaluate() or 0)
    columns = st.columns(4)
    for column, key, label in zip(
        columns,
        ("events", "tables", "figures", "text_blocks"),
        ("事件", "表格", "图片", "文字块"),
    ):
        column.metric(label, counts.get(key, 0))

    table_tab, figure_tab, event_tab = st.tabs(["表格", "图片", "事件"])
    with table_tab:
        tables = graph.run(
            "MATCH (:Report {report_id: $report_id})-[:HAS_CONTENT]->(t:Table) "
            "RETURN properties(t) AS item ORDER BY t.table_id",
            report_id=report_id,
        ).data()
        table_items = [row["item"] for row in tables]
        if not table_items:
            st.info("当前图谱中没有表格。")
        else:
            labels = {
                f"{item.get('title') or item.get('table_id')}  [{item.get('table_id')}]": item
                for item in table_items
            }
            selected_label = st.selectbox("选择表格", list(labels))
            selected = labels[selected_label]
            st.caption(
                f"章节：{selected.get('section_title', '')} ｜ "
                f"页码：{selected.get('page', 0)} ｜ "
                f"{selected.get('row_count', 0)}行×{selected.get('column_count', 0)}列"
            )
            dataframe = table_dataframe(graph, selected.get("table_id", ""))
            st.dataframe(dataframe, width="stretch", hide_index=True)
            st.code(str(resolve_path(selected.get("html_path")) or ""), language=None)

    with figure_tab:
        figures = graph.run(
            "MATCH (:Report {report_id: $report_id})-[:HAS_CONTENT]->(f:Figure) "
            "RETURN properties(f) AS item ORDER BY f.source_order",
            report_id=report_id,
        ).data()
        figure_items = [row["item"] for row in figures]
        if not figure_items:
            st.info("当前图谱中没有图片。")
        else:
            labels = {
                f"{figure_display_name(item)} ｜ {item.get('filename', '')} "
                f"[{item.get('figure_id', '')}]": item
                for item in figure_items
            }
            selected_label = st.selectbox("选择图片", list(labels))
            selected = labels[selected_label]
            image_path = resolve_path(selected.get("relative_path"))
            st.caption(
                f"图名：{figure_display_name(selected)} ｜ "
                f"类型：{selected.get('figure_type', '')} ｜ "
                f"章节：{selected.get('section_title', '')} ｜ "
                f"页码：{selected.get('page', 0)}"
            )
            if image_path and image_path.exists():
                try:
                    st.image(str(image_path), caption=selected.get("caption") or image_path.name)
                except Exception:
                    st.warning("该图片格式无法在浏览器中直接预览，可通过下方路径打开。")
            else:
                st.warning("图片文件不存在。")
            st.code(str(image_path or ""), language=None)
            if selected.get("analysis_text"):
                st.markdown("**图片分析**")
                st.write(selected.get("analysis_text"))

    with event_tab:
        events = graph.run(
            """
            MATCH (:Report {report_id: $report_id})-[:HAS_KNOWLEDGE]->(e:Event)
            RETURN e.name AS 名称, e.event_type AS 类型, e.description AS 描述,
                   e.location AS 位置, e.time AS 时间, e.confidence AS 置信度
            ORDER BY e.confidence DESC
            LIMIT 500
            """,
            report_id=report_id,
        ).data()
        st.dataframe(pd.DataFrame(events), width="stretch", hide_index=True)


def get_qa_service(settings: Dict[str, Any], report_id: str) -> GraphQAService:
    key_value = settings["api_key"]
    if not key_value:
        key_name = "OPENAI_API_KEY" if settings["provider"] == "openai" else "DEEPSEEK_API_KEY"
        key_value = os.environ.get(key_name, "")
    signature = (
        settings["neo4j_uri"], settings["neo4j_user"], settings["neo4j_password"],
        settings["provider"], settings["model"], hashlib.sha256(key_value.encode("utf-8")).hexdigest(),
        settings["api_base"], report_id,
        settings["qa_temperature"], settings["qa_max_tokens"],
        settings["qa_timeout_seconds"],
    )
    if st.session_state.qa_service is None or st.session_state.qa_signature != signature:
        st.session_state.qa_service = GraphQAService(
            project_root=PROGRAM_DIR,
            neo4j_uri=settings["neo4j_uri"],
            neo4j_user=settings["neo4j_user"],
            neo4j_password=settings["neo4j_password"],
            api_key=key_value,
            provider=settings["provider"],
            api_base=settings["api_base"] or None,
            model=settings["model"] or "deepseek-chat",
            temperature=settings["qa_temperature"],
            max_tokens=settings["qa_max_tokens"],
            timeout_seconds=settings["qa_timeout_seconds"],
            report_id=report_id,
        )
        st.session_state.qa_signature = signature
        st.session_state.qa_messages = []
    return st.session_state.qa_service


def render_evidence(item, graph: Graph) -> None:
    with st.expander(f"[{item.evidence_id}] {item.title} · {item.modality}"):
        st.write(item.snippet)
        for support in collect_media_supports([item]):
            if support["kind"] == "table":
                dataframe = table_dataframe(graph, support["source_id"])
                if not dataframe.empty:
                    st.dataframe(dataframe, width="stretch", hide_index=True)
                else:
                    st.caption("该表格节点暂时没有可展示的单元格数据。")
                html_path = resolve_path(support.get("path"))
                if html_path and html_path.exists() and html_path.suffix.lower() == ".html":
                    st.markdown(
                        '<a href="{}" target="_blank" rel="noopener noreferrer">'
                        '打开HTML表格：{}</a>'.format(
                            table_view_url(support["source_id"]),
                            html_lib.escape(str(support["title"])),
                        ),
                        unsafe_allow_html=True,
                    )
            elif support["kind"] == "figure":
                image_path = resolve_path(support.get("path"))
                if image_path and image_path.exists():
                    try:
                        st.image(str(image_path), caption=support["title"])
                    except Exception:
                        st.warning(f"{support['title']} 无法在浏览器中直接预览。")
                else:
                    st.warning(f"没有找到图片文件：{support['title']}")
        if item.path:
            st.code(item.path, language=None)


def render_qa_tab(settings: Dict[str, Any]) -> None:
    st.subheader("基于Neo4j证据的连续问答")
    st.caption("回答会同时展示相关表格、图片或原文证据。")
    if not settings["neo4j_password"]:
        st.info("请先在左侧填写 Neo4j 密码并构建图谱，再开始问答。")
        return
    try:
        graph = connect_graph(
            settings["neo4j_uri"], settings["neo4j_user"], settings["neo4j_password"]
        )
        reports = graph.run(
            "MATCH (r:Report) RETURN r.report_id AS report_id, r.name AS name ORDER BY r.name"
        ).data()
        if not reports:
            st.info("图谱中没有报告，请先构图。")
            return
        labels = {f"{row.get('name') or row['report_id']} [{row['report_id']}]": row["report_id"] for row in reports}
        preferred = st.session_state.preferred_report_id
        report_ids = list(labels.values())
        selected_index = report_ids.index(preferred) if preferred in report_ids else 0
        report_id = labels[st.selectbox(
            "问答报告", list(labels), index=selected_index, key="qa_report"
        )]
        service = get_qa_service(settings, report_id)
    except Exception as exc:
        st.error(f"问答服务启动失败：{exc}")
        return

    if st.button("清除对话记录"):
        service.clear_history()
        st.session_state.qa_messages = []

    for message in st.session_state.qa_messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])
            if message["role"] == "assistant":
                for evidence in message.get("evidence", []):
                    render_evidence(evidence, service.graph)

    question = st.chat_input("例如：这份报告有哪些滑坡事件？")
    if question:
        st.session_state.qa_messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.write(question)
        with st.chat_message("assistant"):
            with st.spinner("正在检索图谱证据并生成回答……"):
                result = service.ask(
                    question,
                    top_k=settings["qa_top_k"] or None,
                    table_format=settings["table_format"],
                )
            st.write(result.answer)
            retrieval_info = getattr(result, "retrieval_info", {}) or {}
            budget_text = retrieval_info.get("effective_budget")
            budget_caption = f" ｜ 动态预算：{budget_text}条" if budget_text else ""
            st.caption(
                f"模态：{','.join(result.analysis.modalities)} ｜ "
                f"意图：{result.analysis.intent} ｜ "
                f"证据：{len(result.evidence)}条"
                f"{budget_caption} ｜ "
                f"耗时：{result.elapsed_seconds:.3f}秒"
            )
            for evidence in result.evidence:
                render_evidence(evidence, service.graph)
        st.session_state.qa_messages.append({
            "role": "assistant",
            "content": result.answer,
            "evidence": result.evidence,
        })




def main() -> None:
    init_state()
    settings = sidebar_settings()
    table_html_id = str(st.query_params.get("table_html") or "").strip()
    if table_html_id:
        render_table_html_page(settings, table_html_id)
        return
    st.title("滑坡勘查报告知识图谱系统")
    st.caption("报告上传、API知识抽取、Neo4j构图、图表浏览与证据问答")
    build_tab, results_tab, qa_tab = st.tabs(
        ["报告处理", "结果浏览", "图谱问答"]
    )
    with build_tab:
        render_build_tab(settings)
    with results_tab:
        render_results_tab(settings)
    with qa_tab:
        render_qa_tab(settings)


if __name__ == "__main__":
    main()
