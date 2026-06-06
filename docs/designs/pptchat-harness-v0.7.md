# PPTChat Harness Engineering Design v0.7

## Overview

PPTChat is the unified interface for all PPT operations. It uses a hybrid architecture:
- **Deterministic tools** for mechanical operations (fast, no LLM needed)
- **LLM JSON engine** for fuzzy intent (needs understanding)

The LLM directly outputs modified SlideContent JSON — no tool definitions, no execution engine overhead.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    PPTChat Panel (Frontend)                  │
│                                                             │
│  ┌─────────────────┐  ┌───────────────────────────┐        │
│  │  Quick Actions   │  │  Chat Input               │        │
│  │  [Del][Move]     │  │  "把第3页改成饼图..."     │        │
│  │  [Dup][Theme]    │  │                           │        │
│  │  [Undo][Layout]  │  │                           │        │
│  └────────┬────────┘  └─────────────┬─────────────┘        │
│           │                         │                       │
│           ▼                         ▼                       │
│  ┌─────────────────┐  ┌───────────────────────────┐        │
│  │  Harness         │  │  ChatEngine               │        │
│  │  (deterministic) │  │  (LLM JSON)               │        │
│  │  <50ms response  │  │  2-5s response            │        │
│  └─────────────────┘  └───────────────────────────┘        │
│           │                         │                       │
│           └──────────┬──────────────┘                       │
│                      ▼                                      │
│              ┌───────────────┐                              │
│              │  ChatRouter   │                              │
│              │  (unified)    │                              │
│              └───────────────┘                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 1. Deterministic Tools (ppt/harness.py)

Operations that can be solidified — no LLM needed:

| Operation | Trigger | Implementation | Latency |
|-----------|---------|----------------|---------|
| Delete slide | Button click | `deleteSlide(index)` | <10ms |
| Move slide | Drag/button | `moveSlide(from, to)` | <10ms |
| Duplicate slide | Button click | `duplicateSlide(index)` | <10ms |
| Change theme | Dropdown | `changeTheme(themeId)` | <10ms |
| Change layout | Dropdown | `changeLayout(index, layout)` | <10ms |
| Undo | Ctrl+Z/button | `undo()` | <10ms |

### SlideHarness Class

```python
class SlideHarness:
    def __init__(self, presentation: Presentation):
        self.original = presentation
        self.slides = [s.model_copy() for s in presentation.slides]
        self.history: list[list[SlideContent]] = []
    
    def delete_slide(self, index: int) -> Presentation
    def move_slide(self, from_idx: int, to_idx: int) -> Presentation
    def duplicate_slide(self, index: int) -> Presentation
    def change_theme(self, theme_id: str) -> Presentation
    def change_layout(self, index: int, new_layout: str) -> Presentation
    def undo(self) -> Presentation
```

---

## 2. LLM JSON Engine (ppt/chat_engine.py)

Handles fuzzy intent that requires understanding:

| Operation | Example | Why LLM needed |
|-----------|---------|----------------|
| Modify content | "把标题改短" | Understand "short" |
| Modify data | "Q4数据改成200" | Locate specific field |
| Add slide | "加一页总结" | Generate content |
| Change chart | "改成折线图" | Restructure chart_data |
| Batch edit | "所有标题加粗" | Iterate + judge |
| Smart suggest | "这页用什么图表好" | Analyze + reason |

### System Prompt

```
你是一个专业的PPT编辑助手。用户会用自然语言描述修改需求。
你需要直接输出修改后的完整幻灯片数据（JSON格式）。

当前演示文稿: {title}
主题: {theme_id}
幻灯片总数: {slide_count}

可用布局: title, section, bullets, title_content, two_column, chart,
         quote, image_text, table, timeline, kpi_grid, mindmap,
         process, gallery, swot

可用图表: bar, line, pie, donut, scatter, radar, area, funnel

输出格式:
{
  "action": "update_slides",
  "slides": [...修改后的完整slides数组...],
  "message": "已完成修改：..."
}

规则:
1. 返回完整 slides 数组（不是增量）
2. 只修改用户要求的部分
3. layout/chart_type 必须是上述合法值
4. message 简要说明修改内容
```

### Context Control (~500 tokens)

```
System Prompt (fixed):
  - Role definition
  - 15 layout descriptions
  - 8 chart_type descriptions
  - JSON output schema

Context (per request):
  - Current slide (full JSON)      ~200 tokens
  - Outline summary (titles only)  ~100 tokens
  - Theme ID                       ~10 tokens
  - User message                   ~50 tokens

Total: ~360-500 tokens
```

---

## 3. Unified Router (ppt/chat_router.py)

Routes user input: try deterministic first, fallback to LLM.

```python
class PPTChatRouter:
    PATTERNS = {
        r"删除(?:第|这)(\d+)(?:页|张)": "delete_slide",
        r"移动第(\d+)页到第(\d+)": "move_slide",
        r"复制(?:第|这)(\d+)(?:页|张)": "duplicate_slide",
        r"撤销|回退|上一步": "undo",
    }
    
    async def route(self, message, context):
        # 1. Try deterministic match
        for pattern, tool in self.PATTERNS.items():
            match = re.search(pattern, message)
            if match:
                return "deterministic", self._execute(tool, match, context)
        
        # 2. Fallback to LLM
        return "llm", await self._execute_llm(message, context)
```

---

## 4. SSE Events

```typescript
type PPTChatStreamEvent =
  | { type: 'session_created'; session_id: string }
  | { type: 'thinking'; content: string }
  | { type: 'message_delta'; content: string }
  | { type: 'tool_start'; tool: string; args: dict }      // deterministic
  | { type: 'tool_end'; tool: string; result: dict }       // deterministic
  | { type: 'done'; updated_presentation: Presentation; message: string }
  | { type: 'error'; error: string }
```

---

## 5. DB Schema

```sql
CREATE TABLE ppt_chat_sessions (
    id TEXT PRIMARY KEY,
    ppt_task_id TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE ppt_chat_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,          -- 'user' | 'assistant'
    content TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
```

---

## 6. File清单

| File | Purpose | Type |
|------|---------|------|
| `ppt/harness.py` | Deterministic slide operations | NEW |
| `ppt/chat_engine.py` | LLM JSON engine | NEW |
| `ppt/chat_router.py` | Unified message router | NEW |
| `ppt/chat_routes.py` | SSE streaming endpoint | NEW |
| `db.py` | Add ppt_chat_sessions + ppt_chat_messages | MODIFY |
| `ppt/__init__.py` | Export new modules | MODIFY |
| `routes/ppt.py` | Register chat routes | MODIFY |
| `PPTChatPanel.tsx` | Chat + quick actions UI | NEW |
| `ppt-api.ts` | SSE streaming functions | MODIFY |
| `PPTGenerator.tsx` | Integrate PPTChatPanel | MODIFY |

---

## 7. Implementation Order

1. `ppt/harness.py` — deterministic tools
2. `ppt/chat_engine.py` — LLM JSON engine
3. `ppt/chat_router.py` — unified router
4. `db.py` — schema + CRUD
5. `ppt/chat_routes.py` — SSE endpoint
6. `ppt/__init__.py` + `routes/ppt.py` — registration
7. `PPTChatPanel.tsx` — frontend
8. `ppt-api.ts` + `PPTGenerator.tsx` — integration
9. Tests + Build + Commit
