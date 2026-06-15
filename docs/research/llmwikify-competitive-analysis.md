# llmwikify 功能盘点与竞品分析

> 调研日期：2026-06-13
> 状态：竞品分析文档
> 目的：沉淀本次对项目能力、同类产品、竞品差异与战略定位的调研结论，作为后续讨论基础。

## 一、项目定位

llmwikify 是面向持久知识沉淀的 LLM Wiki 系统，不是传统一次性 RAG 问答工具。它围绕 `raw/` 原始资料、`wiki/` Markdown 页面、`wiki.md` 维护规则，构建可编辑、可审计、可复用、可迭代的长期知识资产。

当前项目已经扩展为“知识库 + 研究工作流 + 金融策略复现”的复合产品：Wiki、Graph、Agent Chat、AutoResearch、论文/研报解析、策略复现、因子分析、策略回测并存。

## 二、本项目功能全景

### 2.1 持久化 LLM Wiki 核心

| 功能 | 说明 |
|---|---|
| 原始资料管理 | `raw/` 保存不可变资料源 |
| Markdown Wiki | `wiki/` 保存 LLM 维护和人工可编辑页面 |
| 规则 schema | `wiki.md` 定义页面类型、维护规则、写作约束 |
| SQLite FTS5 搜索 | BM25 排序、snippet、高性能全文搜索 |
| 双向引用 | 自动识别 `[[wikilink]]`，维护入链/出链 |
| Query Sink | 查询答案先进入缓冲区，等待后续审核和合并 |
| Source Analysis | 对源文档抽取实体、关系、主题、建议页面 |
| Cross-source Synthesis | 多来源之间找强化证据、矛盾、知识缺口 |
| Smart Lint | 断链、孤儿页、过时页面、矛盾、冗余、知识缺口 |
| Knowledge Graph | 实体关系、邻居、最短路径、社区、Surprise Score |
| Graph Visualization | HTML、SVG、GraphML、D3/Web 图谱展示 |

核心差异：普通 RAG 每次查询临时检索上下文；llmwikify 把知识持续沉淀为 Wiki 页面、引用网络、图谱关系和可审计记录。

### 2.2 多入口产品形态

| 入口 | 功能 |
|---|---|
| CLI | 初始化、导入、搜索、lint、graph、synthesis、MCP 启动 |
| MCP Server | 给外部 Agent 暴露 Wiki 工具 |
| REST API | WebUI 和外部系统访问 Wiki/Agent/Research/Quant 能力 |
| React WebUI | 可视化编辑、图谱、洞察、Agent、研究、复现、设置 |
| Python API | 作为库嵌入其他应用 |

### 2.3 WebUI 功能地图

| 路由 | 功能 |
|---|---|
| `/edit` | Wiki 页面编辑器、页面树、frontmatter、预览、图谱 |
| `/dashboard` | 知识增长仪表盘、状态、sink、dream activity |
| `/insights` | 推荐、cross-source synthesis、graph analysis |
| `/agent/chat` | 流式 Agent Chat、工具调用、确认流、session |
| `/agent/autoresearch` | 6 步 AutoResearch 研究工作流 |
| `/agent/reproduction` | 论文/研报策略复现工作台 |
| `/agent/paper` | 论文/研报抽取到 Wiki/Factor/Strategy 页面 |
| `/agent/factor` | 因子选择、配置、IC、分组、多空分析 |
| `/agent/strategy` | 策略选择、配置、回测与结果展示 |
| `/agent/tasks` | 任务/调度监控 |
| `/agent/settings` | LLM provider、model、API key 配置 |

### 2.4 Agent / Chat / Skills

当前项目存在旧 Agent 与新 Chat/Agent 服务并存的情况。主要能力包括 SSE 流式聊天、工具调用事件、人工确认、session 管理、memory manager、skill runtime、dynamic workflow、scheduler、dream proposal、notification、wiki tool registry。

工具层覆盖 Wiki 初始化、搜索、读写、lint、source analysis、references、status、recommend、synthesis、knowledge gaps、graph analysis、ingest、save-to-wiki 等。

### 2.5 AutoResearch

AutoResearch 是项目内置的结构化研究系统，采用 6 步框架：概念澄清、建立依据、推理严密、稳固结构、结论输出、检查清单。它不是简单搜索总结，而是把研究过程显式结构化，并支持最终保存到 Wiki。

### 2.6 论文/研报到策略复现

项目最垂直、最具差异化的方向是论文/研报策略复现：

```text
论文/研报 PDF/URL/本地文件
  → 文档解析
  → 结构化研究理解
  → 提取因子/信号/参数/假设
  → 生成 Factor/Strategy Wiki 页面
  → 执行回测
  → 输出指标/图表/artifact
  → 回写 Wiki
```

该链路本质是：文档 → 知识 → 可执行策略/回测报告。

### 2.7 量化分析

| 模块 | 能力 |
|---|---|
| Paper | 论文/研报解析与结构化产物 |
| Factor | 因子定义、因子回测、IC、分层、多空 |
| Strategy | 策略定义、回测、指标、图表 |
| Reproduction | 复现 session、阶段流、artifact 管理 |
| 数据源 | ClickHouse、AKShare fallback、后续可接 iFinD |

因子分析目标模块：IC/IR、IC 时间序列、IC 分布、分层回测、多空净值、因子收益、换手率、因子衰减、因子相关性、市场状态检验。

策略分析目标模块：CAGR、Sharpe、Sortino、Max Drawdown、Win Rate、Alpha/Beta、净值曲线、水下回撤图、月度收益热力图、年度收益、VaR/CVaR、基准对比、交易统计、持仓分布、绩效归因、压力测试。

## 三、业界同类项目分层

### 3.1 通用知识库 / RAG / Agent App

| 项目 | 定位 | 主要能力 | 与 llmwikify 对比 |
|---|---|---|---|
| AnythingLLM | 本地优先 Chat with Docs + Agent 应用 | 多模型、多用户、向量库、Agent、文档聊天、MCP、桌面端 | 产品成熟度和易用性更强；但主要是 RAG/chat，不强调 Wiki 知识沉淀 |
| Dify | 可视化 AI app / agentic workflow 平台 | Workflow builder、工具集成、知识库、部署、团队协作 | 平台化和工作流编排更强；不是 Markdown Wiki 知识资产系统 |
| LlamaIndex | LLM 应用开发框架 | connectors、indexes、RAG、agents、workflows、observability | 生态和框架能力最强；llmwikify 更像面向最终用户/研究者的上层产品 |
| Microsoft GraphRAG | 图谱增强 RAG | entity/relation extraction、community hierarchy、global/local/drift search | 图谱检索理论和算法强；llmwikify 更强调可编辑 Wiki 和 human-in-loop |
| Obsidian + AI 插件 | 人工知识库 + AI 辅助 | Markdown、本地文件、插件生态、双链 | 用户自由度强；llmwikify 自动化分析和后端图谱更强 |

结论：llmwikify 不应直接和 Dify/AnythingLLM 拼通用 Agent 平台能力，而应强调“LLM-maintained Wiki + Graph + Human Review”的知识资产路线。

### 3.2 文档解析 / 论文理解

| 项目 | 定位 | 优势 | llmwikify 启示 |
|---|---|---|---|
| MarkItDown | 多格式转 Markdown | 本地轻量，PDF/Office/HTML/Audio/YouTube/ZIP 等格式覆盖广，Markdown 对 LLM 友好 | 适合作为默认解析层 |
| LlamaParse | Agentic document parsing 平台 | agentic OCR、130+ 格式、表格/图表/JSON/Extract/Classify/Split/Index | 可作为高保真增强解析后端 |
| GROBID | 学术论文结构化解析 | 标题、作者、摘要、章节、参考文献、学术结构强 | 适合英文论文结构解析 |
| Nougat | PDF 到 LaTeX 模型 | 公式和学术排版能力较强 | 适合公式密集论文补强 |
| Mathpix / Pix2Text | 公式 OCR | 公式识别能力强 | 可作为关键公式页增强 |
| PyMuPDF4LLM | 本地 PDF 到 Markdown/JSON | 快、稳、成本低 | 适合作为默认 PDF 解析层 |

推荐路线：默认用 MarkItDown / PyMuPDF4LLM；增强接 LlamaParse / GROBID / Vision LLM / Mathpix / Pix2Text；策略是本地低成本解析 + 关键页多模态补强。

### 3.3 Deep Research / 自动研究

| 项目 | 定位 | 优势 | 与 llmwikify 对比 |
|---|---|---|---|
| GPT Researcher | 开源 deep research agent | planner/executor、多源检索、引用、报告、前端、MCP、本地文档 | Web research 生态更成熟；llmwikify 胜在研究结果沉淀到 Wiki/Graph |
| OpenAI Deep Research | 商业深度研究产品 | 搜索、综合、引用、体验强 | 闭源不可控；llmwikify 可本地、可扩展、可审计 |
| STORM | 学术写作/访谈式多 Agent | 多视角提问、长文生成 | 偏写作；llmwikify 偏知识维护 |
| TradingAgents | 金融多 Agent 决策 | 分析师、研究员辩论、交易员、风控、组合经理 | 偏交易决策；llmwikify 偏研究复现与知识沉淀 |

AutoResearch 的独特价值：不是只输出报告，而是把报告、证据、结论、矛盾、待办沉淀为 Wiki 页面和图谱关系。

### 3.4 量化 / 策略 / 因子平台

| 项目 | 定位 | 优势 | 与 llmwikify 对比 |
|---|---|---|---|
| Qlib | AI 量化全链路平台 | 数据、模型、训练、回测、报告、线上 serving、AI quant workflow | 底层量化工程远强；llmwikify 更偏论文/研报理解与知识化复现 |
| RD-Agent | LLM 自动化量化 R&D | 自动因子挖掘、模型优化、实验闭环 | 是量化 R&D 自动化直接高阶竞品 |
| TradingAgents | 多 Agent 金融交易框架 | 基本面/情绪/新闻/技术分析、多空辩论、风控、决策日志 | 偏股票交易决策，不是论文复现系统 |
| backtrader | Python 事件驱动回测 | 中文生态成熟、多市场、analyzer 丰富 | 可作为 llmwikify 的回测执行层 |
| vectorbt | 向量化回测 | 高性能，适合参数扫描和大规模因子实验 | 可作为 llmwikify 的高性能回测后端 |
| Zipline | 学术派回测框架 | pipeline 思想成熟 | 生态相对旧，可参考但不宜重依赖 |

llmwikify 在量化方向的最佳定位是：研报/论文理解层 + 策略知识库 + 回测编排前端。不建议替代 Qlib/backtrader/vectorbt，而应通过适配器借力。

## 四、竞品矩阵

| 能力 | llmwikify | AnythingLLM | Dify | LlamaIndex | GraphRAG | GPT Researcher | Qlib | TradingAgents |
|---|---|---|---|---|---|---|---|---|
| Markdown Wiki | 强 | 弱 | 弱 | 弱 | 弱 | 弱 | 弱 | 弱 |
| 持久知识沉淀 | 强 | 中 | 中 | 取决于实现 | 中 | 中 | 中 | 中 |
| RAG/chat | 中 | 强 | 强 | 强 | 中 | 中 | 弱 | 中 |
| 可视化工作流 | 弱 | 中 | 强 | 弱 | 弱 | 弱 | 弱 | 弱 |
| Agent 工具调用 | 中 | 强 | 强 | 强 | 弱 | 中 | 弱 | 强 |
| Human-in-loop | 中 | 中 | 中 | 中 | 弱 | 弱 | 弱 | 中 |
| 文档解析 | 中 | 中 | 中 | 中 | 弱 | 中 | 弱 | 弱 |
| 图谱分析 | 强 | 弱 | 弱 | 中 | 强 | 弱 | 弱 | 弱 |
| Deep Research | 中 | 弱 | 中 | 中 | 弱 | 强 | 弱 | 中 |
| 金融研究 | 中 | 弱 | 弱 | 框架支持 | 弱 | 中 | 强 | 强 |
| 论文/研报策略复现 | 强潜力 | 弱 | 弱 | 需自建 | 弱 | 弱 | 中 | 弱 |
| 因子/回测 | 中 | 弱 | 弱 | 需自建 | 弱 | 弱 | 强 | 中 |
| 多用户/权限 | 弱 | 强 | 强 | 需自建 | 弱 | 中 | 弱 | 弱 |
| 部署成熟度 | 中 | 强 | 强 | 框架 | 中 | 中 | 中 | 中 |

## 五、核心竞争力与短板

### 5.1 强项

1. 持久知识复利：RAG 是一次性回答，llmwikify 是持续维护 Wiki、引用网络和知识图谱。
2. Markdown-first：可读、可 diff、可 git、可迁移，不被专用数据库或 SaaS 锁死。
3. Graph + Wiki 融合：既有人工可读页面，又有实体关系、社区、桥节点和 surprise connection。
4. Human-in-loop 设计正确：多数关键动作是建议、确认、审核，而不是直接自动覆盖。
5. MCP / CLI / Web 多入口：可作为工具、服务、Web 应用或外部 Agent 的知识后端。
6. 金融研究复现方向差异化明显：从论文/研报到因子/策略/回测/Wiki 的完整链路在竞品中较少完整覆盖。

### 5.2 弱项

1. 产品边界过宽：Wiki、Agent、Research、Quant、Paper、Reproduction 同时推进，主线容易模糊。
2. 文档解析不如专业解析平台：LlamaParse、GROBID、Mathpix 等在高保真解析上更强。
3. 通用 Agent 平台能力弱于 Dify/AnythingLLM：多用户、权限、部署、workflow builder、插件市场、观测性不足。
4. 量化底层不如 Qlib/vectorbt/backtrader：因子分析、组合优化、风险归因、数据质量、实验管理还不完整。
5. UI/工程稳定性仍有 beta 感：多 wiki、dist 缓存、类型大小写冲突、错误可见性等需要继续打磨。

## 六、战略建议

### 6.1 收敛主线

建议主线定义为：面向研究/金融研究的持久化 LLM Wiki。不要泛泛做“另一个 Dify/AnythingLLM”，而要强化“LLM-maintained research wiki”的差异化。

### 6.2 优先打磨独特链路

优先打磨以下闭环：

```text
Add Wiki / ingest
  → source analysis
  → wiki page
  → graph
  → paper extraction
  → factor / strategy
  → backtest
  → report-to-wiki
```

### 6.3 解析层外包/可插拔

默认使用 MarkItDown / PyMuPDF4LLM；增强接 LlamaParse、GROBID、Vision LLM、Mathpix/Pix2Text。不要自研 OCR/公式识别。

### 6.4 量化层借力成熟框架

短期用 backtrader 做单策略回测，pandas/numpy 做简单因子；中期接 vectorbt 做参数扫描，接 Qlib 做因子、模型、组合分析。

### 6.5 产品化补齐

优先补齐：多 wiki 持久注册、任务状态可靠恢复、错误可见性、数据源配置 UI、实验版本和回测参数快照、引文/证据链、报告导出、权限/多用户可选。

## 七、一句话结论

llmwikify 不应定位为“Chat with Docs”或“通用 Agent 平台”，而应定位为：

> 面向研究/金融研究的持久化 LLM Wiki：把资料、推理、图谱、策略和回测结果沉淀为可审计、可复用、可迭代的知识资产。
