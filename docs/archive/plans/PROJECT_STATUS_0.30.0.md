# llmwikify v0.30.0 项目状态

> 项目能力梳理、未完成功能与测试覆盖情况总结
>
> 创建日期: 2026-04-24
> 版本: 0.30.0
> 状态: 进行中

---

## 项目基线

| 指标 | 值 |
|------|-----|
| 当前版本 | 0.30.0 |
| 测试总数 | 879+ passing |
| CLI 命令 | 22 个 |
| MCP 工具 | 20 个 |
| Python 支持 | 3.10+ |
| 代码质量 | ruff ✅, e2e ✅, mypy 进行中 |

---

## 一、已实现的核心能力

### 成熟度等级说明
- ✅ **成熟** - 功能完整，测试覆盖充分，可稳定使用
- ⚠️ **部分完整** - 功能可用，但缺少完整测试或边缘场景验证
- ❌ **未完成** - 功能骨架存在，但缺少实现或测试

### 1. Wiki 核心层

| 能力 | 组件 | 成熟度 | 说明 |
|------|------|--------|------|
| **页面管理** | `core/wiki.py` + 13 Mixins | ✅ | CRUD、索引自动更新 |
| **双向引用追踪** | `core/wiki_mixin_link.py`, `core/index.py` | ✅ | 精确到章节级的入站/出站链接 |
| **全文搜索** | `core/index.py` (SQLite FTS5) | ✅ | BM25 排序，0.06s/157页 |
| **健康检查/Lint** | `core/wiki_analyzer.py` | ✅ | 断链、孤立页面、矛盾、知识缺口 |
| **状态报告** | `core/wiki_mixin_status.py` | ✅ | 统计、推荐、提示 |
| **Prompt 模板系统** | `core/prompt_registry.py` | ✅ | YAML+Jinja2，Provider 定制 |
| **原则合规检查** | `core/principle_checker.py` | ✅ | Prompt 原则验证 |

### 2. 知识图谱层

| 能力 | 组件 | 成熟度 | 说明 |
|------|------|--------|------|
| **关系引擎** | `core/relation_engine.py` | ✅ | 8种关系类型×3种置信度 |
| **图分析引擎** | `core/graph_analyzer.py` | ✅ | PageRank、Hub/Authority、桥接节点 |
| **社区检测** | `core/graph_export.py` | ✅ | Leiden/Louvain 算法 |
| **图谱可视化** | `core/graph_export.py` | ✅ | HTML/SVG/GraphML 导出 |
| **意外连接报告** | `core/graph_export.py` | ✅ | Surprise Score 多维度评分 |
| **跨源综合分析** | `core/synthesis_engine.py` | ⚠️ | 强化声明、矛盾、知识缺口检测 |

### 3. 知识沉淀层

| 能力 | 组件 | 成熟度 | 说明 |
|------|------|--------|------|
| **Query Sink** | `core/query_sink.py` | ✅ | 待更新缓冲区、去重、紧急度追踪 |
| **查询合成** | `core/wiki_mixin_query.py` | ✅ | 答案保存为 wiki 页面 |
| **相似性匹配** | `core/wiki_mixin_query.py` | ✅ | 基于内容的页面相似度 |

### 4. 内容提取层

| 能力 | 组件 | 成熟度 | 说明 |
|------|------|--------|------|
| **文本/HTML 提取** | `extractors/text.py` | ✅ | 纯文本和简单 HTML |
| **PDF 提取** | `extractors/pdf.py` | ✅ | PyMuPDF 后端 |
| **网页提取** | `extractors/web.py` | ⚠️ | trafilatura 后端，部分场景测试 |
| **YouTube 字幕** | `extractors/youtube.py` | ⚠️ | 功能可用，无测试 |
| **统一提取器** | `extractors/markitdown_extractor.py` | ✅ | Office、图像、音频 |
| **自动类型检测** | `extractors/base.py` | ✅ | 基于文件后缀/MIME |

### 5. 接口层

| 能力 | 组件 | 成熟度 | 说明 |
|------|------|--------|------|
| **CLI 命令行** | `cli/commands.py` (22 个命令) | ✅ | 完整测试覆盖 |
| **MCP 服务** | `mcp/server.py` (20 个工具) | ✅ | stdio/http/sse 传输 |
| **Python API** | `__init__.py` | ✅ | Wiki / create_wiki 入口 |
| **Web UI** | `web/server.py` + React | ⚠️ | 编辑器、搜索可用，功能不完整 |
| **文件监听** | `core/watcher.py` | ⚠️ | 基础功能，缺少复杂场景测试 |

### 6. Agent 层

| 能力 | 组件 | 成熟度 | 说明 |
|------|------|--------|------|
| **工具注册** | `agent/tools.py` | ✅ | 可扩展工具注册系统 |
| **Runner 引擎** | `agent/runner.py` | ✅ | LLM 执行引擎 + 工具调用 |
| **生命周期 Hooks** | `agent/hooks.py` | ⚠️ | 基础注册，缺少复杂链测试 |
| **WikiAgent 编排** | `agent/wiki_agent.py` | ⚠️ | 主编排器，部分集成测试 |
| **内存管理** | `agent/memory.py` | ❌ | 无独立测试 |
| **任务调度** | `agent/scheduler.py` | ❌ | 完全无测试 |
| **通知系统** | `agent/notifications.py` | ❌ | 完全无测试 |
| **Dream Editor** | `agent/dream_editor.py` | ❌ | 完全无测试 |

---

## 二、测试覆盖情况

### 总体覆盖率：约 75-80%

### ✅ 充分测试的模块（~60%）

| 模块 | 测试文件 | 覆盖质量 |
|------|---------|---------|
| Wiki 核心操作 | `test_wiki_core.py` | 完整 |
| WikiIndex（搜索+引用） | `test_index.py` | 完整 |
| WikiAnalyzer（Lint） | `test_wiki_analyzer.py` | 完整 |
| QuerySink | `test_sink_flow.py`, `test_sink_dedup.py` | 完整 |
| PromptRegistry | `test_prompt_registry.py` | 完整 |
| PrincipleChecker | `test_v019_principle_checker.py` | 完整 |
| RelationEngine | `test_v022_relations.py` | 完整 |
| GraphExport / GraphAnalyzer | `test_v023_graph.py`, `test_p1_3_graph_analyzer.py` | 完整 |
| LLM Client | `test_llm_client.py` | 完整 |
| 内容提取器（基础） | `test_extractors.py` | 完整 |
| MCP 集成 | `test_mcp_integration.py` | 完整 |
| CLI 命令 | 多个 test_cli_*.py | 完整 |
| Agent Tools/Runner | `test_agent_layer.py` | 完整 |

### ⚠️ 部分测试的模块（~25%）

| 模块 | 测试状态 | 缺口说明 |
|------|---------|---------|
| SynthesisEngine | 仅集成测试 | 缺少独立单元测试 |
| Watcher | 基础功能测试 | 缺少文件变更风暴、错误恢复测试 |
| Web 服务器 | 仅 E2E 间接覆盖 | 缺少 API 单元测试 |
| Agent Memory | 无独立测试 | 仅通过集成测试验证 |
| Agent Hooks | 基础注册测试 | 缺少复杂 Hook 链测试 |
| Web 提取器 | 部分测试 | 缺少复杂网页场景测试 |
| PDF 提取器 | Mock 测试 | 缺少真实 PDF 解析测试 |
| Wiki Mixin 模块 | 通过 Wiki 集成测试 | 缺少独立单元测试 |

### ❌ 完全无测试的模块（~15%）

| 模块 | 文件 | 风险等级 | 说明 |
|------|------|---------|------|
| **Scheduler** | `agent/scheduler.py` | 🔴 高 | 定时任务调度，完全无测试 |
| **Notifications** | `agent/notifications.py` | 🔴 高 | 通知系统，完全无测试 |
| **Dream Editor** | `agent/dream_editor.py` | 🔴 高 | 精准 wiki 编辑引擎，完全无测试 |
| **Protocols** | `core/protocols.py` | 🟡 中 | 协议定义，无验证测试 |
| **Config** | `config.py` | 🟡 中 | 配置系统，无边界测试 |
| **YouTube 提取器** | `extractors/youtube.py` | 🟡 中 | 依赖外部服务，无验证测试 |
| **Constants** | `core/constants.py` | 🟢 低 | 常量定义，低风险 |

---

## 三、未完成功能优先级

### 🔴 高优先级（稳定性风险）

1. **Agent 核心组件测试**
   - Scheduler 调度器 - 添加基础单元测试
   - Notifications 通知系统 - 添加基础单元测试
   - Memory Manager 内存管理 - 添加独立测试
   - **影响**: Agent 模式的可靠性

2. **Dream Editor 测试**
   - 精准编辑引擎的核心逻辑测试
   - 与 Wiki 集成测试
   - **影响**: 自动化编辑功能可靠性

### 🟡 中优先级（功能完整性）

1. **SynthesisEngine 独立测试**
   - 跨源综合分析的边界测试
   - 矛盾检测、强化声明、知识缺口的单元测试

2. **Watcher 场景测试**
   - 文件变更风暴处理
   - 错误恢复机制
   - 并发写入场景

3. **Web API 单元测试**
   - 独立的 Starlette 端点测试
   - 不依赖 Playwright E2E

### 🟢 低优先级（代码质量）

1. **Protocols 协议验证测试**
   - WikiProtocol 及其子类型的验证

2. **Config 边界测试**
   - 无效配置处理
   - 配置合并逻辑

3. **Wiki Mixin 独立测试**
   - 各 Mixin 模块的独立单元测试

---

## 四、代码质量状态

### 已完成
- ✅ **ruff** - 全部通过（140+ 问题修复）
- ✅ **e2e 测试** - 全部 7 个通过（选择器修复）
- ⚠️ **mypy** - 进行中（剩余 ~162 个错误）
  - 已完成: 类型桩安装、WikiProtocol 基类创建、CLI 参数类型标注
  - 剩余: 缺少返回类型注解、`returning Any` 警告、次要类型不匹配

---

## 五、下一步讨论点

1. **Agent 层测试优先级** - Scheduler/Notifications/DreamEditor 的具体实施顺序
2. **SynthesisEngine 测试策略** - 是否需要独立的单元测试套件
3. **mypy 剩余错误处理** - 低优先级类型注解的处理策略（`# type: ignore` vs 完整标注）
4. **Web UI 功能规划** - 后续是否需要增强前端功能及相应测试

---

*Last updated: 2026-04-24*
