"""PPT Generator Engine - LLM-based content generation with rules engine."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from ..adapters import StreamableLLMClient
from .rules import resolve_layout, validate_content_for_layout
from .schema import (
    CONTENT_TYPES,
    GenerateRequest,
    GenerateResponse,
    Outline,
    OutlinePage,
    OutlineRequest,
    OutlineResponse,
    Presentation,
    SlideContent,
    Theme,
)
from .themes import get_theme

logger = logging.getLogger(__name__)


# ─── Prompts ──────────────────────────────────────────────────────────────

OUTLINE_PROMPT = """你是一个专业的演示文稿大纲生成助手。
根据用户提供的主题，生成幻灯片大纲。

要求：
1. 生成 {num_slides} 张幻灯片的大纲
2. 每张幻灯片标注 content_type（语义标签）
3. 大纲逻辑清晰，结构合理
4. 适当使用不同 content_type 增加多样性

content_type 枚举：
- intro: 标题/介绍页（通常为第一页）
- section: 章节分隔页（用于划分大章节）
- bullets: 要点列表（3-5 个要点）
- comparison: 对比/对照（如 before/after、优劣对比）
- data: 数据/图表（需要量化信息支撑）
- quote: 引用/名言（权威观点、用户反馈等）
- summary: 总结/结束页（通常为最后一页）

输出 JSON 格式：
{{
  "title": "演示文稿标题",
  "subtitle": "副标题",
  "outline": [
    {{
      "page": 1,
      "content_type": "intro",
      "title": "幻灯片标题",
      "description": "简要描述这张幻灯片要讲什么"
    }}
  ]
}}
"""

CONTENT_PROMPT = """你是一个专业的演示文稿内容生成助手。
根据大纲中每张幻灯片的描述，生成具体内容。

大纲信息：
- 标题：{title}
- 当前页：第 {page_num} 页，共 {total_pages} 页
- content_type：{content_type}
- 页标题：{slide_title}
- 页描述：{slide_description}

要求：
1. 根据 content_type 生成对应格式的内容
2. 内容简洁有力，每点不超过 2 行
3. 标题层级清晰，逻辑连贯

输出 JSON 格式：
{{
  "content_type": "{content_type}",
  "title": "幻灯片标题",
  // 根据 content_type 输出对应字段：
  // intro: {{ "subtitle": "副标题" }}
  // section: {{ "subtitle": "章节描述" }}
  // bullets: {{ "bullets": ["要点1", "要点2", ...] }}
  // comparison: {{ "left": {{"heading": "...", "items": [...]}}, "right": {{"heading": "...", "items": [...]}} }}
  // data: {{ "chart_type": "bar|line|pie", "chart_data": {{"labels": [...], "values": [...]}} }}
  // quote: {{ "text": "引用内容", "author": "作者" }}
  // summary: {{ "content": "总结内容" }}
}}
"""

RESEARCH_OUTLINE_PROMPT = """基于以下研究结果，生成演示文稿大纲：

研究主题：{topic}
研究摘要：{summary}
关键发现：{findings}
来源数量：{source_count}

请将研究内容组织为结构化的大纲，每页标注 content_type。

输出 JSON 格式：
{{
  "title": "演示文稿标题",
  "subtitle": "副标题",
  "outline": [
    {{
      "page": 1,
      "content_type": "intro",
      "title": "幻灯片标题",
      "description": "简要描述这张幻灯片要讲什么"
    }}
  ]
}}
"""

CHAT_OUTLINE_PROMPT = """基于以下聊天对话内容，生成演示文稿大纲：

对话主题：{topic}
对话摘要：{summary}
关键内容：{key_points}
消息数量：{message_count}

请将对话内容组织为结构化的大纲，每页标注 content_type。

输出 JSON 格式：
{{
  "title": "演示文稿标题",
  "subtitle": "副标题",
  "outline": [
    {{
      "page": 1,
      "content_type": "intro",
      "title": "幻灯片标题",
      "description": "简要描述这张幻灯片要讲什么"
    }}
  ]
}}
"""


# ─── Engine ────────────────────────────────────────────────────────────────

class PPTEngine:
    """PPT generation engine using LLM + rules engine."""

    def __init__(self, llm: StreamableLLMClient):
        self.llm = llm

    async def generate_outline(self, request: OutlineRequest) -> OutlineResponse:
        """
        Step 1: Generate outline from topic.
        
        Args:
            request: Outline generation request
        
        Returns:
            OutlineResponse with the generated outline
        """
        start_time = time.monotonic()
        
        # Build prompt
        prompt = OUTLINE_PROMPT.format(
            num_slides=request.num_slides,
        )
        
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"请为以下主题生成 {request.num_slides} 张幻灯片的大纲：\n\n主题：{request.topic}"},
        ]
        
        # Call LLM
        response_text = await self._call_llm(messages)
        
        # Parse JSON
        outline_data = self._parse_json(response_text)
        
        # Validate and construct outline
        outline = self._validate_outline(outline_data, request.num_slides)
        
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        logger.info(f"Outline generated in {elapsed_ms}ms with {len(outline.pages)} pages")
        
        return OutlineResponse(outline=outline)

    async def generate_content(self, request: GenerateRequest) -> GenerateResponse:
        """
        Step 2: Generate content for each slide in the outline.
        
        Args:
            request: Content generation request with outline
        
        Returns:
            GenerateResponse with the complete presentation
        """
        start_time = time.monotonic()
        theme = get_theme(request.theme)
        slides: List[SlideContent] = []
        
        total_pages = len(request.outline.pages)
        
        for page in request.outline.pages:
            slide = await self._generate_slide_content(
                page=page,
                title=request.outline.title,
                total_pages=total_pages,
                language=request.language,
            )
            slides.append(slide)
        
        presentation = Presentation(
            title=request.outline.title,
            subtitle=request.outline.subtitle,
            theme=theme,
            slides=slides,
            source={"type": "topic"},
        )
        
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        
        return GenerateResponse(
            presentation=presentation,
            model_used=self.llm.model,
            generation_time_ms=elapsed_ms,
        )

    async def generate_from_research(
        self,
        topic: str,
        summary: str,
        findings: List[str],
        source_count: int,
    ) -> Outline:
        """
        Generate outline from research results.
        
        Args:
            topic: Research topic
            summary: Research summary
            findings: List of key findings
            source_count: Number of sources
        
        Returns:
            Outline based on research content
        """
        prompt = RESEARCH_OUTLINE_PROMPT.format(
            topic=topic,
            summary=summary,
            findings="\n".join(f"- {f}" for f in findings),
            source_count=source_count,
        )
        
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "请基于上述研究结果生成演示文稿大纲。"},
        ]
        
        response_text = await self._call_llm(messages)
        outline_data = self._parse_json(response_text)
        
        return self._validate_outline(outline_data, num_slides=None)

    async def generate_from_chat(
        self,
        topic: str,
        summary: str,
        key_points: List[str],
        message_count: int,
    ) -> Outline:
        """
        Generate outline from chat conversation.
        
        Args:
            topic: Chat topic
            summary: Chat summary
            key_points: List of key points from conversation
            message_count: Number of messages
        
        Returns:
            Outline based on chat content
        """
        prompt = CHAT_OUTLINE_PROMPT.format(
            topic=topic,
            summary=summary,
            key_points="\n".join(f"- {p}" for p in key_points),
            message_count=message_count,
        )
        
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "请基于上述对话内容生成演示文稿大纲。"},
        ]
        
        response_text = await self._call_llm(messages)
        outline_data = self._parse_json(response_text)
        
        return self._validate_outline(outline_data, num_slides=None)

    async def _generate_slide_content(
        self,
        page: OutlinePage,
        title: str,
        total_pages: int,
        language: str,
    ) -> SlideContent:
        """Generate content for a single slide."""
        prompt = CONTENT_PROMPT.format(
            title=title,
            page_num=page.page,
            total_pages=total_pages,
            content_type=page.content_type,
            slide_title=page.title,
            slide_description=page.description,
        )
        
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"请生成第 {page.page} 页的内容。"},
        ]
        
        response_text = await self._call_llm(messages)
        content_data = self._parse_json(response_text)
        
        # Apply rules engine to determine layout
        layout = resolve_layout(page.content_type, content_data)
        
        # Build slide content
        slide_id = f"slide_{page.page}"
        
        return SlideContent(
            id=slide_id,
            layout=layout,
            title=content_data.get("title", page.title),
            subtitle=content_data.get("subtitle"),
            content=content_data.get("content"),
            bullets=content_data.get("bullets"),
            left=content_data.get("left"),
            right=content_data.get("right"),
            chart_type=content_data.get("chart_type"),
            chart_data=content_data.get("chart_data"),
            text=content_data.get("text"),
            author=content_data.get("author"),
            image=content_data.get("image"),
        )

    async def _call_llm(self, messages: List[Dict[str, str]]) -> str:
        """Call LLM and return response text."""
        # Use sync chat in a thread to avoid blocking
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.llm.chat(messages, json_mode=True),
        )

    def _parse_json(self, text: str) -> Dict[str, Any]:
        """Parse JSON from LLM response, handling markdown code blocks."""
        # Try to extract JSON from markdown code block
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end != -1:
                text = text[start:end].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            if end != -1:
                text = text[start:end].strip()
        
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}\nText: {text[:500]}")
            raise ValueError(f"Invalid JSON response from LLM: {e}")

    def _validate_outline(
        self,
        data: Dict[str, Any],
        num_slides: Optional[int] = None,
    ) -> Outline:
        """Validate and construct outline from parsed JSON."""
        pages = []
        
        for i, page_data in enumerate(data.get("outline", []), 1):
            content_type = page_data.get("content_type", "bullets")
            
            # Validate content_type
            if content_type not in CONTENT_TYPES:
                content_type = "bullets"  # Default fallback
            
            page = OutlinePage(
                page=i,
                content_type=content_type,
                title=page_data.get("title", f"Page {i}"),
                description=page_data.get("description", ""),
            )
            pages.append(page)
        
        # Limit to num_slides if specified
        if num_slides and len(pages) > num_slides:
            pages = pages[:num_slides]
        
        # Ensure at least one page
        if not pages:
            pages = [OutlinePage(
                page=1,
                content_type="intro",
                title=data.get("title", "Untitled Presentation"),
                description="Presentation title slide",
            )]
        
        return Outline(
            title=data.get("title", "Untitled Presentation"),
            subtitle=data.get("subtitle"),
            pages=pages,
        )
