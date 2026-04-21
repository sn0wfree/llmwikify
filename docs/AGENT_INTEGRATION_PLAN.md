# llmwikify Agent 集成规划文档

**版本**: v1.0  
**创建日期**: 2026-04-20  
**状态**: 规划阶段  
**预计完成**: 29 天

---

## 📋 目录

1. [项目概述](#项目概述)
2. [核心设计决策](#核心设计决策)
3. [原有功能保留清单](#原有功能保留清单)
4. [新增 Agent 功能](#新增-agent-功能)
5. [技术架构](#技术架构)
6. [实施计划](#实施计划)
7. [验收标准](#验收标准)
8. [风险评估](#风险评估)
9. [附录：技术细节](#附录技术细节)

---

## 项目概述

### 项目目标

将 llmwikify 从"工具集"升级为"自主 Agent"，使其具备：
1. **自主感知**: 定时检查 raw/ 目录、监控文件变化
2. **自主决策**: 判断哪些内容需要 ingest、哪些页面需要更新
3. **自主执行**: 调用 ingest、lint、synthesize 等工具
4. **透明可控**: 所有操作可审查、可撤销、可配置

### 核心原则

基于 Karpathy 的 [LLM Wiki Principles](docs/LLM_WIKI_PRINCIPLES.md)：
- **持久化知识库**: Wiki 是 persistent, compounding artifact
- **人类主导**: 人类 curate sources, direct analysis; LLM 负责维护
- **增量维护**: 新来源到达时更新现有页面，而非重写
- **透明操作**: 所有操作记录到 log.md，可审查可撤销

### 项目范围

**纳入范围**:
- ✅ Agent 核心系统 (Runner + Hooks + Scheduler)
- ✅ Memory Layers (QuerySink 缓冲 + Dream 编辑)
- ✅ WebUI 迁移到 React
- ✅ Agent 功能 (聊天/任务监控/通知)
- ✅ Docker 容器化

**不纳入范围**:
- ❌ 多用户权限管理 (后续迭代)
- ❌ 完全自主模式 (保持半自主)
- ❌ 移动端应用 (后续迭代)

---

## 核心设计决策

### 决策 1: 解耦架构

**决策**: Agent 层与原有功能完全解耦

**方案**:
```
llmwikify/
├── core/           # 核心功能 (原有，不变)
├── mcp/            # MCP Server (原有，不变)
├── cli/            # CLI (原有，不变)
├── web/static/     # 原有 WebUI (保留)
└── agent/          # 新增：Agent 层 (独立目录)
```

**理由**:
- 保持向后兼容
- 可选启用 Agent 功能
- 降低迁移风险

**影响**:
- 新增 `llmwikify/agent/` 目录
- 新增可选依赖 `llmwikify[agent]`
- 原有代码 100% 保留

---

### 决策 2: Memory Layers 设计

**决策**: QuerySink 缓冲 + Dream 编辑的双层设计

**架构**:
```
用户提问 → Agent 回答
    ↓
保存到 QuerySink (缓冲/去重)
    ↓
[定时触发 Dream, 每 2 小时]
    ↓
Dream 分析 Sink 内容
    ↓
外科式编辑 Wiki 页面
    ↓
记录编辑日志 (可恢复)
```

**理由**:
- 保留 QuerySink 的去重功能
- 引入 Dream 的外科式编辑理念
- 统一存储到 wiki/ 目录

**数据隔离**:
```
wiki/
├── *.md              # Wiki 页面 (统一存储)
└── .sink/
    └── *.sink.md     # QuerySink (缓冲)

.llmwikify/agent/     # Agent 数据 (隔离)
├── history.jsonl     # 对话历史
├── scheduler.json    # 定时任务
└── edits.jsonl       # Dream 编辑日志
```

---

### 决策 3: 半自主边界

**决策**: 半自主模式，仅删除/批量操作需确认

**自动执行** (无需确认):
- ✅ 读取操作 (search, read_page)
- ✅ 机械维护 (更新 index.md, 追加 log.md)
- ✅ 保存到 QuerySink (缓冲)
- ✅ 检查新文件 (仅通知)

**需要确认** (弹出对话框):
- ⚠️ 创建新 Wiki 页面
- ⚠️ 修改现有页面 (>100 字符)
- ⚠️ 删除页面或链接
- ⚠️ 批量操作 (>5 个页面)
- ⚠️ 外部 API 调用 (web search)

**完全禁止** (无用户明确指令):
- ❌ 删除页面
- ❌ 修改 wiki.md (schema)
- ❌ 修改 config 文件

---

### 决策 4: WebUI 框架统一

**决策**: 迁移到 React + TypeScript + Tailwind

**方案**:
- 原有 Vanilla JS WebUI → React 重写
- 统一使用 React 技术栈
- Agent 功能作为 React 组件添加

**理由**:
- 单一技术栈，易维护
- 组件化，易扩展
- 与 Nanobot 生态兼容
- 长期开发效率高

**成本**: +5 天 (一次性迁移)

---

### 决策 5: 自主场景

**决策**: 实现以下 4 个自主场景

**场景 A: 监控 raw/ 目录**
```
1. Agent 每 30 分钟检查 raw/
2. 发现新文件 → 通知用户
3. 用户确认 → 执行 ingest
4. 分析内容 → 建议创建页面
5. 用户确认 → 创建页面
```

**场景 B: 知识缺口分析**
```
1. Agent 每周分析知识缺口
2. 发现缺失主题 → 建议补充
3. 用户确认 → 搜索外部来源
4. 找到相关内容 → 建议 ingest
5. 用户确认 → 执行 ingest
```

**场景 C: 对话中积累知识**
```
1. 用户与 Agent 对话
2. Agent 识别新知识 → 保存到 Sink
3. Dream 分析 Sink → 编辑 Wiki 页面
4. 通知用户："已更新 3 个页面"
5. 用户可查看/撤销
```

**场景 D: 自主研究**
```
1. 用户提出问题："研究 X 领域最新进展"
2. Agent 自主搜索 → 找到 10 篇文章
3. 批量 ingest → 分析 → 创建综述页面
4. 提交报告给用户审核
```

---

## 原有功能保留清单

### CLI 命令 (100% 保留)

| 命令 | 状态 | 说明 |
|------|------|------|
| `llmwikify init` | ✅ 保留 | 初始化 wiki 结构 |
| `llmwikify ingest` | ✅ 保留 | Ingest 源文件 |
| `llmwikify batch` | ✅ 保留 | 批量 ingest |
| `llmwikify search` | ✅ 保留 | FTS5 搜索 |
| `llmwikify references` | ✅ 保留 | 引用关系 |
| `llmwikify lint` | ✅ 保留 | 健康检查 |
| `llmwikify knowledge-gaps` | ✅ 保留 | 知识缺口分析 |
| `llmwikify graph-analyze` | ✅ 保留 | 图谱分析 |
| `llmwikify suggest-synthesis` | ✅ 保留 | 跨源合成建议 |
| `llmwikify mcp` | ✅ 保留 | MCP Server |
| `llmwikify serve --web` | ✅ 保留 | Web UI 服务 |
| `llmwikify watch` | ✅ 保留 | 文件监控 |

**新增 Agent 命令**:
```bash
llmwikify agent --watch          # 启动 Agent 后台服务
llmwikify serve --agent --web    # 同时启动 Web + Agent
```

---

### Python API (100% 保留)

```python
# 原有 API 全部保留
from llmwikify import Wiki

wiki = Wiki(Path("/path/to/wiki"))

# 核心方法
wiki.ingest_source("document.pdf")
wiki.write_page("Page", content)
wiki.read_page("Page")
wiki.search("query")
wiki.lint()
wiki.synthesize_query("Q", "A", ["Page1"])
wiki.get_relation_engine()
wiki.graph_analyze()

# 不受影响 - 继续使用
```

**新增 Agent API**:
```python
from llmwikify.agent import WikiAgent

agent = WikiAgent(root="~/wiki")
await agent.chat("帮我分析这个文件")
await agent.start()  # 启动后台调度
```

---

### MCP Server (20 工具全部保留)

| 工具 | 状态 | 说明 |
|------|------|------|
| `wiki_init` | ✅ 保留 | 初始化 |
| `wiki_ingest` | ✅ 保留 | Ingest |
| `wiki_write_page` | ✅ 保留 | 写入页面 |
| `wiki_read_page` | ✅ 保留 | 读取页面 |
| `wiki_search` | ✅ 保留 | 搜索 |
| `wiki_lint` | ✅ 保留 | Lint |
| `wiki_status` | ✅ 保留 | 状态 |
| `wiki_log` | ✅ 保留 | 日志 |
| `wiki_recommend` | ✅ 保留 | 推荐 |
| `wiki_build_index` | ✅ 保留 | 构建索引 |
| ... (共 20 个) | ✅ 保留 | 全部保留 |

**Agent 使用方式**: Agent **内部调用** 这些 MCP 工具，而非替换

---

### Web UI 功能 (功能增强)

#### 原有功能 (React 重写后保留):
- ✅ Wiki 编辑器 (预览/编辑/分屏)
- ✅ 文件树导航
- ✅ 搜索功能
- ✅ 知识图谱可视化
- ✅ 引用关系 (Backlinks/Outgoing)
- ✅ Wiki 健康状态
- ✅ Sink Status
- ✅ Recommendations
- ✅ Insights (Synthesis/Gaps/Graph)

#### 新增功能 (Agent 增强):
- 🆕 Agent 聊天面板
- 🆕 任务监控面板
- 🆕 自主操作通知
- 🆕 Dream 编辑日志
- 🆕 知识增长可视化

**技术栈变化**:
- ❌ Vanilla JS → ✅ React + TypeScript
- ✅ 功能完全保留 + 增强

---

### 核心功能 (100% 保留)

| 功能 | 状态 | 说明 |
|------|------|------|
| SQLite FTS5 搜索 | ✅ 保留 | Porter 词干，BM25 排名 |
| 双向引用 | ✅ 保留 | `[[wikilink]]` 检测 |
| Query Sink | ✅ 保留 | 查询缓冲 + 去重 |
| 文件提取 | ✅ 保留 | PDF/Office/YouTube/URL |
| 文件监控 | ✅ 保留 | Watch `raw/` |
| 知识图谱 | ✅ 保留 | PageRank/社区检测 |
| Smart Lint | ✅ 保留 | Broken links/Orphans/Contradictions |
| 跨源合成 | ✅ 保留 | 检测矛盾/缺口 |

---

### 数据格式 (100% 兼容)

```
wiki/
├── index.md          ✅ 格式不变
├── log.md            ✅ 格式不变
├── *.md              ✅ 格式不变
└── .sink/
    └── *.sink.md     ✅ 格式不变

.llmwikify.db         ✅ SQLite 格式不变
wiki.md               ✅ Schema 格式不变
```

**新增 Agent 数据** (隔离存储):
```
.llmwikify/
├── agent/
│   ├── history.jsonl    # 对话历史
│   ├── scheduler.json   # 定时任务
│   └── edits.jsonl      # Dream 编辑日志
```

---

## 新增 Agent 功能

### 1. Agent 核心系统

**组件**:
- `WikiAgentRunner`: Agent 执行循环 (基于 Nanobot Runner 定制)
- `WikiToolRegistry`: 工具注册表 (封装 20+ MCP 工具)
- `CompositeHook`: Hooks 系统 (生命周期回调)
- `WikiScheduler`: 定时任务调度器 (基于 Nanobot Cron 定制)

**功能**:
- 自主决策执行
- 工具调用编排
- 上下文管理
- 流式输出

---

### 2. Memory Layers

**组件**:
- `QuerySink`: 原有缓冲机制 (保留)
- `DreamEditor`: 新增外科式编辑引擎

**功能**:
- 对话历史压缩
- 知识提取
- 外科式编辑
- 编辑日志 + 恢复

---

### 3. WebUI - Agent 功能

**组件**:
- `AgentChat`: Agent 聊天面板
- `TaskMonitor`: 任务监控面板
- `Notifications`: 自主操作通知
- `DreamLog`: Dream 编辑日志
- `KnowledgeGrowth`: 知识增长可视化

**功能**:
- 自然语言交互
- 任务创建/管理
- 实时通知
- 编辑历史查看

---

### 4. 自主任务系统

**系统任务**:
1. **Dream 更新** (每 2 小时)
   - 分析 QuerySink 新条目
   - 外科式编辑 Wiki 页面

2. **检查 raw/** (每 30 分钟)
   - 监控新文件
   - 通知用户

3. **每日 Lint** (每天 22:00)
   - 健康检查
   - 生成建议

4. **每周缺口分析** (每周一 9:00)
   - 知识缺口分析
   - 建议补充

---

## 技术架构

### 架构分层

```
┌─────────────────────────────────────────────────────────┐
│                    用户交互层                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │   CLI        │  │   MCP        │  │  WebUI       │  │
│  │  命令行      │  │  工具调用    │  │  (React)     │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
└─────────┼─────────────────┼─────────────────┼──────────┘
          │                 │                 │
          ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────┐
│              Agent 层 (可选启用)                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │  WikiAgent                                       │   │
│  │  - 自主决策                                       │   │
│  │  - 定时任务                                       │   │
│  │  - Dream 编辑                                     │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
                              │
                              │ 调用
                              ▼
┌─────────────────────────────────────────────────────────┐
│              核心功能层 (原有功能)                        │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Wiki 类                                          │   │
│  │  - ingest_source()                               │   │
│  │  - analyze_source()                              │   │
│  │  - lint()                                        │   │
│  │  - synthesize_query()                            │   │
│  │  - search()                                      │   │
│  │  - write_page()                                  │   │
│  │  - ... (20+ 方法)                                 │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

### 目录结构

```
llmwikify/
├── src/llmwikify/
│   ├── agent/                    # 新增：Agent 层 (独立)
│   │   ├── __init__.py
│   │   ├── wiki_agent.py         # Wiki Agent 主类
│   │   ├── runner.py             # Agent Runner
│   │   ├── tools.py              # Tool Registry
│   │   ├── hooks.py              # Hooks 系统
│   │   ├── scheduler.py          # Cron Scheduler
│   │   ├── dream_editor.py       # Dream 编辑
│   │   └── memory.py             # Memory Layers
│   ├── core/                     # 原有：核心功能
│   │   ├── wiki.py
│   │   ├── query_sink.py
│   │   └── ...
│   ├── mcp/                      # 原有：MCP Server
│   │   └── server.py
│   ├── web/
│   │   ├── static/               # 原有：Vanilla JS (保留)
│   │   │   ├── index.html
│   │   │   └── js/
│   │   └── webui/                # 新增：React (统一框架)
│   │       ├── src/
│   │       │   ├── App.tsx
│   │       │   ├── components/
│   │       │   │   ├── AgentChat.tsx
│   │       │   │   ├── TaskMonitor.tsx
│   │       │   │   └── ...
│   │       │   └── styles/
│   │       └── dist/
│   ├── cli/                      # 原有：CLI
│   │   └── commands.py
│   └── prompts/                  # 原有：Prompts
│       └── ...
├── pyproject.toml                # 更新：可选依赖
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

### 依赖管理

```toml
# pyproject.toml
[project]
name = "llmwikify"
version = "0.30.0"

[project.optional-dependencies]
agent = [
    "nanobot-ai>=0.1.5",
    "croniter>=2.0.0",
    "filelock>=3.13.0",
]
webui = [
    # React WebUI 依赖
]
all = [
    "llmwikify[agent,webui]",
]
```

**安装方式**:
```bash
# 仅原有功能 (不受影响)
pip install llmwikify

# 新增 Agent 功能
pip install llmwikify[agent]

# 完整功能
pip install llmwikify[all]
```

---

## 实施计划

### Phase 1: Agent 核心基础 (6 天)

**目标**: 实现 Agent 核心系统，可独立使用

**任务**:
- Day 1-2: 抽取 Nanobot `runner.py`，定制 Wiki 上下文注入
- Day 3-4: 封装 `ToolRegistry`，包装 20 个 MCP 工具
- Day 5: 实现 `Hooks` 系统 (WikiHook, DreamSyncHook, AutoIngestHook)
- Day 6: 实现 `Scheduler` (Cron)，注册 Wiki 系统任务

**交付**:
- `llmwikify/agent/runner.py`
- `llmwikify/agent/tools.py`
- `llmwikify/agent/hooks.py`
- `llmwikify/agent/scheduler.py`
- `llmwikify/agent/wiki_agent.py`

**验收**:
- ✅ `from llmwikify.agent import WikiAgent` 可用
- ✅ 不影响 `from llmwikify import Wiki`
- ✅ 可选依赖，不安装也不影响原有功能

---

### Phase 2: Memory Layers (3 天)

**目标**: 实现 QuerySink 缓冲 + Dream 编辑双层设计

**任务**:
- Day 7: 整合现有 `query_sink.py`，增强与 Agent 的集成
- Day 8-9: 实现 `DreamEditor` (外科式编辑引擎)

**交付**:
- `llmwikify/agent/memory.py`
- `llmwikify/agent/dream_editor.py`

**验收**:
- ✅ QuerySink 继续独立工作
- ✅ Dream 层可选启用
- ✅ 数据格式向后兼容

---

### Phase 3: WebUI 迁移 + Agent 功能 (12 天)

**目标**: 迁移到 React，实现 Agent 核心功能

**任务**:
- Day 10: 初始化 React 项目 (Vite + TypeScript + Tailwind)
- Day 11-14: 迁移核心组件 (Editor, Preview, Search, FileTree, Health, Insights)
- Day 15-16: 实现 `AgentChat` 组件
- Day 17-18: 实现 `TaskMonitor` 组件
- Day 19-20: 实现 `Notifications` 组件
- Day 21: 实现 `DreamLog` 组件

**交付**:
- `llmwikify/web/webui/src/App.tsx`
- `llmwikify/web/webui/src/components/*.tsx`

**验收**:
- ✅ 原有 WebUI 功能全部保留
- ✅ Agent 功能正常工作
- ✅ 流式输出正常

---

### Phase 4: 增强功能 (5 天)

**目标**: 实现知识可视化等增强功能

**任务**:
- Day 22-23: 实现 `KnowledgeGrowth` 可视化组件
- Day 24: 实现批量操作面板 (可选)
- Day 25-26: 性能优化 + 测试

**交付**:
- `llmwikify/web/webui/src/components/KnowledgeGrowth.tsx`

**验收**:
- ✅ 图表正常显示
- ✅ 性能达标

---

### Phase 5: Docker + 测试 (3 天)

**目标**: 容器化，端到端测试

**任务**:
- Day 27-28: 编写 Dockerfile, docker-compose.yml
- Day 29: 端到端测试
- Day 30: 文档编写

**交付**:
- `Dockerfile`
- `docker-compose.yml`
- `docs/AGENT_GUIDE.md`

**验收**:
- ✅ Docker 容器正常启动
- ✅ 所有功能正常
- ✅ 文档完整

---

### 总时间估算

| Phase | 任务 | 时间 |
|-------|------|------|
| **Phase 1** | Agent 核心 | 6 天 |
| **Phase 2** | Memory Layers | 3 天 |
| **Phase 3** | WebUI 迁移 + Agent | 12 天 |
| **Phase 4** | 增强功能 | 5 天 |
| **Phase 5** | Docker + 测试 | 3 天 |
| **总计** | | **29 天** |

---

## 验收标准

### 解耦验证

- [ ] 不安装 `llmwikify[agent]`，原有功能正常
- [ ] 安装 `llmwikify[agent]`，原有功能正常
- [ ] CLI 命令不受影响
- [ ] MCP Server 不受影响
- [ ] 现有 WebUI 不受影响
- [ ] Python API 不受影响

### Agent 功能验证

- [ ] `WikiAgent` 可独立实例化
- [ ] Agent 可注入现有 `Wiki` 实例
- [ ] Agent 调用现有 Wiki 方法 (而非替换)
- [ ] Agent 可启用/禁用
- [ ] Agent 数据与 Wiki 数据隔离

### 自主场景验证

- [ ] 场景 A: raw/ 监控 → 通知 → ingest
- [ ] 场景 B: 知识缺口分析 → 建议 → 补充
- [ ] 场景 C: 对话 → Sink → Dream → Wiki
- [ ] 场景 D: 自主研究 → 报告 → 审核

### 半自主边界验证

- [ ] 读取操作自动执行
- [ ] 创建/修改页面需确认
- [ ] 删除操作需确认
- [ ] 批量操作需确认

### WebUI 验证

- [ ] 原有功能全部保留
- [ ] Agent 聊天流畅 (流式输出)
- [ ] 任务监控完整
- [ ] 通知系统实时
- [ ] Dream 日志可追溯
- [ ] 可视化图表正常

---

## 风险评估

### 技术风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| Nanobot API 变更 | 中 | 高 | 封装隔离层，不直接依赖 |
| React 迁移延期 | 中 | 中 | 分阶段迁移，先核心功能 |
| Dream 编辑错误 | 低 | 高 | 备份机制，可恢复 |
| 性能下降 | 低 | 中 | 性能测试，优化 |

### 进度风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| Phase 3 延期 | 中 | 中 | 优先核心功能，增强功能可延后 |
| 测试时间不足 | 中 | 高 | 预留缓冲时间 |
| 需求变更 | 低 | 高 | 严格变更控制 |

---

## 附录：技术细节

### Agent Runner 抽取

**源文件**: `nanobot/agent/runner.py` (~900 行)

**关键方法**:
```python
class WikiAgentRunner(AgentRunner):
    def _prepare_context(self, messages):
        # 注入 wiki index, log, schema
        pass
    
    async def _execute_tools(self, tool_calls):
        # 工具执行 + 审计
        pass
```

### Dream Editor 设计

```python
class DreamEditor:
    def run_dream(self):
        # 1. 读取 Sink 新条目
        # 2. LLM 分析需要编辑的页面
        # 3. 外科式编辑
        # 4. 记录编辑日志
        
    def _apply_surgical_edit(self, page: str, edit: dict):
        # 最小化编辑逻辑
        pass
    
    def restore_edit(self, timestamp: str):
        # 从备份恢复
        pass
```

### WebUI 组件结构

```tsx
// src/App.tsx
function App() {
  return (
    <div id="app">
      <TopBar />
      <Sidebar>
        <FileTree />
        <HealthStatus />
        <AgentChatPanel />  {/* 新增 */}
        <TaskMonitorPanel /> {/* 新增 */}
      </Sidebar>
      <MainContent>
        <ViewTabs />
        <PreviewPane />
        <EditPane />
      </MainContent>
    </div>
  );
}
```

---

## 变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-04-20 | 初始版本 |

---

## 参考文档

- [LLM Wiki Principles](docs/LLM_WIKI_PRINCIPLES.md)
- [Nanobot Docs](https://nanobot.wiki)
- [Karpathy's LLM Wiki](https://karpathy.ai/llmwiki)

---

**文档结束**
