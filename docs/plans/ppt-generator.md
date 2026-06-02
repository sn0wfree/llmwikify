# PPT Generator — 设计规划文档

> 日期: 2026-06-02 | 版本: v0.4 | 状态: 规划中

## 〇、业界调研

### 四种主流架构模式

| 模式 | 代表产品 | 核心思路 | 优点 | 缺点 |
|------|---------|---------|------|------|
| **A. 图片原生** | Gamma, banana-slides | LLM → 大纲 → 图片生成 → 图片幻灯片 | 视觉惊艳 | 不可编辑 |
| **B. 模板合并** | GordenPPTSkill, md2pptx | LLM → JSON → 预制模板填充 → PPTX | 可编辑，质量稳定 | 模板受限 |
| **C. 编辑代理** | PPTAgent | LLM → 分析参考模板 → 编辑操作 → 沙箱渲染 | 可复刻任意风格 | 复杂度高 |
| **D. 全栈 Web** | presentation-ai, Beautiful.ai | LLM → JSON → Web 渲染器 → PPTX 导出 | UX 最佳 | JS 依赖 |

### 商业产品技术对比

| 产品 | LLM | 布局引擎 | 渲染方式 | PPTX 导出 |
|------|-----|---------|---------|----------|
| **Kimi/AiPPT** | Kimi K2.6 + Agent Swarm | **AiPPT 引擎**（200k+ 模板） | 分块渲染，原生组件 | ✅ 可编辑 |
| **Gamma** | GPT-4/Claude | 响应式卡片系统 | React/HTML | ⚠️ 有损 |
| **Beautiful.ai** | Claude | **约束求解器**（300+布局规则） | 自定义 Web 渲染器 | ✅ 可编辑 |
| **Tome** | GPT-4 + DALL-E | 叙事块 | React/DOM | ✅ 可编辑 |
| **Canva** | 自研模型 | 模板匹配 | Canvas/WebGL | ✅ 可编辑 |
| **Copilot/PPT** | Azure GPT-4 | PowerPoint 原生布局 | Office.js API | ✅ 原生 |
| **SlidesAI** | 未公开 | 模板映射 | Google Slides API | ✅ 原生 |

### Kimi PPT 深度分析

**架构：两层分离（智能层 + 渲染层）**

```
Kimi LLM (K2.6) — 智能层
  ├─ 内容理解 + 大纲生成
  ├─ Agent Swarm（300 个子代理，4000 步骤）
  ├─ 语义分类（章节/要点/对比/引用...）
  └─ 支持实时指令调整（"增加数据页"等）
          ↓ 结构化数据
AiPPT 引擎 — 渲染层
  ├─ 200,000+ 专业模板
  ├─ 布局匹配 + 渲染
  ├─ 原生组件（SWOT/甘特/KPI/漏斗/公式等）
  └─ 分块渲染（15 页 ≈ 50 秒）
```

**两种生成模式：**

| 模式 | 耗时 | 特点 |
|------|------|------|
| Adaptive（自适应） | 30-60 分钟 | 深度研究，Agent Swarm 协同，带引用 |
| Classic（经典） | 2-3 分钟 | 模板驱动，快速生成 |

**四种输入方式：**
- 文本 → 幻灯片（自然语言描述）
- 文档 → 幻灯片（PDF/Word/Excel/Markdown，保留原始结构和图片）
- 模板 → 品牌幻灯片（上传 .pptx，AI 识别 slide master）
- 图片 → 幻灯片（照片/截图 → AI 重建布局和视觉风格）

**设计特点：**
- 原生组件：图表是可编辑的原生组件，不是静态图片
- F 型阅读流：布局遵循 F 型视觉流设计
- HSL 色彩系统：实时调色，支持企业品牌色
- 行业垂直模板：金融/教育/医疗等领域专用模板
- 支持图表：SWOT、五力模型、甘特图、KPI 进度条、销售漏斗、LaTeX 公式、散点图

### 开源项目技术分析

| 项目 | Stars | 关键创新 | PPTX 方式 | 可编辑性 |
|------|-------|---------|----------|---------|
| **PPTAgent** | 4.5k | 自研 9B 微调模型 + 编辑式生成 | Playwright 渲染 HTML → PPTX | ✅ |
| **banana-slides** | 14.8k | "Vibe PPT" — 图片原生，视觉惊艳 | 图片作为幻灯片背景 | ⚠️ 有限 |
| **presentation-ai** | 2.8k | 最完整 Web 应用，38 主题 | 客户端 JS 生成 | ✅ |
| **GordenPPTSkill** | 1.5k | Agent Skill 模式，17 套中文模板 | python-pptx 模板合并 | ✅ 最佳 |
| **SlideBot-AI** | 1.2k | 多模态输入（音频/文档） | Gemini 图片生成 | ⚠️ 图片 |
| **DeepSlide** | 67 | 演讲脚本 + 幻灯片共生成 | LaTeX Beamer + PPTX | ✅ |

### 关键发现

**1. Kimi 的两层分离架构是最佳实践**

- **智能层**（Kimi LLM）：负责内容理解、大纲生成、语义分类
- **渲染层**（AiPPT）：负责模板匹配、布局渲染、格式导出
- **借鉴价值：LLM 只负责"内容是什么"，渲染引擎负责"怎么放"**

**2. Beautiful.ai 的布局引擎是核心创新**

"Smart Slides" 不是用 LLM 决定布局，而是用**约束求解器**：
- 300+ 预置布局模板
- 每个模板有确定性布局规则（如 "3 项用横排，7 项用竖排+小字"）
- LLM 只负责内容生成，布局由规则引擎决定
- **借鉴价值：用规则决定布局，不依赖 LLM 的不确定性**

**3. GordenPPTSkill 的模板合并最务实**

- 预制精美模板（保证设计质量）
- LLM 生成 JSON（标题、要点、布局类型）
- `build_pptx.py` 将 JSON 合并到模板中
- 输出可直接在 PowerPoint 中编辑
- **借鉴价值：预制模板 + AI 内容填充是最佳平衡**

**4. PPTAgent 的编辑式方法最前沿**

- 分析参考 PPT 的布局结构
- 生成编辑操作（而非从零生成）
- 在沙箱中渲染，有自编辑循环
- 但需要自研微调模型，复杂度高
- **借鉴价值：可作为 Phase 4 的高级功能**

**5. 格式保真度两难**

- **Web 原生渲染**（Gamma）：设计质量最高，但 PPTX 导出有损
- **原生 API 渲染**（Copilot/SlidesAI）：PPTX 质量最高，但设计受限
- **模板合并**（GordenPPTSkill/Kimi）：平衡方案 — 模板保证设计质量，AI 负责内容

### 业界共识

```
智能层（LLM）= 内容生成者 + 语义分类者
渲染引擎 = 设计执行者（规则/模板驱动，确定性）
渲染器 = 格式转换器（JSON → PPTX/HTML）
```

**核心结论：借鉴 Kimi 的两层分离架构，LLM 负责语义分类，规则引擎负责布局映射。**

## 一、产品定位

独立于 Quick Research 的功能模块，同时与 Research 和 Chat **双向关联**。用户可以：

1. **独立使用**：输入主题 → LLM 生成内容 → 导出 .pptx
2. **从 Research 导出**：研究结果一键转为 PPT
3. **用 Research 补充**：PPT 生成过程中调用 Research 获取更多素材
4. **从 Chat 导出**：聊天对话一键转为 PPT
5. **用 Chat 补充**：PPT 生成过程中调用 Chat 获取更多内容

### 核心价值

- **零门槛**：输入主题即可生成专业 PPT
- **可编辑**：输出原生 .pptx，可在 PowerPoint/Keynote/Google Slides 中修改
- **实时预览**：所见即所得，导出前可调整内容和主题
- **浏览器端渲染**：PptxGenJS 在浏览器中直接生成 .pptx，无需后端渲染
- **双向关联**：与 Quick Research 和 Chat 互通，研究结果和聊天对话可直接转为 PPT

## 二、架构设计

### 设计原则（来自业界调研）

1. **两层分离架构** — 智能层（LLM）负责内容，渲染层负责布局（借鉴 Kimi/AiPPT）
2. **LLM 语义分类，规则引擎布局映射** — LLM 输出 content_type，规则引擎决定 layout（方案 B）
3. **预制模板保证设计质量** — 不从零生成，模板约束视觉效果（借鉴 GordenPPTSkill）
4. **浏览器端渲染 PPTX** — PptxGenJS 直接生成，无需后端（借鉴 presentation-ai）
5. **大纲可编辑** — 用户可在生成前调整结构（借鉴 Kimi 大纲编辑）

### 2.1 方案 B：两层架构（LLM 语义分类 + 规则引擎布局映射）

**核心思路：** LLM 只输出语义标签（content_type），不直接选 layout。规则引擎将语义标签映射为最终布局。

```
┌─────────────────────────────────────────────────────────┐
│  第 1 层：LLM 语义分类（借鉴 Kimi 的智能层）             │
│                                                         │
│  Step 1: 生成大纲                                        │
│    - 用户输入主题                                        │
│    - LLM 生成大纲（每页标题 + content_type）              │
│    - 用户可编辑大纲（调整顺序、增删页面）                  │
│                                                         │
│  Step 2: 逐页生成内容                                    │
│    - LLM 按大纲逐页生成内容                              │
│    - 每页输出：content_type + 内容字段                    │
│    - content_type 枚举：                                 │
│      intro | section | bullets | comparison              │
│      | data | quote | summary                           │
│                                                         │
│  可选: Step 0 深度研究                                   │
│    - 调用 Quick Research 获取素材                        │
│    - 研究结果作为 LLM 生成的上下文                       │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│  第 2 层：规则引擎布局映射（借鉴 Kimi 的 AiPPT 引擎）    │
│                                                         │
│  输入：content_type + 内容特征                           │
│  输出：最终 layout + 布局参数                             │
│                                                         │
│  映射规则：                                              │
│  intro      → layout: "title"                           │
│  section    → layout: "section"                         │
│  bullets    → layout: "bullets" (≤5) / "two_column" (>5)│
│  comparison → layout: "two_column"                      │
│  data       → layout: "chart" (≥3 点) / "bullets" (<3)  │
│  quote      → layout: "quote"                           │
│  summary    → layout: "title_content"                   │
│                                                         │
│  Phase 4 扩展：模板驱动渲染                              │
│  - 从模板 JSON 读取样式                                  │
│  - 支持 SWOT/甘特/漏斗等原生组件                         │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│  第 3 层：渲染（借鉴 Kimi 的分块渲染）                    │
│                                                         │
│  Phase 1-3: PptxGenJS 代码驱动                          │
│  Phase 4: PptxGenJS + 模板 JSON                         │
│                                                         │
│  优化：分块渲染，逐页生成预览                             │
└─────────────────────────────────────────────────────────┘
```

### 2.2 导航入口

```
┌─ 侧边栏 ─────────────────────┐
│  Agent Chat                   │
│  Quick Research               │
│  PPT Generator        ← 新增 │
│  Tasks                        │
├───────────────────────────────┤
│  Confirmations                │
│  Dream Proposals              │
│  Dream Log                    │
│  Ingest Log                   │
│  Edit History                 │
│  LLM Settings                 │
└───────────────────────────────┘
```

**入口方式：**
- 侧边栏独立导航项（主入口）
- Quick Research 结果页 [导出为 PPT] 按钮（快捷入口）

### 2.2 双向关联

```
Quick Research ──→ PPT Generator
  研究结果页增加 [导出为 PPT] 按钮
  点击后跳转到 PPT Generator，预填研究主题和内容

PPT Generator ──→ Quick Research
  生成 PPT 前可点击 [用 Research 补充内容]
  调用 Quick Research 获取更多素材

Chat ──→ PPT Generator
  聊天对话可作为 PPT 素材来源
  点击 [导出为 PPT] 从对话生成 PPT

PPT Generator ──→ Chat
  生成 PPT 前可点击 [用 Chat 补充内容]
  调用 Chat 获取更多素材
```

### 2.3 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                       前端 (React)                           │
│                                                             │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐    │
│  │ Quick       │←→│ PPT          │←→│ Chat           │    │
│  │ Research    │  │ Generator    │  │                │    │
│  │             │  │              │  │                │    │
│  │ [导出PPT]───│──│→ [输入+预览] │  │ [素材补充]     │    │
│  │             │  │ [Research补充]│──│→              │    │
│  └─────────────┘  └──────┬───────┘  └────────────────┘    │
│                          │                                  │
│                    [导出 .pptx]                             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    后端 (FastAPI)                            │
│                                                             │
│  POST /ppt/generate         ← LLM → JSON → 布局规则        │
│  POST /ppt/from-research    ← 从 Research 结果生成 PPT      │
│  POST /ppt/from-chat        ← 从 Chat 对话生成 PPT          │
│  POST /ppt/upload-template  ← 上传 .pptx 模板（Phase 4）    │
│  GET  /ppt/templates        ← 可用模板列表（Phase 4）       │
│  GET  /ppt/themes           ← 可用主题列表                  │
└─────────────────────────────────────────────────────────────┘
```

### 2.4 数据流

**流程 1：独立使用（大纲编辑模式）**
```
用户输入主题 + 幻灯片数量 + 语言
    ↓
POST /ppt/outline → LLM 生成大纲（每页标题 + content_type）
    ↓
前端展示大纲 → 用户编辑（调整顺序、增删页面、修改标题）
    ↓
POST /ppt/generate { outline, theme, language }
    ↓
后端 LLM 按大纲逐页生成内容 → 规则引擎分配 layout
    ↓
返回前端 { slides, theme }
    ↓
React 组件实时渲染 HTML 预览
    ↓
用户调整内容 / 切换主题
    ↓
点击"导出" → PptxGenJS 生成 .pptx → 浏览器下载
```

**流程 2：从 Research 导出**
```
Quick Research 完成
    → 点击 [导出为 PPT]
    → POST /ppt/from-research { research_id }
    → 后端读取 Research 结果，提取摘要
    → LLM 生成大纲（基于研究内容）
    → 用户编辑大纲
    → LLM 按大纲逐页生成
    → 返回前端预览
    → 导出 .pptx
```

**流程 3：参考已有 Research 手动补充**

用户在 PPT Generator 中手动输入主题后，可参考已完成的 Research 结果来丰富内容。
这不是自动流程，而是用户手动操作：打开 Research 面板查看结果 → 回到 PPT Generator 补充内容。

> 注：不做 PPT → Research 的自动调用，避免循环依赖和长时间等待。

**流程 4：从 Chat 导出**
```
Chat 对话完成
    → 点击 [导出为 PPT]
    → POST /ppt/from-chat { chat_session_id }
    → 后端读取 Chat 历史，提取关键内容
    → LLM 生成大纲（基于对话内容）
    → 用户编辑大纲
    → LLM 按大纲逐页生成
    → 返回前端预览
    → 导出 .pptx
```

**流程 5：参考已有 Chat 手动补充**

用户在 PPT Generator 中手动输入主题后，可参考已完成的 Chat 对话来丰富内容。
这不是自动流程，而是用户手动操作：打开 Chat 面板查看结果 → 回到 PPT Generator 补充内容。

### 2.5 布局规则引擎（方案 B 核心：content_type → layout 映射）

```python
# ppt/rules.py — 语义类型到布局的映射，不依赖 LLM 直接选 layout

# 固定映射
TYPE_TO_LAYOUT = {
    "intro":       "title",
    "section":     "section",
    "quote":       "quote",
    "summary":     "title_content",
    "comparison":  "two_column",
}

# 动态映射（需要根据内容特征决定）
def resolve_layout(content_type: str, content: dict) -> str:
    """语义类型 + 内容特征 → 最终布局"""
    # 固定映射
    if content_type in TYPE_TO_LAYOUT:
        return TYPE_TO_LAYOUT[content_type]
    
    # bullets：根据数量决定是否分栏
    if content_type == "bullets":
        count = len(content.get("bullets", []))
        if count <= 5:
            return "bullets"
        return "two_column"  # 超过 5 项自动分栏
    
    # data：根据数据量决定是否用图表
    if content_type == "data":
        chart_data = content.get("chart_data", {})
        values = chart_data.get("values", [])
        if len(values) >= 3:
            return "chart"
        return "bullets"  # 数据点太少，用文字描述
    
    # 兜底
    return "title_content"
```

## 三、幻灯片数据模型

### 3.1 顶层结构

```typescript
interface Presentation {
  title: string;           // 演示文稿标题
  subtitle?: string;       // 副标题
  author?: string;         // 作者
  theme: ThemeConfig;      // 主题配置
  slides: Slide[];         // 幻灯片数组
  source?: {               // 来源信息（可选）
    type: 'research' | 'topic' | 'template';
    research_id?: string;  // 关联的 Research ID
  };
}
```

### 3.2 幻灯片类型

```typescript
type SlideLayout = 
  | 'title'           // 标题页
  | 'section'         // 章节分隔页
  | 'bullets'         // 标题 + 要点列表
  | 'title_content'   // 标题 + 正文段落
  | 'two_column'      // 双栏对比
  | 'chart'           // 数据图表
  | 'image_text'      // 图文混排
  | 'quote'           // 引用页
  | 'blank';          // 空白页（自由布局）

interface Slide {
  layout: SlideLayout;
  title?: string;
  // 根据 layout 不同，使用不同字段
  subtitle?: string;        // title, section
  bullets?: string[];       // bullets
  content?: string;         // title_content
  left?: ColumnContent;     // two_column
  right?: ColumnContent;    // two_column
  chart_type?: 'bar' | 'line' | 'pie';  // chart
  chart_data?: ChartData;   // chart
  image_url?: string;       // image_text
  image_position?: 'left' | 'right';  // image_text
  text?: string;            // quote
  author?: string;          // quote
  notes?: string;           // 演讲者备注
}

interface ColumnContent {
  heading?: string;
  items?: string[];
}

interface ChartData {
  labels: string[];
  values: number[];
}
```

### 3.3 主题配置

```typescript
interface ThemeConfig {
  name: string;             // 主题名称
  primary_color: string;    // 主色调
  secondary_color?: string; // 辅助色
  background: string;       // 背景色
  text_color: string;       // 文字颜色
  accent_color?: string;    // 强调色
  font_family: string;      // 字体
  slide_background?: string; // 幻灯片背景（纯色或渐变）
}
```

## 四、LLM Prompt 设计

### 4.1 大纲生成 Prompt（Step 1）

```python
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
{
  "title": "演示文稿标题",
  "subtitle": "副标题",
  "outline": [
    {
      "page": 1,
      "content_type": "intro",
      "title": "幻灯片标题",
      "description": "简要描述这张幻灯片要讲什么"
    }
  ]
}
"""
```

### 4.2 逐页内容生成 Prompt（Step 2）

```python
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
{
  "content_type": "{content_type}",
  "title": "幻灯片标题",
  // 根据 content_type 输出对应字段：
  // intro: { "subtitle": "副标题" }
  // section: { "subtitle": "章节描述" }
  // bullets: { "bullets": ["要点1", "要点2", ...] }
  // comparison: { "left": {"heading": "...", "items": [...]}, "right": {"heading": "...", "items": [...]} }
  // data: { "chart_type": "bar|line|pie", "chart_data": {"labels": [...], "values": [...]} }
  // quote: { "text": "引用内容", "author": "作者" }
  // summary: { "content": "总结内容" }
}
"""
```

### 4.3 从 Research 生成 Prompt

```python
RESEARCH_OUTLINE_PROMPT = """基于以下研究结果，生成演示文稿大纲：

研究主题：{topic}
研究摘要：{summary}
关键发现：{findings}
来源数量：{source_count}

请将研究内容组织为结构化的大纲，每页标注 content_type。
"""
```

### 4.3 JSON Schema 校验

```python
SLIDE_SCHEMA = {
    "type": "object",
    "required": ["layout", "title"],
    "properties": {
        "layout": {"type": "string", "enum": [
            "title", "section", "bullets", "title_content",
            "two_column", "chart", "image_text", "quote", "blank"
        ]},
        "title": {"type": "string"},
        "subtitle": {"type": "string"},
        "bullets": {"type": "array", "items": {"type": "string"}},
        "content": {"type": "string"},
        "left": {"$ref": "#/definitions/column"},
        "right": {"$ref": "#/definitions/column"},
        "chart_type": {"type": "string", "enum": ["bar", "line", "pie"]},
        "chart_data": {"$ref": "#/definitions/chartData"},
        "text": {"type": "string"},
        "author": {"type": "string"},
        "notes": {"type": "string"}
    }
}
```

## 五、预设主题

| # | 名称 | 风格 | 主色调 | 背景 | 字体 |
|---|------|------|--------|------|------|
| 1 | Professional | 商务简约 | #1a73e8 | #ffffff | Arial |
| 2 | Modern | 现代科技 | #6366f1 | #0f172a (渐变) | Inter |
| 3 | Minimal | 极简黑白 | #374151 | #ffffff | Helvetica |
| 4 | Nature | 自然清新 | #16a34a | #f0fdf4 | Georgia |
| 5 | Warm | 温暖活力 | #ea580c | #fff7ed | Verdana |
| 6 | Dark | 暗色主题 | #3b82f6 | #111827 | Inter |
| 7 | Academic | 学术严谨 | #dc2626 | #ffffff | Times New Roman |
| 8 | Creative | 创意设计 | #8b5cf6 | #faf5ff (渐变) | Poppins |

## 六、文件结构

```
src/llmwikify/agent/backend/
├── ppt/
│   ├── __init__.py
│   ├── engine.py              # LLM 大纲生成 + 逐页内容生成
│   ├── rules.py               # 规则引擎（content_type → layout 映射）
│   ├── themes.py              # 预设主题配置
│   ├── schema.py              # JSON Schema 定义
│   ├── profiler.py            # 模板分析器（Phase 3）
│   ├── cloner.py              # 模板克隆器（Phase 3）
│   └── templates/             # 预制模板存储（Phase 3）
├── routes/
│   └── ppt.py                 # API 路由

src/llmwikify/web/webui-agent/src/
├── components/
│   ├── PPTGenerator.tsx       # 主界面（输入 + 大纲编辑 + 预览 + 导出）
│   ├── OutlineEditor.tsx      # 大纲编辑器（拖拽排序、增删页面）
│   ├── SlidePreview.tsx       # 单页幻灯片 HTML 预览
│   ├── ThemeSelector.tsx      # 主题/模板选择器
│   ├── TemplateUploader.tsx   # 模板上传（Phase 3）
│   └── TemplateManager.tsx    # 模板管理（Phase 3）
├── lib/
│   ├── ppt-export.ts          # PptxGenJS 导出逻辑
│   ├── ppt-themes.ts          # 主题配置（前端）
│   ├── slide-renderer.tsx     # JSON → React 组件
│   └── ppt-api.ts             # API 调用封装
```

## 七、API 设计

### 7.1 POST /ppt/outline

生成大纲（Step 1）。

**请求：**
```json
{
  "topic": "量子计算的未来",
  "num_slides": 8,
  "language": "zh"
}
```

**响应：**
```json
{
  "outline": {
    "title": "量子计算的未来",
    "subtitle": "从理论到实践的突破",
    "pages": [
      {"page": 1, "content_type": "intro", "title": "量子计算的未来", "description": "标题页"},
      {"page": 2, "content_type": "bullets", "title": "什么是量子计算", "description": "基本概念和原理"},
      {"page": 3, "content_type": "comparison", "title": "量子 vs 经典", "description": "对比量子计算和经典计算"},
      {"page": 4, "content_type": "data", "title": "市场规模", "description": "量子计算市场规模数据"},
      {"page": 5, "content_type": "section", "title": "应用场景", "description": "章节分隔"},
      {"page": 6, "content_type": "bullets", "title": "行业应用", "description": "金融/医药/材料等应用"},
      {"page": 7, "content_type": "quote", "title": "专家观点", "description": "引用权威观点"},
      {"page": 8, "content_type": "summary", "title": "总结与展望", "description": "未来趋势"}
    ]
  }
}
```

### 7.2 POST /ppt/generate

按大纲逐页生成内容（Step 2）。

**请求：**
```json
{
  "outline": {
    "title": "量子计算的未来",
    "subtitle": "从理论到实践的突破",
    "pages": [...]
  },
  "theme": "professional",
  "language": "zh"
}
```

**响应：**
```json
{
  "presentation": {
    "title": "量子计算的未来",
    "subtitle": "从理论到实践的突破",
    "theme": { "name": "professional", "primary_color": "#1a73e8", ... },
    "slides": [
      {
        "id": "slide_1",
        "layout": "title",
        "title": "量子计算的未来",
        "subtitle": "从理论到实践的突破"
      },
      {
        "id": "slide_2",
        "layout": "bullets",
        "title": "什么是量子计算",
        "bullets": ["基于量子力学原理", "量子比特可同时处于 0 和 1", ...]
      }
    ],
    "source": { "type": "topic" }
  },
  "model_used": "minimax",
  "generation_time_ms": 8500
}
```

### 7.3 POST /ppt/from-research

从 Research 结果生成 PPT。

**请求：**
```json
{
  "research_id": "abc123",
  "theme": "professional",
  "language": "zh"
}
```

**响应：**
```json
{
  "outline": {
    "title": "基于研究的主题",
    "subtitle": "Quick Research 结果",
    "pages": [...]
  },
  "research_summary": "研究摘要...",
  "source_count": 15
}
```

**说明：** 返回大纲，用户编辑后再调用 `/ppt/generate`。

### 7.4 POST /ppt/from-chat

从 Chat 对话生成 PPT。

**请求：**
```json
{
  "chat_session_id": "abc123",
  "theme": "professional",
  "language": "zh"
}
```

**响应：**
```json
{
  "outline": {
    "title": "基于对话的主题",
    "subtitle": "Chat 内容",
    "pages": [...]
  },
  "chat_summary": "对话摘要...",
  "message_count": 25
}
```

**说明：** 返回大纲，用户编辑后再调用 `/ppt/generate`。

### 7.5 GET /ppt/themes

返回可用主题列表。

**响应：**
```json
{
  "themes": [
    { "name": "professional", "label": "Professional", "primary_color": "#1a73e8", "background": "#ffffff" },
    { "name": "modern", "label": "Modern", "primary_color": "#6366f1", "background": "#0f172a" }
  ]
}
```

### 7.5 POST /ppt/upload-template（Phase 3）

上传 .pptx 模板。

**请求：** `multipart/form-data` with file

**响应：**
```json
{
  "template_id": "tpl_abc123",
  "name": "用户模板",
  "layouts": ["Title Slide", "Content", "Two Column"],
  "theme": { "primary_color": "#1a73e8", "font": "Arial" }
}
```

### 7.6 GET /ppt/templates（Phase 3）

返回可用模板列表。

**响应：**
```json
{
  "templates": [
    { "id": "professional", "name": "Professional", "type": "preset", "layouts": [...] },
    { "id": "tpl_abc123", "name": "用户模板", "type": "custom", "layouts": [...] }
  ]
}
```

## 八、前端组件设计

### 8.1 PPTGenerator（主界面）

```
┌─────────────────────────────────────────────────────────────┐
│  PPT Generator                    [模板] [主题▼] [导出.pptx]│
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  输入：[量子计算的未来________________] [8张] [中文▼] │   │
│  │                          [生成大纲]                  │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  大纲编辑（点击后展开）                               │   │
│  │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐          │   │
│  │  │ 1.  │ │ 2.  │ │ 3.  │ │ 4.  │ │ 5.  │ ...      │   │
│  │  │intro│ │bulle│ │compr│ │data │ │secti│          │   │
│  │  └─────┘ └─────┘ └─────┘ └─────┘ └─────┘          │   │
│  │  [生成内容]                                          │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  缩略图栏                                            │   │
│  │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐          │   │
│  │  │ 1   │ │ 2   │ │ 3   │ │ 4   │ │ 5   │ ...      │   │
│  │  └─────┘ └─────┘ └─────┘ └─────┘ └─────┘          │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                                                     │   │
│  │              当前幻灯片大图预览                       │   │
│  │                                                     │   │
│  │   量子计算的未来                                     │   │
│  │   从理论到实践的突破                                  │   │
│  │                                                     │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  [编辑内容]  [重新生成]  [上一张] [下一张]             │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 8.2 OutlineEditor（大纲编辑器）

核心功能：
- 展示 LLM 生成的大纲（每页标题 + content_type 标签）
- 支持拖拽排序
- 支持增删页面
- 支持修改标题和 content_type
- 每个页面显示 content_type 标签（彩色 badge）

### 8.3 SlidePreview（单页预览）

将 JSON 数据渲染为 React 组件，模拟 PPT 视觉效果：

- `title` 布局：大标题居中 + 副标题
- `section` 布局：章节标题 + 分隔线
- `bullets` 布局：标题 + 要点列表（带图标）
- `two_column` 布局：左右分栏
- `chart` 布局：标题 + 柱状/饼图（CSS 绘制）
- `quote` 布局：大引号 + 引文 + 作者
- `title_content` 布局：标题 + 正文

### 8.4 ThemeSelector（主题/模板选择器）

卡片式选择，支持切换主题和模板，实时预览效果。

## 九、PptxGenJS 导出

### 9.1 核心导出逻辑

```typescript
import PptxGenJS from 'pptxgenjs';

export async function exportToPptx(
  presentation: Presentation,
  customTheme?: Partial<ThemeConfig>
): Promise<Blob> {
  const pptx = new PptxGenJS();
  const theme = { ...presentation.theme, ...customTheme };
  
  // 设置 16:9 宽屏
  pptx.defineLayout({ name: 'WIDE', width: 13.33, height: 7.5 });
  pptx.layout = 'WIDE';
  
  // 设置默认字体
  pptx.theme = { headFontFace: theme.font_family, bodyFontFace: theme.font_family };
  
  for (const slide of presentation.slides) {
    const s = pptx.addSlide();
    renderSlideToPptx(s, slide, theme);
  }
  
  const blob = await pptx.write({ outputType: 'blob' });
  return blob as Blob;
}
```

### 9.2 布局渲染映射

| 布局 | PptxGenJS 实现 |
|------|---------------|
| `title` | `addText(title, { x, y, w, h, fontSize: 36, bold: true })` + `addText(subtitle, { fontSize: 18 })` |
| `bullets` | `addText(title, { fontSize: 28 })` + `addText(bullets, { bullet: true, fontSize: 16 })` |
| `two_column` | 左右各 `addText()` + `addShape()` 分隔线 |
| `chart` | `addChart(chartType, chartData, { x, y, w, h })` |
| `quote` | `addText('❝', { fontSize: 72 })` + `addText(text, { italic: true })` |

## 九-B、模板分析与导入（Phase 3）

### 模板分析器 (ppt/profiler.py)

已有 .pptx → python-pptx 读取 → 提取 layout profile → 存储为 JSON

**核心能力：**
- 提取 slide master 和 layout 定义
- 识别每个 placeholder 的类型、位置、大小
- 提取主题颜色和字体
- 统计布局使用频率

**产出物示例：**
```json
{
  "template_name": "用户上传的模板",
  "layouts": {
    "Title Slide": {
      "placeholders": [
        {"idx": 0, "type": "TITLE", "font_size": 36},
        {"idx": 1, "type": "SUBTITLE", "font_size": 18}
      ]
    },
    "Content": {
      "placeholders": [
        {"idx": 0, "type": "TITLE"},
        {"idx": 1, "type": "BODY"}
      ]
    }
  },
  "theme": { "primary_color": "#1a73e8", "font": "Arial" }
}
```

### 模板克隆器 (ppt/cloner.py)

已有 .pptx → 清空幻灯片 → 保留 master/layout → 新幻灯片使用 layout placeholder

### 布局规则自动提取

```python
# 从多个 .pptx 提取布局规则
def extract_rules_from_pptx_folder(folder: str) -> dict:
    for pptx_file in Path(folder).glob("*.pptx"):
        prs = Presentation(pptx_file)
        for slide in prs.slides:
            features = extract_features(slide)  # 提取特征向量
            classify_layout(features)            # 分类布局类型
    
    # 统计 → 生成约束规则
    return generate_constraints(rules)
```

## 十、实现计划

### Phase 1：后端 LLM 语义分类 + 规则引擎（2-3 天）

- [ ] `ppt/schema.py` — JSON Schema 定义（大纲 + 内容）
- [ ] `ppt/themes.py` — 预设主题配置（8 套预制主题）
- [ ] `ppt/rules.py` — 规则引擎（content_type → layout 映射）
- [ ] `ppt/engine.py` — LLM prompt（大纲生成 + 逐页内容生成）+ JSON 解析
- [ ] `routes/ppt.py` — API 路由（outline, generate, from-research, themes）

### Phase 2：前端渲染 + 导出 + 导航集成（3-4 天）

**前端渲染：**
- [ ] `lib/ppt-themes.ts` — 前端主题配置
- [ ] `lib/slide-renderer.tsx` — JSON → React 组件（9 种 layout）
- [ ] `lib/ppt-export.ts` — PptxGenJS 导出
- [ ] `lib/ppt-api.ts` — API 调用封装（outline, generate, fromResearch, fromChat）

**UI 组件：**
- [ ] `components/OutlineEditor.tsx` — 大纲编辑器（拖拽排序、增删页面）
- [ ] `components/SlidePreview.tsx` — 单页预览
- [ ] `components/ThemeSelector.tsx` — 主题选择器
- [ ] `components/PPTGenerator.tsx` — 主界面

**导航集成：**
- [ ] `App.tsx` — 添加 PPT Generator 导航入口
- [ ] `ResearchPanel.tsx` — 添加 [导出为 PPT] 按钮
- [ ] `ChatPanel.tsx` — 添加 [导出为 PPT] 按钮

### Phase 3：Research 关联 + Chat 关联 + 模板系统（2-3 天）

**Research 关联：**
- [ ] `routes/ppt.py` — POST /ppt/from-research 端点
- [ ] `lib/ppt-api.ts` — fromResearch() 调用
- [ ] 手动测试：Research → PPT 完整流程

**Chat 关联：**
- [ ] `routes/ppt.py` — POST /ppt/from-chat 端点
- [ ] `lib/ppt-api.ts` — fromChat() 调用
- [ ] 手动测试：Chat → PPT 完整流程

**模板系统：**
- [ ] `ppt/profiler.py` — 模板分析器（python-pptx 提取 layout profile）
- [ ] `ppt/cloner.py` — 模板克隆器
- [ ] `ppt/templates/` — 预制模板存储
- [ ] `routes/ppt.py` — POST /ppt/upload-template, GET /ppt/templates
- [ ] `components/TemplateUploader.tsx` — 模板上传 UI
- [ ] `components/TemplateManager.tsx` — 模板管理

### Phase 4：高级功能（3-4 天）

- [ ] 原生图表组件（SWOT/甘特/漏斗/KPI）
- [ ] 模板驱动渲染（从模板 JSON 读取样式）
- [ ] 分块渲染优化（逐页生成预览）
- [ ] 手动测试：端到端生成 + 导出

### 依赖安装

```bash
# 前端
cd src/llmwikify/web/webui-agent
npm install pptxgenjs

# 后端（Phase 3 模板分析）
pip install python-pptx
```

### 预估总工时：10-14 天

## 十一、技术决策记录

| 决策 | 选择 | 理由 | 来源 |
|------|------|------|------|
| 架构模式 | 两层分离（智能层 + 渲染层） | 内容与布局职责分离 | Kimi/AiPPT |
| 布局决策 | LLM 语义分类 + 规则引擎映射 | LLM 负责"是什么"，规则负责"怎么放" | Kimi + Beautiful.ai |
| 大纲编辑 | 生成后可编辑 | 用户对内容有控制权 | Kimi |
| PPTX 渲染位置 | 浏览器端 (PptxGenJS) | 无需后端渲染，用户直接下载 | presentation-ai |
| 内容生成 | LLM 两步生成（大纲 + 逐页） | 大纲可编辑，内容更精准 | Kimi |
| 主题系统 | 预设 + 自定义（Phase 3） | 平衡易用性和灵活性 | GordenPPTSkill |
| 预览方式 | React 组件渲染 | 实时预览，所见即所得 | Gamma |
| 模板系统 | Phase 3 实现 | 先做核心功能，模板作为增强 | 设计讨论 |
| 不使用图片原生 | — | 输出不可编辑，用户体验差 | banana-slides 教训 |
| 不使用 reveal.js | — | 预览需要 PPT 效果，reveal.js 是独立演示格式 | — |
| 不使用 Pandoc | — | 设计质量受限，无法自定义主题 | — |
| 不使用编辑代理 | — | 复杂度高，需自研模型，留作 Phase 4 | PPTAgent |
