"""PPTChat Engine - LLM directly modifies SlideContent JSON.

Design principle: No tool definitions, no execution engine.
LLM outputs modified slides as JSON, validated by Pydantic.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator

from .schema import (
    CONTENT_TYPES,
    LAYOUT_TYPES,
    Presentation,
    SlideContent,
    Theme,
)
from .themes import get_theme, list_themes

logger = logging.getLogger(__name__)

# ─── Available context for LLM ────────────────────────────────────

CHART_TYPES = ["bar", "line", "pie", "donut", "scatter", "radar", "area", "funnel"]

LAYOUT_DESCRIPTIONS = {
    "title": "封面/标题页（居中标题+副标题）",
    "section": "章节过渡页（圆形图标+章节标题）",
    "bullets": "要点列表（3-5个要点，带圆点）",
    "title_content": "标题+正文段落",
    "two_column": "左右双栏对比（适合对比类内容）",
    "chart": "数据图表（柱状/折线/饼图等）",
    "quote": "引用/金句页（大引号+斜体文字+作者）",
    "image_text": "图片+文字（左侧图片，右侧文字说明）",
    "table": "数据表格（带表头，交替行色）",
    "timeline": "时间线（按时间排列的事件节点）",
    "kpi_grid": "关键指标仪表盘（2-4个大数字+标签）",
    "mindmap": "思维导图（中心主题+分支）",
    "process": "步骤流程（编号步骤+箭头连接）",
    "gallery": "图片画廊（2-4张图片网格）",
    "swot": "SWOT分析（四象限：优势/劣势/机会/威胁）",
}

# ─── System Prompt ────────────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """你是一个专业的PPT编辑助手。用户会用自然语言描述对演示文稿的修改需求。
你需要理解用户的意图，直接输出修改后的完整幻灯片数据（JSON格式）。

═══════════════════════════════════════════════
【当前演示文稿信息】
═══════════════════════════════════════════════
标题: {title}
主题: {theme_id}
幻灯片总数: {slide_count}

═══════════════════════════════════════════════
【可用布局类型】
═══════════════════════════════════════════════
{layout_list}

═══════════════════════════════════════════════
【可用图表类型】
═══════════════════════════════════════════════
{chart_type_list}

═══════════════════════════════════════════════
【输出格式】
═══════════════════════════════════════════════
返回一个JSON对象，包含修改后的幻灯片数组：

```json
{{
  "action": "update_slides",
  "slides": [
    {{
      "id": "slide-1",
      "layout": "chart",
      "title": "页面标题",
      "chart_type": "bar",
      "chart_data": {{
        "labels": ["Q1", "Q2", "Q3", "Q4"],
        "values": [100, 150, 130, 200]
      }}
    }}
  ],
  "message": "已完成修改：将第3页改为柱状图..."
}}
```

═══════════════════════════════════════════════
【SlideContent 字段说明】
═══════════════════════════════════════════════
- id: 字符串，唯一标识（如 "slide-1"）
- layout: 布局类型（见上方列表）
- title: 幻灯片标题（必填）
- subtitle: 副标题（用于 title/section 布局）
- content: 正文文本（用于 title_content/image_text 布局）
- bullets: 要点列表（用于 bullets 布局）
- left/right: 双栏内容（用于 two_column 布局），格式: {{"heading": "", "items": [""]}}
- chart_type: 图表类型（用于 chart 布局）
- chart_data: 图表数据，格式: {{"labels": [""], "values": [0]}}
- text: 引用文本（用于 quote 布局）
- author: 引用作者（用于 quote 布局）
- events: 时间线事件（用于 timeline 布局），格式: [{{"date": "", "title": "", "description": ""}}]
- kpi_items: KPI指标（用于 kpi_grid 布局），格式: [{{"label": "", "value": "", "trend": ""}}]
- central_topic: 中心主题（用于 mindmap 布局）
- branches: 分支（用于 mindmap 布局），格式: [{{"name": "", "children": [{{"name": ""}}]}}]
- steps: 步骤（用于 process 布局），格式: [{{"title": "", "description": ""}}]
- images: 图片列表（用于 gallery 布局），格式: [{{"url": "", "caption": ""}}]
- swot: SWOT数据（用于 swot 布局），格式: {{"strengths": [""], "weaknesses": [""], "opportunities": [""], "threats": [""]}}
- table_headers: 表头（用于 table 布局）
- table_rows: 表格数据（用于 table 布局），格式: [[""]]
- html: 自定义HTML内容（仅在以上布局都无法满足需求时使用）

═══════════════════════════════════════════════
【规则】
═══════════════════════════════════════════════
1. 返回完整的 slides 数组（不是增量修改）
2. 只修改用户要求的部分，其余保持不变
3. 新增幻灯片追加到指定位置（或末尾）
4. 删除幻灯片从数组中移除
5. layout 必须是上述可用类型之一
6. chart_type 必须是上述可用图表类型之一
7. 如果用户描述模糊，选择最合理的实现
8. 在 message 字段中简要说明你做了什么修改
9. 保持主题一致性（不要突然改变风格）
10. 每个幻灯片必须有 id 和 layout 字段
11. 优先使用上述标准布局类型。只有当标准布局完全无法满足需求时，才使用 html 字段
12. 使用 html 字段时，确保 HTML 内容完整可渲染，样式使用内联 CSS
13. 【关键规则】你输出的 JSON 修改不会直接生效。用户在回复「确认」或「执行」之前，你的修改不会被应用。
14. 因此在 message 字段中：
    - 先说你要做什么修改（如「我将把第3页改为柱状图」）
    - 末尾必须加「请回复"确认"来应用修改」
    - 绝对不要用「已完成」「已修改」「已经修改」等字眼"""

class PPTChatEngine:
    """LLM-based chat engine for interactive slide editing.

    Design: LLM directly outputs modified SlideContent JSON.
    No tool definitions, no execution engine, no result parsing overhead.
    """

    def __init__(self, llm: Any):
        self.llm = llm

    def _build_system_prompt(
        self,
        presentation: Presentation,
        current_slide_index: int,
    ) -> str:
        """Build context-aware system prompt."""
        layout_list = "\n".join(
            f"  - {lt}: {desc}" for lt, desc in LAYOUT_DESCRIPTIONS.items()
        )
        chart_list = ", ".join(CHART_TYPES)

        return SYSTEM_PROMPT_TEMPLATE.format(
            title=presentation.title,
            theme_id=presentation.theme.id,
            slide_count=len(presentation.slides),
            layout_list=layout_list,
            chart_type_list=chart_list,
        )

    def _build_user_context(
        self,
        message: str,
        presentation: Presentation,
        current_slide_index: int,
    ) -> str:
        """Build user message with slide context."""
        current_slide = None
        if 0 <= current_slide_index < len(presentation.slides):
            current_slide = presentation.slides[current_slide_index]

        outline_summary = [
            {"index": i, "layout": s.layout, "title": s.title}
            for i, s in enumerate(presentation.slides)
        ]

        context = {
            "user_request": message,
            "current_slide_index": current_slide_index,
            "current_slide": current_slide.model_dump() if current_slide else None,
            "outline_summary": outline_summary,
        }

        return json.dumps(context, ensure_ascii=False, indent=2)

    async def chat(
        self,
        message: str,
        presentation: Presentation,
        current_slide_index: int,
        history: list[dict | None] = None,
    ) -> AsyncGenerator[dict, None]:
        """Process chat message and yield events.

        Events:
          - thinking: LLM reasoning tokens
          - message_delta: incremental response text
          - done: {updated_presentation, message}
          - error: {error}
        """
        system_prompt = self._build_system_prompt(presentation, current_slide_index)
        user_context = self._build_user_context(
            message, presentation, current_slide_index
        )

        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]

        if history:
            for h in history[-5:]:
                messages.append({"role": h["role"], "content": h["content"]})

        messages.append({"role": "user", "content": user_context})

        full_response = ""
        async for event in self.llm.astream_chat(messages):
            event_type = event.get("type")

            if event_type == "thinking":
                yield {"type": "thinking", "content": event.get("text", "")}

            elif event_type == "content":
                token = event.get("text", "")
                full_response += token
                yield {"type": "message_delta", "content": token}

            elif event_type == "done":
                updated_presentation = self._apply_changes(
                    full_response, presentation
                )
                if updated_presentation:
                    yield {
                        "type": "done",
                        "updated_presentation": updated_presentation.model_dump(),
                        "message": self._extract_message(full_response),
                    }
                else:
                    yield {
                        "type": "done",
                        "updated_presentation": presentation.model_dump(),
                        "message": full_response,
                    }
                return

            elif event_type == "error":
                yield {"type": "error", "error": event.get("text", "Unknown error")}
                return

        yield {
            "type": "done",
            "updated_presentation": presentation.model_dump(),
            "message": full_response or "No response from LLM",
        }

    def _apply_changes(
        self, llm_response: str, presentation: Presentation
    ) -> Presentation | None:
        """Parse LLM JSON response and apply changes to presentation."""
        try:
            data = self._parse_json(llm_response)

            if data.get("action") != "update_slides":
                logger.warning(f"Unexpected action: {data.get('action')}")
                return None

            raw_slides = data.get("slides", [])
            if not raw_slides:
                return None

            validated_slides = []
            for raw in raw_slides:
                try:
                    slide = SlideContent(**raw)
                    validated_slides.append(slide)
                except Exception as e:
                    logger.warning(f"Slide validation failed: {e}, skipping")
                    continue

            if not validated_slides:
                return None

            return Presentation(
                title=presentation.title,
                subtitle=presentation.subtitle,
                theme=presentation.theme,
                slides=validated_slides,
                source=presentation.source,
            )

        except json.JSONDecodeError as e:
            logger.error(f"LLM output is not valid JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to apply changes: {e}")
            return None

    def _parse_json(self, text: str) -> dict[str, Any]:
        """Parse JSON from LLM response, handling markdown code blocks."""
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return json.loads(text.strip())

    def _extract_message(self, llm_response: str) -> str:
        """Extract the human-readable message from LLM response."""
        try:
            data = self._parse_json(llm_response)
            return data.get("message", "修改已完成")
        except Exception:
            return "修改已完成"
