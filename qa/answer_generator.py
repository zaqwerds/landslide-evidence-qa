# -*- coding: utf-8 -*-
"""Generate answers from graph evidence with configurable table representations."""

from __future__ import annotations

import hashlib
import os
import time
from typing import Any, Dict, List, Tuple

from qa.models import Evidence, QueryAnalysis


class EvidenceAnswerGenerator:
    GENERATION_MODES = {"constrained", "free"}
    TABLE_FORMATS = {"legacy", "structured", "flattened"}

    def __init__(
        self,
        api_key: str | None = None,
        provider: str = "deepseek",
        api_base: str | None = None,
        model: str = "deepseek-chat",
        *,
        temperature: float = 0.1,
        max_tokens: int = 900,
        timeout_seconds: int = 60,
        top_p: float | None = None,
    ):
        self.api_key = os.environ.get("DEEPSEEK_API_KEY", "") if api_key is None else api_key
        self.provider = provider
        default_bases = {
            "deepseek": "https://api.deepseek.com",
            "openai": "https://api.openai.com/v1",
            "local": "http://localhost:8000/v1",
        }
        self.api_base = (api_base or default_bases.get(provider, default_bases["deepseek"])).rstrip("/")
        self.model = model
        self.temperature = float(temperature)
        self.max_tokens = int(max_tokens)
        self.timeout_seconds = int(timeout_seconds)
        self.top_p = top_p
        self.last_call_metadata: Dict[str, Any] = {}

    def generate(
        self,
        question: str,
        analysis: QueryAnalysis,
        evidence: List[Evidence],
        conversation_history: str = "",
        *,
        generation_mode: str = "constrained",
        table_format: str = "legacy",
    ) -> Tuple[str, bool]:
        self._validate_modes(generation_mode, table_format)
        if not evidence:
            self.last_call_metadata = {
                "generation_mode": generation_mode,
                "table_format": table_format,
                "api_called": False,
                "stop_reason": "no_evidence",
            }
            return "当前图谱中没有检索到能够回答该问题的证据。", False

        prompt = self._build_prompt(
            question,
            analysis,
            evidence,
            conversation_history,
            generation_mode=generation_mode,
            table_format=table_format,
        )
        system_prompt = self._system_prompt(generation_mode)
        self.last_call_metadata = {
            "generation_mode": generation_mode,
            "table_format": table_format,
            "provider": self.provider,
            "requested_model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "prompt_sha256": self._sha256(prompt),
            "system_prompt_sha256": self._sha256(system_prompt),
            "prompt_char_count": len(prompt),
            "prompt_text": prompt,
            "system_prompt_text": system_prompt,
            "api_called": False,
        }

        if self.api_key or self.provider == "local":
            answer = self._call_chat(prompt, system_prompt)
            if answer:
                return answer, True
        return self._template_answer(evidence), False

    def _build_prompt(
        self,
        question: str,
        analysis: QueryAnalysis,
        evidence: List[Evidence],
        conversation_history: str,
        *,
        generation_mode: str = "constrained",
        table_format: str = "legacy",
    ) -> str:
        self._validate_modes(generation_mode, table_format)
        evidence_text = self._serialize_evidence(evidence, table_format)[:16000]
        history = conversation_history[-2500:] if conversation_history else "无"
        header = f"""用户问题：{question}
识别意图：{analysis.intent}
目标模态：{','.join(analysis.modalities)}
对话历史：{history}

证据：
{evidence_text}
"""
        if generation_mode == "free":
            return header + """
请根据上述材料，对用户问题作出专业、自然、完整的中文回答，不要输出JSON。

请直接回答："""

        return header + """
回答规则：
1. 具体数值、时间、地点和结论只能来自证据，禁止补写证据中没有的事实。
2. 每个主要结论后标注证据编号，例如[T1]、[F1]、[E1]或[X1]。
3. 表格问题优先说明表名、相关行列和原值。
4. 图片只有图题和路径时，只能说明图片存在及位置，必须明确“尚未分析图片内部内容”。
5. 证据不足时直接说明不足，不要凭领域常识猜测。
6. 使用简洁、自然、专业的中文回答，不要输出JSON。

请直接回答："""

    def _serialize_evidence(self, evidence: List[Evidence], table_format: str) -> str:
        lines = []
        for item in evidence:
            metadata = item.metadata
            details = []
            for key in (
                "event_type", "location", "time", "trigger", "section_title",
                "page", "figure_type", "category",
            ):
                value = metadata.get(key)
                if value not in (None, "", 0):
                    details.append(f"{key}={value}")

            content = item.snippet
            if (
                item.modality == "table"
                and table_format != "legacy"
                and metadata.get("structured_rows")
            ):
                if table_format == "structured":
                    content = self._structured_table_text(metadata["structured_rows"])
                else:
                    content = self._flattened_table_text(metadata["structured_rows"])

            lines.append(
                f"[{item.evidence_id}] 类型={item.modality}；标题={item.title}；"
                f"内容={content}；元数据={'，'.join(details) or '无'}；"
                f"文件路径={item.path or '无'}"
            )
        return "\n".join(lines)

    @staticmethod
    def _structured_table_text(rows: List[Dict[str, Any]]) -> str:
        """Compactly retain row boundaries and header/raw-value/unit bindings for the structured condition."""
        row_lines: List[str] = []
        for row in rows:
            cells = []
            for cell in row.get("cells") or []:
                if not cell:
                    continue
                header = str(cell.get("header") or "未命名列")
                raw_text = str(cell.get("raw_text") or "")
                unit = str(cell.get("unit") or "")
                value = raw_text + (f" {unit}" if unit and unit not in raw_text else "")
                cells.append(f"{header}={value}")
            row_lines.append(
                f"R{row.get('row_index', '')}〈" + "｜".join(cells) + "〉"
            )
        return "\n".join(row_lines)

    @staticmethod
    def _flattened_table_text(rows: List[Dict[str, Any]]) -> str:
        """Retain the same cell tokens while removing explicit row/column structure and binding delimiters."""
        tokens: List[str] = []
        for row in rows:
            for cell in row.get("cells") or []:
                if not cell:
                    continue
                header = str(cell.get("header") or "").strip()
                raw_text = str(cell.get("raw_text") or "").strip()
                unit = str(cell.get("unit") or "").strip()
                if header:
                    tokens.append(header)
                if raw_text:
                    tokens.append(raw_text)
                if unit and unit not in raw_text:
                    tokens.append(unit)
        return " ".join(tokens)

    @staticmethod
    def _system_prompt(generation_mode: str) -> str:
        if generation_mode == "free":
            return "你是滑坡勘查报告问答助手，请专业、完整地回答用户问题。"
        return "你只能依据提供的知识图谱证据回答，并为结论标注证据编号。"

    def _call_chat(self, prompt: str, system_prompt: str) -> str:
        started = time.perf_counter()
        try:
            import requests

            payload: Dict[str, Any] = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }
            if self.top_p is not None:
                payload["top_p"] = self.top_p

            response = requests.post(
                f"{self.api_base}/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
            self.last_call_metadata.update({
                "api_called": True,
                "api_success": True,
                "response_model": data.get("model", ""),
                "response_id": data.get("id", ""),
                "usage": data.get("usage") or {},
                "api_elapsed_seconds": round(time.perf_counter() - started, 3),
            })
            return str(data["choices"][0]["message"]["content"]).strip()
        except Exception as exc:
            self.last_call_metadata.update({
                "api_called": True,
                "api_success": False,
                "api_elapsed_seconds": round(time.perf_counter() - started, 3),
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            })
            return ""

    def _call_deepseek(self, prompt: str) -> str:
        """Keep the method name used by legacy callers."""
        return self._call_chat(prompt, self._system_prompt("constrained"))

    @classmethod
    def _validate_modes(cls, generation_mode: str, table_format: str) -> None:
        if generation_mode not in cls.GENERATION_MODES:
            raise ValueError(f"未知回答模式：{generation_mode}")
        if table_format not in cls.TABLE_FORMATS:
            raise ValueError(f"未知表格表示：{table_format}")

    @staticmethod
    def _sha256(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _template_answer(evidence: List[Evidence]) -> str:
        lines = ["已检索到以下相关证据："]
        for item in evidence[:5]:
            lines.append(f"[{item.evidence_id}] {item.title}：{item.snippet[:260]}")
        lines.append("当前未使用大模型组织答案，以上为图谱直接检索结果。")
        return "\n".join(lines)
