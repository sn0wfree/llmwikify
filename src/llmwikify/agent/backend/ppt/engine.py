"""PPT Generator Engine - LLM-based content generation with rules engine."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from llmwikify.llm.streamable import StreamableLLMClient
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


def _bullet_to_str(item) -> str:
    """Convert an LLM bullet item (string or dict) to a plain string."""
    if isinstance(item, str):
        return item
    if isinstance(item, (int, float)):
        return str(item)
    if isinstance(item, dict):
        parts = []
        for key in ("category", "title", "label"):
            if key in item and item[key]:
                parts.append(str(item[key]))
        for key in ("description", "text", "content", "detail"):
            if key in item and item[key]:
                parts.append(str(item[key]))
        return ": ".join(parts) if parts else str(item)
    return str(item)


# ─── Prompts ──────────────────────────────────────────────────────────────
# v0.6.2.patch1: Prompt 全面升级
# - OUTLINE_PROMPT: 加 content_type 边界 + 文字质量自检（错别字 / 空话 / 标题精炼）
# - CONTENT_PROMPT: 5 段式重写（Role → 本页规格 → 类型指南 → Schema → 原则+反例+自检）
# - 关键修复: 显式列出 comparison vs bullets 边界规则（解决 two_column 渲染为空白）
# - 新增 4 个 get_*_prompt(language) helper，为 v0.6.3 英文翻译预留架构
# - 当前仅中文版（per Q6），EN 返回中文 + TODO 标记

OUTLINE_PROMPT_ZH = """你是一位资深演示文稿大纲设计师（10 年咨询/演讲经验），
为讲者设计一套"打开即用"的演示结构——讲者拿到大纲即可直接展开成内容。

═══════════════════════════════════════════════
【任务】
═══════════════════════════════════════════════
为主题《{topic}》设计 {num_slides} 张幻灯片的大纲（结构化、语义清晰）。

═══════════════════════════════════════════════
【content_type 选择指南】— 何时用哪种类型
═══════════════════════════════════════════════

1. **intro** — 演示首页（标题+副标题）
   典型场景：开场引入、主题概览
   用量：1 张（仅首页）

2. **section** — 章节过渡页（全屏强调）
   典型场景：分隔大主题（如"现在进入第二章：风险分析"）
   ⚠️ 不要列目录列表，section 是"进入新主题"的强调页

3. **bullets** — 并列要点（默认主力类型）
   典型场景：特性列表、原则列表、步骤列表
   数量：3-5 个要点
   ⚠️ 不要用 bullets 装"对比关系"，对比请用 comparison

4. **comparison** — 左右双栏对比
   典型场景：A vs B、传统 vs 现代、方案甲 vs 方案乙
   ⚠️ **何时不要用 comparison**（用 bullets 替代）：
     - 单个概念的多个方面（如"理论机制的三个维度"）→ 用 bullets
     - 多个并列要点无对比关系 → 用 bullets
     - 3 个或以上并列项 → 用 bullets

5. **data** — 数值数据图表
   典型场景：年度营收、市场份额、用户增长
   ⚠️ 仅当**有真实量化数据**时使用；否则用 bullets

6. **quote** — 真实引用/金句
   典型场景：开篇金句、章节点睛、专家观点
   ⚠️ 仅当引用真实存在时使用；否则用 bullets

7. **summary** — 总结/收尾
   用量：1 张（仅末页）
   形态：一段流畅文字（80-150 字）

═══════════════════════════════════════════════
【输出 Schema】— 严格 JSON
═══════════════════════════════════════════════

输出**纯 JSON**（不要 ``` 包裹，不要任何额外文字）：
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

═══════════════════════════════════════════════
【文字质量自检】
═══════════════════════════════════════════════
- **错别字检查**：常见错别字（撅→掘、记念→纪念、帐→账、像→象、
  的/地/得 不混用、像/象 区分）
- **删除空话**：避免"重要"、"关键"、"有效"、"非常"等无信息词
- **标题精炼**：去除"研究"、"分析"、"探讨"等冗词
  （如"资产共掘现象研究"→"资产共掘现象"）
- **description 充实**：每页 description ≥ 20 字，给内容生成留空间

═══════════════════════════════════════════════
【禁止的反模式】❌
═══════════════════════════════════════════════
❌ 首末页用 section（首末应用 intro/summary）
❌ 全本只用 bullets 一种类型
❌ 大纲页数与 {num_slides} 不一致
❌ 标题与 description 重复
❌ 用 ```json 或 ``` 包裹输出
❌ 输出 JSON 之外的任何解释文字
"""

CONTENT_PROMPT_ZH = """你是一位资深演示文稿内容设计师（10 年咨询/演讲经验），
为讲者准备"打开即用"的单页内容——讲者拿到这页不需再修改即可演讲。

═══════════════════════════════════════════════
【本页规格】
═══════════════════════════════════════════════
- 演示标题：{title}
- 当前页：第 {page_num} / {total_pages} 页
- 页标题：{slide_title}
- 页描述：{slide_description}
- 内容类型：{content_type}（**必须严格遵循**下方"类型指南"）

═══════════════════════════════════════════════
【类型指南】— 何时用 / 怎么写
═══════════════════════════════════════════════

■ intro（封面页）        → 输出 {{"subtitle": "副标题"}}
   何时用：演示首页，整本主题+副标题
   副标题长度：15-30 字

■ section（章节过渡页）  → 输出 {{"subtitle": "章节描述"}}
   何时用：分隔不同主题的全屏章节页（如"第二章 风险分析"）
   描述长度：10-30 字，**不是**目录列表

■ bullets（并列要点）    → 输出 {{"bullets": ["要点1", "要点2", ...]}}
   何时用：3-5 个**并列、对等**的要点
   数量：3-5 个（少于 3 信息密度不够；超过 5 应改用更精炼表达或拆页）
   形态：每个要点是**完整短语/短句**（不是单词堆砌）
   ✓ "高弹性架构支持快速扩容"
   ✗ "弹性"、"灵活"、"扩展"  ← 这是单词堆砌，禁用

■ comparison（左右对比）→ 输出 {{"left": {{"heading", "items"}}, "right": ...}}
   何时用：A vs B、传统 vs 现代、方案甲 vs 方案乙
   结构：left 和 right **都必须有有意义的 heading**（如"传统模式"/"AI 模式"）
   数量：每栏 2-4 个对比点
   ⚠️ 何时**不要**用 comparison（用 bullets 替代）：
     - 单个概念的多个方面（如"理论机制的三个维度"）→ 用 bullets
     - 多个并列要点无对比关系 → 用 bullets
     - 3 个或以上并列项 → 用 bullets
   ⚠️ **必须输出 left/right，禁止回退为 bullets**（前端会渲染为空白）

■ data（数据图表）       → 输出 {{"chart_type": "bar|line|pie", "chart_data": ...}}
   何时用：呈现可量化的对比/趋势/占比
   数据点：3-7 个（少于 3 用 bullets；多于 7 需聚合）
   ⚠️ 数值必须**真实合理**：
     - 百分比 0-100
     - 绝对值带单位（万元、%、人）
     - labels 与 values 数量必须一致

■ quote（引言/金句）    → 输出 {{"text": "...", "author": "..."}}
   何时用：名人名言、研究结论、关键金句
   ⚠️ **必须是真实存在的引用**，否则改用 bullets
   author 字段：人名 + 出处（如"——彼得·德鲁克《管理实践》"）

■ summary（总结收尾）    → 输出 {{"content": "..."}}
   何时用：全本收尾、关键结论
   形态：一段流畅文字（80-150 字），**不是**要点列表

═══════════════════════════════════════════════
【输出 Schema】— 严格 JSON
═══════════════════════════════════════════════

输出**纯 JSON**（不要 ``` 包裹，不要任何额外文字）：
{{
  "content_type": "{content_type}",
  "title": "<本页标题，可与 slide_title 略有不同以更精炼>",
  ...（根据 content_type 输出对应字段，参见上方"类型指南"）
}}

═══════════════════════════════════════════════
【写作原则】
═══════════════════════════════════════════════
1. **每点 ≤ 25 字**（中文）/ ≤ 12 词（英文）
2. **主动语态**："提供了高度的灵活性" → "高度灵活"
3. **删除空话**：去掉"重要"、"关键"、"有效"等无信息词
4. **平行结构**：同列表中要点语法结构一致（都是动宾或都是偏正）
5. **避免重复**：要点不复述 slide_title
6. **bullet title 可微调**：例如 slide_title="理论机制解析"可改为
   "理论机制的三大维度"（更具体）或保留原样

═══════════════════════════════════════════════
【禁止的反模式】❌
═══════════════════════════════════════════════
❌ comparison 输出为 bullets（必须输出 left/right 两字段）
❌ bullets 超过 5 项或少于 3 项
❌ bullets 中混入整段句子
❌ 引用未注明出处
❌ 数据无单位/无 labels
❌ 用 ```json 或 ``` 包裹输出
❌ 输出 JSON 之外的任何解释文字
❌ title 与 slide_title 一字不差（至少换 1-2 个字）
❌ 出现"未找到数据"等占位符

═══════════════════════════════════════════════
【输出前自检】✓
═══════════════════════════════════════════════
- [ ] JSON 语法正确（双引号、无尾逗号、无注释）
- [ ] content_type 与下方字段匹配
- [ ] 每个要点 ≤ 25 字
- [ ] comparison 的 left/right heading 都非空
- [ ] data 的 labels 和 values 数量一致
"""

# v0.6.2.patch1: research/chat outline 提示词也按升级版 content_type 指南对齐
RESEARCH_OUTLINE_PROMPT_ZH = """你是一位资深演示文稿大纲设计师（10 年咨询/演讲经验），
基于研究结果设计一套"打开即用"的演示结构。

═══════════════════════════════════════════════
【研究素材】
═══════════════════════════════════════════════
- 研究主题：{topic}
- 研究摘要：{summary}
- 关键发现：{findings}
- 来源数量：{source_count}

═══════════════════════════════════════════════
【content_type 选择指南】
═══════════════════════════════════════════════
1. intro     — 演示首页（1 张）
2. section   — 章节过渡页（强调"进入新主题"）
3. bullets   — 3-5 个并列要点（默认主力）
4. comparison — A vs B 明确对比（⚠️ 单概念多面/3+ 并列 → 用 bullets）
5. data      — 数值数据图表（仅当有真实量化数据时）
6. quote     — 真实引用（仅当引用真实存在时）
7. summary   — 总结收尾（1 张，80-150 字段落）

⚠️ 不要滥用 comparison：单个概念的多个方面、3+ 个并列项 → 用 bullets
⚠️ 不要滥用 section：列目录 → 改用 bullets

═══════════════════════════════════════════════
【输出 Schema】— 严格 JSON
═══════════════════════════════════════════════
输出**纯 JSON**（不要 ``` 包裹）：
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

═══════════════════════════════════════════════
【文字质量自检】
═══════════════════════════════════════════════
- 错别字检查（撅→掘、记念→纪念、帐→账、像→象）
- 删除空话（"重要"、"关键"、"有效"）
- 标题精炼（去除"研究"、"分析"等冗词）
- description ≥ 20 字（给内容生成留空间）

═══════════════════════════════════════════════
【禁止】❌ 首末用 section、全本仅用 bullets、标题与 description 重复
"""

CHAT_OUTLINE_PROMPT_ZH = """你是一位资深演示文稿大纲设计师（10 年咨询/演讲经验），
基于聊天对话内容设计一套"打开即用"的演示结构。

═══════════════════════════════════════════════
【对话素材】
═══════════════════════════════════════════════
- 对话主题：{topic}
- 对话摘要：{summary}
- 关键内容：{key_points}
- 消息数量：{message_count}

═══════════════════════════════════════════════
【content_type 选择指南】
═══════════════════════════════════════════════
1. intro     — 演示首页（1 张）
2. section   — 章节过渡页
3. bullets   — 3-5 个并列要点（默认主力）
4. comparison — A vs B 明确对比（⚠️ 单概念多面/3+ 并列 → 用 bullets）
5. data      — 数值数据图表（仅当有真实量化数据时）
6. quote     — 真实引用（仅当引用真实存在时）
7. summary   — 总结收尾（1 张，80-150 字段落）

⚠️ 不要滥用 comparison：单个概念的多个方面、3+ 个并列项 → 用 bullets
⚠️ 不要滥用 section：列目录 → 改用 bullets

═══════════════════════════════════════════════
【输出 Schema】— 严格 JSON
═══════════════════════════════════════════════
输出**纯 JSON**（不要 ``` 包裹）：
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

═══════════════════════════════════════════════
【文字质量自检】
═══════════════════════════════════════════════
- 错别字检查（撅→掘、记念→纪念、帐→账、像→象）
- 删除空话（"重要"、"关键"、"有效"）
- 标题精炼（去除"研究"、"分析"等冗词）
- description ≥ 20 字

═══════════════════════════════════════════════
【禁止】❌ 首末用 section、全本仅用 bullets、标题与 description 重复
"""


# ─── Prompt helpers ────────────────────────────────────────────────────────
# v0.6.2.patch1: 4 个 helper 统一支持 language 路由
# 当前仅 zh 实现，en 返回 zh + TODO 标记（per Q6 中文版优先）

_LANGUAGE_TODO_MARKER = (
    "\n\n<!-- TODO(v0.6.3): English translation pending. "
    "Currently falling back to Chinese prompt. -->\n"
)


def _select_prompt(language: str, zh_prompt: str) -> str:
    """语言路由：仅 zh 实现；en 返回中文 + TODO 标记（v0.6.3 补全）。"""
    if language == "zh":
        return zh_prompt
    return zh_prompt + _LANGUAGE_TODO_MARKER


def get_outline_prompt(language: str = "zh", **kwargs) -> str:
    """Step 1: 大纲生成提示词（topic → outline）。

    v0.6.2.patch1: 新增 language 参数；当前仅 zh 实现，en 走 TODO 标记。
    """
    return _select_prompt(language, OUTLINE_PROMPT_ZH).format(**kwargs)


def get_content_prompt(language: str = "zh", **kwargs) -> str:
    """Step 2: 逐页内容生成提示词（outline page → slide content）。

    v0.6.2.patch1: 新增 language 参数。
    """
    return _select_prompt(language, CONTENT_PROMPT_ZH).format(**kwargs)


def get_research_prompt(language: str = "zh", **kwargs) -> str:
    """Research → outline 提示词。"""
    return _select_prompt(language, RESEARCH_OUTLINE_PROMPT_ZH).format(**kwargs)


def get_chat_prompt(language: str = "zh", **kwargs) -> str:
    """Chat → outline 提示词。"""
    return _select_prompt(language, CHAT_OUTLINE_PROMPT_ZH).format(**kwargs)


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
        # v0.6.2.patch1: use helper (was: OUTLINE_PROMPT.format)
        language = getattr(request, "language", "zh") or "zh"
        prompt = get_outline_prompt(
            language=language,
            topic=request.topic,
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

    async def generate_content_stream(
        self,
        request: GenerateRequest,
        queue: Any,
        db: Any = None,
        task_id: str | None = None,
    ) -> dict:
        """Generate content with SSE events pushed to queue.

        Yields slide_start / slide_done / done / error events to *queue*
        so an SSE consumer can stream progress to the browser.
        Returns the final GenerateResponse dict.

        v0.5: If db and task_id are provided, incrementally persists
        partial slides to ppt_tasks.presentation_json after each slide_done.
        This enables reconnecting users to see partial progress.
        """
        import asyncio as _aio

        start_time = time.monotonic()
        theme = get_theme(request.theme)
        slides: List[SlideContent] = []
        total_pages = len(request.outline.pages)

        for idx, page in enumerate(request.outline.pages):
            # Notify: slide generation starting
            await queue.put({
                "type": "slide_start",
                "index": idx,
                "total": total_pages,
                "title": page.title,
            })

            try:
                slide = await self._generate_slide_content(
                    page=page,
                    title=request.outline.title,
                    total_pages=total_pages,
                    language=request.language,
                )
                slides.append(slide)

                # Notify: slide done
                await queue.put({
                    "type": "slide_done",
                    "index": idx,
                    "total": total_pages,
                    "slide": slide.model_dump(),
                })

                # v0.5: incremental DB write so reconnecting users
                # can see partial progress
                if db is not None and task_id is not None:
                    try:
                        db.set_ppt_task_partial_presentation(
                            task_id,
                            [s.model_dump() for s in slides],
                        )
                    except Exception as e:
                        logger.warning(
                            "Failed to persist partial slides for %s: %s",
                            task_id, e,
                        )
            except Exception as e:
                logger.error("Failed to generate slide %d: %s", idx + 1, e)
                await queue.put({
                    "type": "slide_error",
                    "index": idx,
                    "total": total_pages,
                    "error": str(e),
                })
                # Create a placeholder slide so presentation is still usable
                slide = SlideContent(
                    id=f"slide_{idx + 1}",
                    layout="section",
                    title=page.title,
                    content=f"[Generation failed: {e}]",
                )
                slides.append(slide)

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        presentation = Presentation(
            title=request.outline.title,
            subtitle=request.outline.subtitle,
            theme=theme,
            slides=slides,
            source={"type": "topic"},
        )

        result = GenerateResponse(
            presentation=presentation,
            model_used=self.llm.model,
            generation_time_ms=elapsed_ms,
        )

        # Notify: all slides done
        await queue.put({
            "type": "done",
            "presentation": result.model_dump(),
        })

        return result.model_dump()

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
        # v0.6.2.patch1: use helper (was: RESEARCH_OUTLINE_PROMPT.format)
        prompt = get_research_prompt(
            language="zh",  # v0.6.3: propagate from GenerateRequest
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
        # v0.6.2.patch1: use helper (was: CHAT_OUTLINE_PROMPT.format)
        prompt = get_chat_prompt(
            language="zh",  # v0.6.3: propagate from GenerateRequest
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
        # v0.6.2.patch1: use helper (was: CONTENT_PROMPT.format)
        prompt = get_content_prompt(
            language=language,
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

        # ── Normalize all LLM response fields ──

        # bullets: unwrap nested dict wrapper {"bullets": {...}} → list
        if isinstance(content_data.get("bullets"), dict):
            inner = content_data["bullets"]
            content_data["bullets"] = inner.get("bullets") or inner.get("items") or []

        # bullets: convert each item to string (handles dicts like {"category":..., "description":...})
        if isinstance(content_data.get("bullets"), list):
            content_data["bullets"] = [_bullet_to_str(b) for b in content_data["bullets"]]

        # content/text/author/image: ensure string or None
        for field in ("content", "text", "author", "image"):
            val = content_data.get(field)
            if val is not None and not isinstance(val, str):
                if isinstance(val, (dict, list)):
                    content_data[field] = None
                else:
                    content_data[field] = str(val)

        # left/right: ensure dict with heading+items
        for field in ("left", "right"):
            val = content_data.get(field)
            if isinstance(val, dict):
                if "items" in val and not isinstance(val["items"], list):
                    val["items"] = [str(val["items"])]
                if "heading" in val and not isinstance(val["heading"], str):
                    val["heading"] = str(val["heading"])
            elif val is not None:
                content_data[field] = None

        # chart_data: ensure dict with labels+values lists
        chart_data = content_data.get("chart_data")
        if chart_data is not None:
            if not isinstance(chart_data, dict):
                content_data["chart_data"] = None
            else:
                if not isinstance(chart_data.get("labels"), list):
                    chart_data["labels"] = []
                if not isinstance(chart_data.get("values"), list):
                    chart_data["values"] = []

        # Apply rules engine to determine layout
        layout = resolve_layout(page.content_type, content_data)

        # Validate and fill missing fields for the chosen layout
        content_data = validate_content_for_layout(page.content_type, layout, content_data)

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
            result = json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}\nText: {text[:500]}")
            raise ValueError(f"Invalid JSON response from LLM: {e}")

        if result is None:
            return {}
        if isinstance(result, list):
            return {"outline": result}
        return result

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
