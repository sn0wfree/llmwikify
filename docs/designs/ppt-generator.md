# PPT Generator — 设计规划文档

> 日期: 2026-06-02 | 版本: v0.6.2 | 状态: v0.6.1 已完成、v0.6.2 紧凑化实施中
>
> **版本演进**：v0.1-v0.4（Phase 1-2 后端+前端）→ v0.5（任务持久化+侧边栏）→ v0.6.1（主题 8→36）→ **v0.6.2（主题选择器紧凑化）**→ v0.6.3（布局 7→31）→ ...

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

### Phase 3.5：任务持久化 + 侧边栏（v0.5 增量，~1 天）

**背景**：v0.4 上线后用户报告 frps 60s 断流导致 UI 死锁、刷新页面任务丢失。

**后端（~2h）：**
- [ ] `agent/backend/db.py` — `ppt_tasks` 表 + 8 个 CRUD 方法
- [ ] `ppt/task_manager.py` — 注入 DB，状态镜像到 DB
- [ ] `ppt/engine.py` — `slide_done` 时增量写 `presentation_json`
- [ ] `routes/ppt.py` — 加 `GET /api/ppt/tasks`、`DELETE /api/ppt/task/{id}` 端点
- [ ] `routes.py` + `core.py` — startup hook 标记重启前 running 任务为 error + 24h 清理循环

**前端（~2.5h）：**
- [ ] `lib/useUrlTask.ts` — URL hash hook（NEW）
- [ ] `lib/ppt-api.ts` — 加 `listTasks`/`getTask`/`deleteTask` + `streamPresentation` 重连 + 退避
- [ ] `components/PPTSidebar.tsx` — 侧边栏组件（NEW，仿 SessionSidebar 风格）
- [ ] `components/PPTGenerator.tsx` — 集成 sidebar 布局 + `taskId` 恢复逻辑

**测试（~30min）：**
- [ ] curl 后端测试：create → list → get → delete
- [ ] 浏览器端到端：刷新恢复、SSE 断流重连、清理 30 天任务
- [ ] 跑现有 147 个测试确保不破

**详细设计见第十二节。**

### Phase 5：主题与布局扩展（v0.6 增量，~1 周）

**背景**：v0.5 完成后视觉风格与商业产品差距大。借力 html-ppt-skill（MIT，36 主题 + 31 布局 + 47 动画 + 15 模板）提升视觉质量。

**v0.6.1 主题扩展（4-5h，~1 天）：**
- [ ] 拉取 html-ppt-skill 的 36 个 themes/*.css 到本地
- [ ] 写 `scripts/parse_themes.py` 一次性解析 CSS tokens
- [ ] `ppt/themes.py` — 8 → 36 主题定义 + Theme dataclass + 分类
- [ ] `lib/ppt-themes.ts` — 36 主题元数据 + 预览 gradient
- [ ] `components/ThemeSelector.tsx` — 分组 + 搜索
- [ ] `components/slide-renderer.tsx` — 根元素 inline style + 内部 `var(--color-*)`
- [ ] `README.md` — Credits 段（"Based on html-ppt-skill (MIT)"）
- [ ] 测试：36×7=252 组合 smoke + 147 现有测试回归

**v0.6.2 布局扩展（1-2 天）：**
- [ ] 优先翻译 10 个高价值布局：cover、toc、section-divider、kpi-grid、stat-highlight、timeline、arch-diagram、process-steps、flow-diagram、gantt
- [ ] 后续 21 个：todo、pros-cons、three-column、table、chart-*、big-quote、comparison、diff、code、terminal、roadmap、mindmap、image-hero、image-grid、cta、thanks
- [ ] LLM prompt 增加 layout 候选清单
- [ ] 测试：31 布局 × 1 主题 smoke

**v0.6.3 动画注入（4h）：**
- [ ] html-ppt-skill `assets/animations/animations.css` 27 个 CSS 动画
- [ ] `slide-renderer.tsx` 在 slide 根元素附加 `data-animate="..."` 属性
- [ ] 测试：浏览器中验证动画触发

**v0.6.5 PPTX 视觉增强（0.5 天）：**
- [ ] `lib/ppt-export.ts` 读取 theme tokens 转 PptxGenJS 颜色对象
- [ ] 测试：36 主题导出 .pptx，PowerPoint 中视觉一致

**详细设计见第十三节。**

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
| 状态所有权（v0.5） | 后端 DB 是唯一真理源，前端无持久化状态 | 避免多源数据不一致，刷新天然支持 | 架构设计原则 |
| 任务身份（v0.5） | URL hash (`#ppt/task/{id}`) | 浏览器原生支持，可分享，刷新自动恢复 | v0.5 讨论 |
| 任务持久化时机（v0.5） | 每个 slide_done 写一次 DB | reconnect 用户能看到部分内容 | v0.5 讨论 Q1=A |
| SSE 断流（v0.5） | 应用层指数退避重连（1→2→4→8s） | 解决 frps 60s 断流体验，无需改 frps | v0.5 讨论 Q2=C |
| Sidebar 数据刷新（v0.5） | 5s 轮询 | 简单可靠；未来可换 SSE 推送 | v0.5 讨论 Q3=A |
| 任务清理（v0.5） | 30 天自动清理 + server 重启标记 error | 防 DB 无限增长 | v0.5 讨论 Q2 |
| 任务列表端点（v0.5） | `GET /api/ppt/tasks?limit=50&source_type=` | 支持 sidebar 列表和按来源过滤 | API 设计 |
| 主题系统演进（v0.6.1） | 8 → 36 主题（搬运 html-ppt-skill CSS token 体系） | 借力成熟 token 系统，主题丰富度 4.5× | 业界方案对比 |
| 借鉴模式（v0.6.1） | 资产搬运（asset 移植到 LLM 管线）而非整包安装 | 保留 LLM 自动化核心价值 | v0.6 讨论 |
| 主题 token 应用（v0.6.1） | slide 根元素 inline `style={CSS variables}` + 内部 `var(--color-*)` | 一次注入，全局生效，避免 7 个布局逐个改 | 实施策略 |
| 旧主题 ID（v0.6.1） | 保留旧 8 个 ID 映射到 html-ppt-skill 同名主题，向后兼容 | 现有用户数据不破坏 | 向后兼容原则 |
| 主题归类（v0.6.1） | 按 category 分组：minimal / dark / colorful / retro / tech / brand | 36 主题需分类展示，UX 友好 | UI 设计 |
| 视觉资产归属（v0.6.1） | README 标注 "Based on html-ppt-skill (MIT, © 2026 lewislulu)" | 遵守 MIT 许可 | 法规要求 |
| 静态 HTML 导出（v0.6.x 暂缓） | v0.6.4 之前不做，先做 PPTX 视觉增强 | 用户当前更需要 PPT 体验 | v0.6 讨论 |
| 主题选择器 UX（v0.6.2） | Pill 行（6 个精选）+ 抽屉（全部 36） | 节省 82-94% 垂直空间，常用主题 1 秒可达 | 36 主题空间问题讨论 |
| 6 个默认精选主题（v0.6.2） | 硬编码 FEATURED_THEME_IDS，跨 6 category | 编辑可控、简单可靠；v0.7+ 可改算法 | UX 设计 |
| 抽屉交互（v0.6.2） | 不点外部自动收起，需显式点 "▴ 收起" | 避免浏览中误点导致抽屉消失 | 交互模式选择 |
| 抽屉内点主题后保持展开（v0.6.2） | 切换后不收起抽屉 | 用户可继续浏览找到更合适的主题 | 用户体验 |

---

## 十二、任务持久化 + 侧边栏恢复（v0.5 新增）

### 12.1 背景与问题

v0.4 上线后，用户报告两个关键问题：

**问题 A：frps 60s 断流导致 UI 死锁**

- 后端 PPT 生成 16 页深度内容耗时 70-90s
- frps `vhost_http_timeout` 默认 60s，会切断 SSE 响应
- 浏览器 `fetch().body.getReader()` 收到 `{done: true}`，但**没收到 done 事件**
- `streamPresentation` 直接退出，**`onDone` 永远不调用**
- UI 卡在 `generatingSlide=0`，无法恢复

**问题 B：刷新页面 = 任务丢失**

- 任务状态完全在 `PPTTaskManager` 内存中（5 个 dict）
- 前端只有 `task_id` 在 component state
- 刷新页面 → React 状态全清 → 用户无法回到原任务
- 即使任务已成功完成，用户也看不到结果

### 12.2 设计目标

| 目标 | 优先级 | 成功标准 |
|------|--------|----------|
| 任务历史可查 | P0 | 用户能看到所有历史任务（done/running/error） |
| 刷新后能恢复 | P0 | 刷新页面后能继续查看已完成任务 |
| 进行中任务可重连 | P0 | 刷新时若任务正在生成，能看到进度 |
| 状态所有权清晰 | P0 | 后端 DB 是唯一真理源，前端无持久化状态 |
| 任务可清理 | P1 | 30 天前的旧任务自动清理 |
| 任务可删除 | P1 | 用户可手动删除不再需要的任务 |

### 12.3 核心设计原则

> **"后端是唯一真理源，前端只是视图"**

- ❌ 前端不持有 `currentTaskId` React state
- ❌ 前端不缓存任务列表
- ❌ 前端不用 localStorage
- ✅ 任务身份在 **URL hash**（`#ppt/task/abc123`）
- ✅ 任务数据全部来自 **GET /api/ppt/task/{id}**
- ✅ 任务列表来自 **GET /api/ppt/tasks**（5s 轮询）

### 12.4 DB Schema

在 `~/.llmwikify/agent/.llmwiki_agent.db` 增加 `ppt_tasks` 表：

```sql
CREATE TABLE IF NOT EXISTS ppt_tasks (
    id TEXT PRIMARY KEY,                  -- 12-char hex UUID
    title TEXT,                           -- outline.title
    subtitle TEXT,
    theme TEXT,                           -- 'professional', 'modern', etc.
    source_type TEXT,                     -- 'topic' | 'research' | 'chat'
    source_id TEXT,                       -- 关联 research/chat ID（topic 时为 null）
    outline_json TEXT,                    -- 完整 Outline JSON
    presentation_json TEXT,               -- 渐进式更新（每个 slide_done 写一次）
    status TEXT NOT NULL,                 -- 'pending'|'running'|'done'|'error'
    error TEXT,
    slide_count INTEGER DEFAULT 0,
    model_used TEXT,
    generation_time_ms INTEGER,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ppt_tasks_updated ON ppt_tasks(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_ppt_tasks_status ON ppt_tasks(status);
```

**关键设计**：
- `presentation_json` **渐进式更新** — 每个 `slide_done` 写一次，让 reconnect 用户能看到部分内容
- `status` 是核心状态机
- `outline_json` 持久化 → 用户可重看大纲
- 30 天后自动清理（基于 `updated_at`）

### 12.5 后端 API 设计

| 方法 | 路径 | 用途 | 返回 |
|------|------|------|------|
| POST | `/api/ppt/generate` | 启动异步生成（已存在） | `{task_id, status: "processing"}` |
| GET | `/api/ppt/task/{id}` | 获取任务状态（已扩展读 DB） | `{task_id, status, presentation?, error?}` |
| GET | `/api/ppt/task/{id}/stream` | SSE 事件流（已存在） | `text/event-stream` |
| **GET** | **`/api/ppt/tasks?limit=50&source_type=research`** | **列出历史任务** | **`{tasks: [...]}`** |
| **DELETE** | **`/api/ppt/task/{id}`** | **删除任务** | **`{ok: true}`** |

**`listTasks` 响应结构**：

```typescript
interface PPTTaskSummary {
  id: string;
  title: string | null;
  subtitle: string | null;
  theme: string;
  source_type: 'topic' | 'research' | 'chat' | null;
  status: 'pending' | 'running' | 'done' | 'error';
  slide_count: number;
  model_used: string | null;
  generation_time_ms: number | null;
  error: string | null;
  created_at: string;  // ISO 8601
  updated_at: string;
}
```

### 12.6 PPTTaskManager 重构

**核心决策**：保留 asyncio.Task 在内存（必须），状态镜像到 DB。

```python
class PPTTaskManager:
    def __init__(self, db: AgentDatabase):
        self.db = db
        self._tasks: dict[str, asyncio.Task] = {}        # 保留 in-memory
        self._queues: dict[str, asyncio.Queue] = {}      # 保留 in-memory
    
    def create_task(self, generate_fn, *args, **kwargs) -> str:
        # 1. 先 DB INSERT
        task_id = self.db.create_ppt_task(...)
        # 2. 再启动 asyncio.Task
        task = asyncio.create_task(self._run_task(...))
        return task_id
    
    async def _run_task(self, task_id, generate_fn, args, kwargs, queue):
        self.db.update_ppt_task_status(task_id, 'running')
        try:
            result = await generate_fn(task_id, self.db, queue, *args, **kwargs)
            self.db.set_ppt_task_result(task_id, result)
            self.db.update_ppt_task_status(task_id, 'done')
        except Exception as e:
            self.db.update_ppt_task_status(task_id, 'error', str(e))
        finally:
            await queue.put(None)
    
    def get_status(self, task_id) -> dict:
        # 优先 DB（覆盖已完成/已错误任务）
        row = self.db.get_ppt_task(task_id)
        if row:
            return row
        # fallback in-memory（活跃任务）
        ...
```

**`engine.py` 增量写**：

```python
async def generate_content_stream(self, request, queue, db=None, task_id=None):
    slides = []
    for idx, page in enumerate(request.outline.pages):
        slide = await self._generate_slide_content(...)
        slides.append(slide)
        
        await queue.put({"type": "slide_done", "slide": slide.model_dump()})
        
        # 关键：每个 slide_done 写一次 DB
        if db and task_id:
            db.set_ppt_task_partial_presentation(
                task_id, [s.model_dump() for s in slides]
            )
```

### 12.7 前端架构

#### 12.7.1 URL hash 作为任务身份

```
http://llmwikify.frp.tokenhub.top/agent/#ppt/task/abc123
```

- ✅ 浏览器原生支持，0 成本
- ✅ 刷新自动保留
- ✅ 可分享、可书签
- ✅ 浏览器前进/后退自然工作

#### 12.7.2 `useUrlTask` Hook

```typescript
// src/lib/useUrlTask.ts
export function useUrlTask() {
  const [taskId, setTaskId] = useState<string | null>(() => {
    const m = window.location.hash.match(/^#\/ppt\/task\/([a-z0-9]+)$/);
    return m ? m[1] : null;
  });
  
  const setTask = useCallback((id: string | null) => {
    if (id) {
      window.location.hash = `#/ppt/task/${id}`;
    } else {
      history.replaceState(null, '', window.location.pathname + window.location.search);
    }
    setTaskId(id);
  }, []);
  
  useEffect(() => {
    const onHashChange = () => {
      const m = window.location.hash.match(/^#\/ppt\/task\/([a-z0-9]+)$/);
      setTaskId(m ? m[1] : null);
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);
  
  return [taskId, setTask] as const;
}
```

#### 12.7.3 PPTSidebar 组件

仿 `SessionSidebar.tsx` 风格，但**自包含**用 `useUrlTask`：

```
┌─────────────────────────────────────────────┐
│  📊 PPT 任务                          [+]  │  ← 新建（清 URL hash）
├─────────────────────────────────────────────┤
│  [全部] [主题] [研究] [对话]                  │  ← filter
├─────────────────────────────────────────────┤
│  ┌───────────────────────────────────────┐  │
│  │ ✓ 跨组合影响传导推理...           2h  │  │
│  │ 16 页 · professional · 53s            │  │
│  └───────────────────────────────────────┘  │
│  ┌───────────────────────────────────────┐  │
│  │ ⟳ 正在生成 16 页...            1m   │  │  ← 旋转图标
│  │ 进度 5/16                             │  │
│  └───────────────────────────────────────┘  │
│  ┌───────────────────────────────────────┐  │
│  │ ✗ Chat → PPT 失败              10m  │  │
│  │ ⚠ Server restarted                   │  │
│  └───────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

**轮询策略**：5s 间隔，简单可靠：

```typescript
useEffect(() => {
  let mounted = true;
  const fetchTasks = async () => {
    const { tasks } = await listTasks(50, filter === 'all' ? undefined : filter);
    if (mounted) setTasks(tasks);
  };
  fetchTasks();
  const i = setInterval(fetchTasks, 5000);
  return () => { mounted = false; clearInterval(i); };
}, [filter]);
```

#### 12.7.4 PPTGenerator 恢复流程

```typescript
// useEffect 监听 taskId 变化（URL hash 变化触发）
useEffect(() => {
  if (!taskId) {
    // 初始态：清空一切，回到 input step
    setStep('input');
    setPresentation(null);
    setOutline(null);
    return;
  }
  
  setIsLoading(true);
  getTask(taskId).then(task => {
    if (task.status === 'done' && task.presentation) {
      setPresentation(task.presentation);
      setStep('preview');
      setIsLoading(false);
    } else if (task.status === 'running') {
      // 重连 SSE
      sseControllerRef.current = streamPresentation(taskId, {
        onSlideStart, onSlideDone, onSlideError, onDone, onError
      });
    } else if (task.status === 'error') {
      setError(task.error || '任务失败');
      setIsLoading(false);
    }
  });
  
  return () => sseControllerRef.current?.abort();
}, [taskId]);
```

**`handleGenerateContent` 改动**：

```typescript
const { task_id } = await generatePresentationAsync(outline, themeName, language);
setTaskId(task_id);  // ← 写 URL hash，触发恢复逻辑
// 不再本地调 streamPresentation，由 taskId useEffect 统一管理
```

**`handleExit` 改动**：

```typescript
setTaskId(null);  // 清 URL hash
onExit();
```

### 12.8 SSE 重连策略（v0.5 新增）

**问题**：frps 60s 切断后，前端需重连继续收事件。

**方案**：指数退避重连，最多 5 次后转 `onError` 让用户手动重连。

```typescript
export function streamPresentation(taskId, callbacks): AbortController {
  let controller = new AbortController();
  let stopped = false;
  let backoff = 1000;  // 1s
  let receivedDone = false;
  
  async function connect() {
    while (!stopped && !receivedDone) {
      try {
        const response = await fetch(url, { signal: controller.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        
        const reader = response.body!.getReader();
        // 解析循环（解析到 done 时 set receivedDone = true）
        // ...
        
        backoff = 1000;  // 成功后重置
      } catch (e) {
        if (e.name === 'AbortError' || stopped) return;
        
        callbacks.onError?.({
          type: 'error',
          error: `连接中断，${backoff/1000}s 后重连...`
        });
        
        await sleep(backoff);
        backoff = Math.min(backoff * 2, 8000);  // 1→2→4→8s 上限
      }
    }
  }
  
  connect();
  return {
    abort: () => { stopped = true; controller.abort(); }
  };
}
```

**用户体验**：
- 60s 断流 → 1s 后自动重连
- 再断 → 2s → 4s → 8s
- 5 次后 → 显示"连接持续中断，请稍后查看结果"
- 用户可在 sidebar 看到 task 状态，done 后点 sidebar 重新加载

### 12.9 30 天清理策略

**位置**：FastAPI `@app.on_event("startup")` 中启动后台任务。

```python
# routes.py
@app.on_event("startup")
async def _start_ppt_cleanup():
    # 1. 标记 server 重启前的 running 任务为 error
    for row in agent_service.db.list_ppt_tasks(limit=1000):
        if row["status"] in ("pending", "running"):
            agent_service.db.update_ppt_task_status(
                row["id"], "error", "Server restarted"
            )
    
    # 2. 启动 24h 周期清理
    async def _cleanup_loop():
        while True:
            try:
                await asyncio.sleep(86400)  # 24h
                agent_service.db.cleanup_old_ppt_tasks(days=30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"PPT cleanup error: {e}")
    
    asyncio.create_task(_cleanup_loop())
```

**`core.py` shutdown 中**：cancel cleanup loop task。

### 12.10 文件改动清单

| 文件 | 类型 | 改动 |
|------|------|------|
| `agent/backend/db.py` | 改 | 加 `ppt_tasks` 表 + 8 个 CRUD 方法 |
| `ppt/task_manager.py` | 改 | 注入 DB，状态镜像 |
| `ppt/engine.py` | 改 | 增量写 `presentation_json` |
| `routes/ppt.py` | 改 | 加 list/delete 端点 |
| `routes.py` + `core.py` | 改 | startup hook + 清理 |
| `webui-agent/src/lib/useUrlTask.ts` | **NEW** | URL hash hook |
| `webui-agent/src/lib/ppt-api.ts` | 改 | 加 listTasks/getTask/deleteTask + SSE 重连 |
| `webui-agent/src/components/PPTSidebar.tsx` | **NEW** | 侧边栏组件 |
| `webui-agent/src/components/PPTGenerator.tsx` | 改 | 集成 sidebar + 恢复逻辑 |

**`App.tsx` 不动** — sidebar 内嵌在 PPTGenerator 中，状态通过 URL hash 通信。

### 12.11 风险与权衡

| 风险 | 缓解 |
|------|------|
| DB 写阻塞 event loop | sync sqlite3 ~5ms 可接受；>50 slide 任务再考虑异步化 |
| SSE 重连风暴 | 退避上限 8s，最多 5 次后转 `onError` |
| URL hash 误改 | hashchange listener 兜底；不依赖 React state 唯一性 |
| Sidebar 轮询流量 | 5s × 50 tasks × ~1KB = 10KB/s，可接受 |
| Server 重启丢失 in-progress 任务 | DB 标记为 `error: "Server restarted"`，sidebar 仍可见 |
| 30 天清理误删 | 用户可手动 export `.pptx` 备份；删除只影响 DB 记录 |

### 12.12 不在 v0.5 范围

- ❌ frps 60s 真正修复（应用层 SSE 重连已覆盖体验）
- ❌ SSE 推送 sidebar 增量更新（5s 轮询已够用）
- ❌ 任务重命名 / 标签 / 全文搜索（Phase 4）
- ❌ 任务 export 历史 / 版本管理（Phase 4）
- ❌ 多用户协作（不在 PPT Generator 路线图）

---

## 十三、主题与布局扩展（v0.6 新增）

### 13.1 背景与动机

**v0.5 现状**：8 个预设主题，7 个布局，0 动画。视觉风格与商业产品（Gamma、Kimi/AiPPT、Beautiful.ai）有显著差距。

**外部参考发现**：[html-ppt-skill](https://github.com/lewislulu/html-ppt-skill)（MIT，5.4k ⭐，507 fork）提供：
- 36 主题（CSS-token 系统）
- 31 单页布局（含 timeline、arch-diagram、kpi-grid、gantt、mindmap、process-steps…）
- 47 动画（27 CSS + 20 canvas FX）
- 15 整 deck 模板
- 演讲者模式 + 静态 HTML 导出

**核心矛盾**：html-ppt-skill 是**作者工具**（人类写大纲），我们是**LLM 生成器**（LLM 写大纲）。直接照搬会失去自动化价值。

### 13.2 借鉴模式选择

| 方案 | 内容 | 取舍 |
|------|------|------|
| A. 整包安装为 AgentSkill | `npx skills add` 注册 skill | ❌ 失去 LLM 自动化核心价值 |
| **B. 资产搬运（采用）** ⭐ | 把 `assets/themes/`、`templates/single-page/`、`assets/animations/` 移植到我们后端管线 | ✅ 保留自动化 + 视觉质量飞跃 |
| C. 静态 HTML 导出（B 延伸） | 把生成的 deck 导出为单文件 HTML | ⏸ 暂缓（用户决定先做 PPTX 增强） |

### 13.3 v0.6.x 路线图

| 版本 | 范围 | 估时 | 状态 |
|------|------|------|------|
| **v0.6.1** ⬅ 当前 | 主题 8 → 36（搬运 html-ppt-skill CSS tokens） | 4-5h | 📋 实施中 |
| v0.6.2 | 布局 7 → 31（HTML→React 翻译，优先 10 个） | 1-2 天 | ⏳ 排队 |
| v0.6.3 | 动画注入 0 → 47（CSS className 附加到 slide） | 4h | ⏳ 排队 |
| v0.6.4 | 静态 HTML 导出 + 演讲者模式 | 1 天 | ⏸ 暂停 |
| v0.6.5 | PPTX 导出视觉增强（按 html-ppt-skill 视觉风格靠拢） | 0.5 天 | ⏳ 排队 |

### 13.4 v0.6.1 主题扩展详细设计

#### 13.4.1 目标

- 8 → 36 主题，覆盖：
  - **极简**（4）：minimal-white、editorial-serif、sharp-mono、japanese-minimal
  - **柔和**（3）：soft-pastel、xiaohongshu-white、midcentury
  - **暖色**（3）：sunset-warm、retro-tv、magazine-bold
  - **冷色/科技**（5）：arctic-cool、cyberpunk-neon、blueprint、engineering-whiteprint、terminal-green
  - **暗色**（5）：catppuccin-mocha、dracula、tokyo-night、gruvbox-dark、rose-pine
  - **配色卡通风**（6）：catppuccin-latte、nord、solarized-light、memphis-pop、vaporwave、rainbow-gradient
  - **品牌/专业**（4）：corporate-clean、academic-paper、news-broadcast、pitch-deck-vc
  - **特殊设计**（6）：neo-brutalism、glassmorphism、bauhaus、swiss-grid、y2k-chrome、aurora
- 保留现有 8 个主题 ID（向后兼容），映射到 html-ppt-skill 同名/最相似主题
- 主题选择器按 category 分组，36 主题加搜索框

#### 13.4.2 主题数据模型

```python
@dataclass
class Theme:
    id: str                              # "minimal-white"
    name_zh: str                         # "极简白"
    name_en: str                         # "Minimal White"
    category: str                        # "minimal" | "dark" | "warm" | "cool" | "colorful" | "brand" | "design"
    description: str                     # 50-100 字使用场景
    tokens: dict[str, str]               # CSS custom properties 展开
    attribution: str                     # "Based on html-ppt-skill (MIT)"
```

**tokens 字段示例**（minimal-white）：
```python
tokens = {
    "color-primary": "#1a1a1a",
    "color-bg": "#ffffff",
    "color-text": "#1a1a1a",
    "color-muted": "#6b7280",
    "color-accent": "#f59e0b",
    "color-surface": "#fafafa",
    "color-border": "#e5e7eb",
    "font-heading": "Inter, 'Noto Sans SC', sans-serif",
    "font-body": "'Inter', 'Noto Sans SC', sans-serif",
    "font-mono": "'JetBrains Mono', monospace",
    "radius-sm": "4px",
    "radius-md": "8px",
    "radius-lg": "16px",
    "shadow-sm": "0 1px 2px rgba(0,0,0,0.05)",
    "shadow-md": "0 4px 6px rgba(0,0,0,0.1)",
    "shadow-lg": "0 10px 25px rgba(0,0,0,0.15)",
    "gradient-bg": "linear-gradient(135deg, #ffffff 0%, #fafafa 100%)",
}
```

#### 13.4.3 主题到 ID 映射（向后兼容）

| 旧 ID (v0.5) | 新 ID (v0.6.1) | 理由 |
|--------------|----------------|------|
| `business` | `corporate-clean` | 商务感最接近 |
| `academic` | `academic-paper` | 学术风格最匹配 |
| `tech` | `cyberpunk-neon` | 现代科技感 |
| `creative` | `memphis-pop` | 创意设计风 |
| `minimal` | `minimal-white` | 极简黑白的白底版 |
| `dark` | `dracula` | 暗色主题最热 |
| `gradient` | `aurora` | 渐变特效最匹配 |
| `custom` | (保留 user-custom 入口) | 用户自定义主题，Phase 3 实现 |

#### 13.4.4 主题应用机制

**渲染层**（`slide-renderer.tsx`）：
- 根元素：`<div className="slide-root" style={themeToStyleVars(theme)}>`
- `themeToStyleVars` 把 `tokens` dict 转为 `{'--color-primary': '#1a1a1a', ...}` inline style
- 内部元素用 `var(--color-*)`、`var(--font-*)` 等 CSS 变量引用

**收益**：
- 一次注入，全局生效
- 避免 7 个布局 × 36 主题 = 252 个组合的硬编码
- 与 html-ppt-skill 的 `assets/themes/*.css` 范式一致
- 主题切换零延迟

#### 13.4.5 主题选择器 UI

`components/ThemeSelector.tsx` 改版：
- 顶部搜索框（按 name_zh / name_en 过滤）
- 6 个 category 折叠组：
  - 极简 (4)
  - 柔和 (3)
  - 暖色 (3)
  - 冷色/科技 (5)
  - 暗色 (5)
  - 配色卡通风 (6)
  - 品牌/专业 (4)
  - 特殊设计 (6)
- 每个主题卡片：120×80 缩略图（CSS gradient 模拟）+ 名称 + category 标签

#### 13.4.6 数据流

```
用户选择主题
  ↓
前端 PPTGenerator → theme 状态
  ↓
调用 /api/ppt/generate 时 theme 提交
  ↓
后端生成大纲、内容（不变）
  ↓
返回 presentation_json + theme_id
  ↓
前端 SlideRenderer 接收 theme_id
  ↓
查 PPT_THEMES_MAP[theme_id] 拿 tokens
  ↓
inline style 注入 CSS variables
  ↓
7 个布局组件用 var(--color-*) 渲染
```

#### 13.4.7 实施步骤

1. **拉取 CSS（30min）** — `git clone` html-ppt-skill 或 curl 36 个 themes/*.css 到 `/tmp/`
2. **解析 + 归一化（30min）** — 一次性脚本 `scripts/parse_themes.py` 提取所有 CSS custom properties
3. **Theme schema（30min）** — 后端 `ppt/themes.py` 定义 Theme dataclass
4. **后端 themes.py 扩展（1h）** — 36 主题定义；8 旧 ID 映射；分类元数据
5. **前端 ppt-themes.ts（30min）** — 36 主题元数据 + 预览 gradient
6. **ThemeSelector 改版（30min）** — 分组 + 搜索
7. **slide-renderer 适配（1h）** — 根元素 inline style + 内部 `var(--color-*)`
8. **README 归属（10min）** — "Based on html-ppt-skill (MIT)" + 主题分类总览
9. **测试（30min）** — 36×7 组合 smoke + 147 现有测试回归

**总计：4-5h**

#### 13.4.8 文件改动清单

| 文件 | 类型 | 改动 | 行数 |
|------|------|------|------|
| `agent/backend/ppt/themes.py` | 改 | 8 → 36 主题，token 化 | +220 / -50 |
| `webui-agent/src/lib/ppt-themes.ts` | 改 | 8 → 36 主题元数据 | +120 / -20 |
| `webui-agent/src/components/ThemeSelector.tsx` | 改 | 分组 + 搜索 | +50 / -10 |
| `webui-agent/src/components/slide-renderer.tsx` | 改 | inline style + var(--*) | +40 / -30 |
| `webui-agent/src/components/PPTGenerator.tsx` | 改 | 透传 theme_id | +5 |
| `README.md` | 改 | Credits 段 | +5 |
| `docs/designs/ppt-generator.md` | 改 | 本节 | +200 |

#### 13.4.9 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 36 主题 CSS tokens 字段名差异大 | 中 | 写 normalize 层统一字段（`color-primary` / `color-bg` / `font-heading` 等） |
| 现有 7 布局 hardcoded colors | 中 | 重构为 `var(--color-*)`；每个布局改 ~10 处 |
| 字体未下载 | 低 | Noto Sans SC 已在 `index.html` 引入；Inter 等 webfont 在 CDN 加载 |
| 主题视觉差异过大，某些布局难看 | 低 | smoke test 过滤出明显 bad cases，标记 deprecated |
| 旧 ID 数据兼容 | 低 | 旧 8 ID 保留，重定向到新主题 |
| Bundle 体积膨胀 | 极低 | 主题 metadata +20KB，gzip 后 +5KB |

#### 13.4.10 兼容性策略

- **DB 向后兼容**：`theme` 字段（v0.5 已存）继续接受旧 8 ID；后端 lookup 时映射到新 36 主题
- **前端向后兼容**：`ppt-themes.ts` 旧 ID 仍 export，但内容指向新主题
- **API 兼容**：`GenerateRequest.theme` 接受任意字符串；不在 36 之内的回退到 `minimal-white`
- **PPTX 导出兼容**：theme tokens 直接转 PptxGenJS 颜色对象

#### 13.4.11 成功标准

- [ ] 36 主题全部定义且 ID 不重复
- [ ] 36 主题 × 7 布局 = 252 组合全部能正确渲染（无 NaN / undefined color / missing token）
- [ ] 旧 8 主题 ID 仍可使用（向后兼容）
- [ ] 主题切换无闪烁（< 50ms）
- [ ] 147 现有测试无回归
- [ ] README 含 html-ppt-skill 归属

#### 13.4.12 不在 v0.6.1 范围

- ❌ 布局扩展 7→31（v0.6.2）
- ❌ 动画注入 0→47（v0.6.3）
- ❌ 静态 HTML 导出（v0.6.4，暂缓）
- ❌ 模板系统 15 套 full-deck（v0.7+）
- ❌ 主题用户自定义（Phase 3，color picker）
- ❌ 主题混合 / 渐变映射（高级玩法）

### 13.5 v0.6.2 主题选择器紧凑化（当前）

#### 13.5.1 背景与问题

v0.6.1 上线后，ThemeSelector 占据过多垂直空间：

| 状态 | 高度 | 内容 |
|------|------|------|
| 默认（10 类全展开） | ~600-800px | 10 个 category 头 + 36 主题卡 (4 列网格) |
| 用户折叠后 | ~300px | 10 个 category 头 + 滚动区 |
| 即使折叠空 category | ~280px | 仍占 1/3 屏幕 |

**用户痛点**：36 主题数量大，但用户最常用的是 6-8 个。把所有主题一次性塞进视野，喧宾夺主，且拖慢主题切换速度。

#### 13.5.2 设计目标

- **默认收起**：只显示一行精选主题（6 个 pill）+ 切换按钮
- **一键展开**：抽屉式下拉面板，展示全部 36 主题（10 category 分组）
- **空间节省**：收起态高度 ≤ 50px（vs v0.6.1 的 280-800px）
- **响应式**：窄屏 (< 800px) pill 行横向滚动

#### 13.5.3 三种方案对比

| 方案 | 收起高度 | 优点 | 缺点 |
|------|---------|------|------|
| A. 原生 dropdown | ~40px | 最紧凑 | UI 简陌，36 项滚动累 |
| **B. Pill 行 + 抽屉（采用）** ⭐ | ~50px | 6 个常用主题一眼可见，扩展用现有 UI | 收起后看不到其他 30 个 |
| C. 图标按钮 + Popover | ~40px | 极致紧凑 | 多一次点击打断流程 |

**选择 B** 的核心理由：6 个精选 pill 足以让用户在 1 秒内感受到"我有很多主题可选"；需要切换到具体主题时，pill 提供即时切换；探索更多主题时，下拉面板提供完整浏览体验。

#### 13.5.4 UI 设计稿

**收起态**（默认，高度 ~50px）：
```
┌──────────────────────────────────────────────────────────────────┐
│ [●极简白][●德古拉][●企业清洁][●赛博朋克][●小红书白][●包豪斯]    │
│                                              [▾ 显示全部 36 个]   │
└──────────────────────────────────────────────────────────────────┘
```

**展开态**（高度 ~50 + 400px 抽屉 = 450px 总高）：
```
┌──────────────────────────────────────────────────────────────────┐
│ [●极简白][●德古拉][●企业清洁][●赛博朋克][●小红书白][●包豪斯]    │
│                                                  [▴ 收起]         │
├──────────────────────────────────────────────────────────────────┤
│ 主题 · 36                       [🔍 搜索主题...]                  │
│ 极简 / Minimal · 4                                                │
│ [▣ 极简白] [▣ 编辑衬线] [▣ 锋利单色] [▣ 日式极简]                 │
│ 柔和 / Soft · 2                                                    │
│ [▣ 柔和粉彩] [▣ 小红书白]                                          │
│ ...                                                               │
│ 复古 / Retro · 3                                                   │
│ [▣ Y2K 铬金] [▣ 复古电视] [▣ 蒸汽波]                              │
│ Themes adapted from html-ppt-skill (MIT, © 2026 lewislulu)        │
└──────────────────────────────────────────────────────────────────┘
```

#### 13.5.5 默认 6 个精选主题

按"广覆盖 + 高频用"原则，跨 6 个 category：

| # | 主题 ID | 中文 | 类别 | 选择理由 |
|---|---------|------|------|----------|
| 1 | `minimal-white` | 极简白 | minimal | 商务通用默认 |
| 2 | `dracula` | 德古拉 | dark | 暗色最热、开发者圈 |
| 3 | `corporate-clean` | 企业清洁 | brand | 商务汇报标准 |
| 4 | `cyberpunk-neon` | 赛博朋克 | tech | 科技未来感 |
| 5 | `xiaohongshu-white` | 小红书白 | soft | 生活/营销热门 |
| 6 | `bauhaus` | 包豪斯 | design | 视觉冲击、设计感 |

#### 13.5.6 数据模型

`lib/ppt-themes.ts` 新增：

```ts
export const FEATURED_THEME_IDS: string[] = [
  'minimal-white', 'dracula', 'corporate-clean',
  'cyberpunk-neon', 'xiaohongshu-white', 'bauhaus',
];

export function getFeaturedThemes(): Theme[];
```

**为什么用硬编码而非算法？**
- v0.6.2 范围小，简单可靠
- 编辑可控，主题可手动调
- v0.7+ 可改为基于使用频率的算法 + `localStorage` 记忆

#### 13.5.7 组件 API

`components/ThemeSelector.tsx` 内部新增：

```tsx
function ThemePill({ theme, selected, onClick }: {...}): JSX.Element;
// 50×24px pill：彩色圆 + 中文名

function ThemeChipCard({ theme, selected, onClick }: {...}): JSX.Element;
// 5 列网格用 chip：彩色圆 + 中文名 + 英文名
```

#### 13.5.8 状态机

```ts
type View = 'collapsed' | 'expanded' | 'searching';
const [view, setView] = useState<View>('collapsed');
const [query, setQuery] = useState('');

// 切换规则：
// - 点 pill：onSelect(id)，view 保持
// - 点 "▾ 显示全部 36 个"：view = 'expanded'
// - 点 "▴ 收起"：view = 'collapsed'
// - 搜索框输入（query.length > 0）：view = 'searching'
// - 搜索框清空：view = 'collapsed'（若之前是 searching）
```

**抽屉不点外部收起**：不加 `onBlur`/`useEffect` 监听外部点击，用户必须显式点 "▴ 收起"。理由：避免用户浏览过程中误点导致抽屉消失。

#### 13.5.9 行为细节

| 行为 | 实现 |
|------|------|
| 当前主题高亮 | `selected === theme.id` → pill/chip 加 `ring-1 ring-blue-500 bg-blue-50` |
| 当前主题不在 6 个默认里 | 抽屉展开时仍能看到并高亮；pill 行无高亮 |
| 抽屉内点主题后 | onSelect(id) → 抽屉**不收起**（用户可继续浏览） |
| 抽屉高度溢出 | 抽屉内部 `max-h-[28rem] overflow-y-auto` |
| 屏幕窄（< 800px） | pill 行 `overflow-x-auto` 横向滚动 |
| 切换主题后 | pill 行立即更新高亮（无需展开抽屉） |

#### 13.5.10 文件改动清单

| 文件 | 改动 | 行数 |
|------|------|------|
| `lib/ppt-themes.ts` | 新增 `FEATURED_THEME_IDS` + `getFeaturedThemes()` | +12 |
| `components/ThemeSelector.tsx` | 重写为 pill 行 + 抽屉 | -100 / +130 |

`components/PPTGenerator.tsx` **无需改动**（ThemeSelector API 完全兼容）。

#### 13.5.11 视觉空间对比

| 状态 | v0.6.1 高度 | v0.6.2 高度 | 节省 |
|------|-----------|-----------|------|
| 默认收起 | 280-800px | 50px | **82-94%** |
| 展开抽屉 | — | 450px | — |
| 搜索态 | 400-600px | 60-200px | 50-67% |

#### 13.5.12 风险与缓解

| 风险 | 缓解 |
|------|------|
| 6 个默认主题不讨所有用户喜欢 | 用户展开抽屉后可换；v0.6.3+ 加 `localStorage` 记忆 |
| 抽屉高度 400px 仍偏大 | 抽屉内部已 `max-h-28rem overflow-y-auto`，可滚动 |
| 屏幕宽 768px 时 pill 行过密 | 横向滚动兜底 |
| 用户预期"6 个最热门"但其实是硬编码 | 在抽屉底部标注 "Featured by editor"，未来可改为算法 |

#### 13.5.13 不在 v0.6.2 范围

- ❌ `localStorage` 记忆用户最近选的主题（v0.6.3+）
- ❌ 主题预览 tooltip（hover 显示完整描述，v0.6.3+）
- ❌ 主题推荐算法（基于使用频率，v0.7+）
- ❌ 用户自定义 featured 列表（v0.7+）
- ❌ 主题缩略图（用真实预览图替代色块，v0.7+）

### 13.6 v0.6.3 布局扩展预告

31 个布局分组：

| Category | 布局 | 优先级 |
|----------|------|--------|
| **基础** | cover、toc、section-divider、thanks、cta | 高（5/5 优先） |
| **列表** | bullets、todo-checklist、pros-cons、three-column | 高 |
| **数据** | kpi-grid、stat-highlight、table、chart-bar、chart-line、chart-pie、chart-radar | 高 |
| **流程** | flow-diagram、timeline、process-steps、gantt、roadmap、arch-diagram | 中 |
| **引用** | big-quote、comparison、diff、code、terminal | 中 |
| **创意** | mindmap、image-hero、image-grid | 低 |

**v0.6.3 优先翻译**：cover、toc、section-divider、kpi-grid、stat-highlight、timeline、arch-diagram、process-steps、flow-diagram、gantt（10 个最高价值）

### 13.7 实施顺序

```
v0.6.1 主题（8→36）          ← ✅ 已完成
  ↓ 完成 + 回归通过
v0.6.2 主题选择器紧凑化      ← ✅ 当前
  ↓ 完成 + 回归通过
v0.6.3 布局扩展（10 个高价值 + 完整 31）
  ↓ 完成 + 回归通过
v0.6.4 动画注入
  ↓ 完成 + 回归通过
v0.6.5 静态 HTML 导出（暂停中）
v0.6.6 PPTX 导出视觉增强
```

每个小版本独立 commit、独立测试、独立可演示。

