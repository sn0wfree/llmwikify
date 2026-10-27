# 代码复用优化候选池 + 关键性能点剥离方案

> **日期**: 2026-10-27 · **基线 commit**: `5398f6d3`（v0.41-dev）
> **性质**: 纯分析与方案设计，**未改任何 `src/` 代码**
> **方法**: graphify 0.9.96（AST 图）+ 自写 AST 归一化克隆检测（`scripts/clone_survey.py`，双口径）+ git churn 统计 + 源码级证据链 + 3 路并行只读勘察
> **配套文档**: `docs/designs/codebase-survey.md`（复用现状复核）· `docs/designs/code-reuse-optimization.md`（R1–R6 方案）

---

## 1. 项目理解摘要与信息缺口

### 1.1 项目理解

| 项 | 实测 |
|----|------|
| 技术栈 | Python 3.12 · FastAPI · httpx/requests · SQLite(FTS5) · MCP · React/Vite WebUI |
| 规模 | `src/llmwikify/` **407 个 .py / 79,635 行**；`tests/` 规模相当 |
| 分层 | `interfaces → apps → kernel → foundation`，**实测 0 层违规**（AST + grep 双确认） |
| 层占比 | apps 44,858(56%) · kernel 14,599(18%) · interfaces 11,740(15%) · foundation 8,331(10%) |
| 重复现状 | 结构哈希克隆 **902 行**(docstring 口径) / **402 行**(payload 口径)，70 组；转发层 **834 行** |
| 热点文件 | `kernel/wiki/engines/analyzer.py`(churn 10) · `apps/chat/agent/orchestrator.py` · `foundation/llm/streamable.py` · `apps/chat/agent/runner_v2.py` |
| 性能基建 | **已有** 指纹缓存（`kernel/graph/cache.py`）· 8 条 lint 规则框架 · 3 个 benchmark 脚本（`repro_bench_graph.py` / `profile_lint_paths.py` / `profile_core_cache_llm_fresh.sh`） |
| 已知历史 | O(E²) 边去重已修（`6f44e8b8`）· `missing_cross_ref` O(N²) 已修（150s→秒级）· lint 单次扫描已合并 |

**关键判断**：这不是一个"缺抽象"的项目 —— `LintEngine` 的 `CrossPageRule` 共享 `shared_pages`、
`cache.py` 的指纹缓存、`iter_with_metrics`/`call_with_metrics` 都已经是有意识的抽象。
**真正的债集中在三处**：(1) LLM 调用层的三处平行实现；(2) `async def` 路由里跑同步重活；
(3) 持久层「同一文件、不同 PRAGMA 策略」的连接单例。

### 1.2 信息缺口（影响方案精度，需你确认）

| # | 缺口 | 影响 | 我的默认假设 |
|---|------|------|-------------|
| G1 | **无生产火焰图 / APM 数据**。仓库内只有脚本化 profile，无线上 profiling 产物 | 所有性能结论是**静态可达性 + 已有基准脚本**，不是实测 p99 | 按"可达即高风险"排序，实施前用仓库自带脚本复测 |
| G2 | **线上 wiki 规模未知**（页数 / raw 文件数 / DB 行数） | `_scan_all_pages`、`add_relations`、token 计数的绝对耗时无法估 | 按 1400 页量级（`missing_cross_refs.py:41` 注释中的实测基准）估算 |
| G3 | **无基准测试框架**（pytest-benchmark / timeit 基准均无） | "剥离后必须可单独基准测试"这条约束需要**先建基准设施** | 批次 0 先补 `pytest-benchmark` + 最小基准集 |
| G4 | **团队规模 / owner 机制未知**（仓库无 CODEOWNERS） | 共享库 owner、废弃策略无法落到具体人 | 暂按"层 owner = 该层主要维护者"占位，需你补人名 |
| G5 | ~~**`foreign_keys` 实际生效值未验证**~~ | — | ✅ **已由批次 0.1 关闭**：FK 值不再取决于「谁先构造」，而由 `ConnectionProfile` 决定；research 恒为 OFF、chat 恒为 ON，且有回归测试锁定。§6 P2 已按「修 bug」定性并已落地 |
| G6 | **无 CI 性能门禁** | 性能回归只能靠人工跑脚本 | 建议在批次 3 引入基线对比门禁 |
| G7 | **WAL/busy_timeout 的实际部署配置**未确认 | 连接策略修复的副作用面未知 | 按 config 默认值处理 |

> 以下方案**不依赖 G1–G7 的具体答案**即可启动批次 0/1；但 §6 的优先级排序在拿到线上 profile 后应重排一次。

---

## 2. 重复热点候选表

**收益公式**：`复用收益 = 重复次数 × 修改频率 × 影响范围 ÷ 抽象成本`
（修改频率取 `git log -60` 的改动次数；影响范围取"该抽象变更需触达的模块数"；抽象成本取"新增接口 + 迁移调用点 + 补测试"的相对工作量）

| ID | 位置 | 重复类型 | 次数 | payload | churn | 影响范围 | 抽象成本 | 收益分 | 建议 |
|----|------|---------|-----:|-------:|------:|---------|---------|------:|------|
| **U1** | `apps/chat/agent/runner_v2.py:924` ↔ `unified/handlers/chat_reasoner.py:201` | **语义重复**（近乎逐字） | 2 | ~50 | **22** | **chat 主链路全部对话 + unified loop** | 中 | **9.6** | ✅ **最高优先** |
| **U2** | `foundation/auth/db.py:128` ↔ `:325` 两个 `_init_schema` | 完全重复 | 2 | 37 | 4 | 认证全部 | 低 | **7.2** | ✅ 提取 |
| **U3** | `apps/chat/db/_facade.py` → `research_delegate.py` → `apps/research/db.py` 三层转发 | 完全重复 | 44 方法 | ~250 | 中 | chat 持久化全表 | **高**（但解法是**删层**不是抽函数） | **7.0** | ✅ 删中间层 |
| **U4** | `apps/research/db.py:431` `get_sub_queries` ↔ `:509` `get_sources` | 结构重复 | 2 | 18 | 5 | research 读取路径 | 低 | **5.4** | ✅ 提取 |
| **U5** | `kernel/storage/backend.py:437` ↔ `kernel/wiki/mixins/core/utility.py:236` `_build_merge_notice` | 完全重复 | 2 | 17 | 4+4 | wiki schema 合并 | 低 | **5.1** | ✅ 提取（改名公开） |
| **U6** | `apps/chat/skills/` `autoresearch_compound_skill.py:28` ↔ `workflows/skill.py:43` `_format_run_not_found` | 完全重复 | 2 | 17 | 中 | skills 错误提示 | 低 | **4.6** | ✅ 提取 |
| **U7** | `apps/chat/skills/crud/` 5 个 skill 的 `_get_memory`/`_get_manager`×2/`_get_scheduler`/`_get_editor` | 结构重复 | **5** | 4 | 低 | skills 依赖获取 | 低 | **4.5** | ✅ 提取 |
| **U8** | `apps/chat/skills/actions/web_search_action.py:87` ↔ `:114` `_search_youtube`/`_search_news` | 结构重复 | 2 | 14 | 低 | web search action | 低 | **4.2** | ✅ 提取 |
| **U9** | `apps/agent/tools/__init__.py:823` ↔ `skill_adapter.py:99` `list_tools` | 结构重复 | 2 | 12 | 低 | agent 工具面 | 低 | **4.0** | ✅ 提取 |
| **U10** | `foundation/config.py:325` `get_mcp_config` ↔ `:346` `get_search_config` | 结构重复 | 2 | 10 | 中 | 配置加载 | 低 | **3.6** | ✅ 提取 |
| **U11** | `foundation/auth/db.py:92` ↔ `:312` `_ensure_dir` | 完全重复 | 2 | 8 | 4 | 认证 | 低 | **3.2** | ✅ 随 U2 带 |
| **U12** | `apps/chat/memory/` 三 store 的 `delete` | 结构重复 | 3 | 5 | 低 | memory | 低 | **2.8** | ⚠️ 语义待确认 |
| **U13** | `clarifier.py:27` / `harness/review.py:23` / `research/report.py:25` `__init__` | 结构重复 | 3 | 5 | 低 | 各模块独立 | 中 | **2.2** | ⚠️ 不同则不强抽 |

**语义重复但 AST 检不出（需人工识别）** —— 这是 U1 的关键特征：

```
runner_v2.py:924-981  (58 行)          chat_reasoner.py:201-256  (56 行)
  路径1  _llm_stream_with_retry           路径1  _llm_stream_with_retry      ← 同
  路径2  wiki_service.get_llm()           路径2  wiki_service.get_llm()      ← 同
         .astream_chat                          .astream_chat
  路径3  llm.chat() 单发兜底                路径3  llm.chat() 单发兜底        ← 同
  prompt_name="chat_reason"              prompt_name="chat_reason"         ← 同
  prompt_name="chat_fallback"            prompt_name="chat_fallback"       ← 同
  iter_with_metrics / call_with_metrics  iter_with_metrics / call_with_metrics ← 同
```

差异只有 **注释、`chars_in` 的写法（for 循环 vs 生成器表达式）、守卫顺序、
`events.DONE` vs 字面量 `"done"`（实测两者都是 `"done"`，语义等价）**。
→ AST 结构哈希因这些琐碎差异判为不同组，**语义上是同一份分派逻辑**。

> **方法论提示**：`scripts/clone_survey.py` 只能检出 type-1/type-2 克隆；
> **type-3（语义重复）必须靠人读**。U1 就是靠逐行 diff 才暴露的，
> 它同时是**性能热点**（见 §5 P1）与**复用热点**（本表）。

---

## 3. 高优先级复用候选详细方案

### U1 — LLM 流式分派：3 份平行实现收敛为 1 个 dispatcher

**位置与重复表现**

| 实现 | 位置 | 行数 | 角色 |
|------|------|-----:|------|
| A | `apps/chat/agent/runner_v2.py:924-981` `_stream_llm` | 58 | runner_v2 路径 |
| B | `apps/chat/agent/unified/handlers/chat_reasoner.py:201-256` `_stream_llm` | 56 | unified loop 路径 |
| C | `apps/chat/base.py:463-506` `_astream_with_tools` | 44 | 基础 ChatService 路径（多一个 `_stream_preprocess` 转换层） |

**B 的 docstring 自认是「包装 runner_v2._stream_llm 逻辑」，但实际是重新实现。**

**重复类型**：语义重复（type-3）

**是否建议提取**：✅ **强烈建议**。这是全仓收益最高的复用点：
- 改一次 LLM 策略（超时 / 缓存 / 并发闸门 / 新指标）必须**同步改 3 处**，漏一处就行为分叉；
- `runner_v2` churn 22 次 / 60 commits，是**最热的文件**；
- 三份实现的 fallback 常量（`events.DONE` vs `"done"`）已经分叉过一次，说明漂移正在发生。

**推荐复用方式**：**提取一个 dispatcher（不是工具类）**，三处调用方改为委托。

```python
# apps/chat/agent/llm_dispatcher.py（新文件，apps 层）
class LLMDispatcher:
    """唯一的 LLM 调用分派点。三条来源路径 + 指标记录，只此一份。

    职责边界：
      - 选路（retry / astream_chat / 单发兜底）
      - 记录指标（chars_in / latency / prompt_name）
    不负责：
      - 构造 prompt（属于 prompt_builder）
      - 业务编排（属于 orchestrator）
      - 事件语义转换（属于 _stream_preprocess）
    """
    def __init__(self, chat_service: Any, *, preprocess: Callable | None = None) -> None: ...

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        *,
        prompt_name: str = "chat_reason",
    ) -> AsyncIterator[dict[str, Any]]: ...
```

**接口/函数签名**（保持三处调用点现有签名不变 → 迁移成本最低）

```python
# runner_v2.py:924  → 替换函数体为一行委托
async def _stream_llm(self, messages, tools):
    async for ev in self._dispatcher.stream(messages, tools):
        yield ev

# chat_reasoner.py:201 → 同上
# base.py:463 → 把 _stream_preprocess 作为 preprocess= 注入
```

**参数设计**
- `prompt_name` **保留为参数**（三处已用同名 tag `chat_reason`/`chat_fallback`），不要硬编码 ——
  指标聚合按 tag 分组，改名会断历史曲线。
- `preprocess` 注入而非子类化：C 的 `_stream_preprocess` 是唯一的真实差异，函数注入比继承轻。

**依赖与副作用处理**
- dispatcher **不持有 LLM client**，只通过 `chat_service` 上的 `getattr` 延迟取（保持现有
  `getattr(self._chat_service, "_llm_stream_with_retry", None)` 的鸭子类型兼容）。
- **无全局状态**：dispatcher 实例挂在持有者上（runner_v2 / chat_reasoner 各自持有），
  不进模块级单例 —— 避免与 §5 P6 的"全局缓存失效"问题叠加。
- 指标写入仍走 `llm_metrics` 的 `iter_with_metrics`/`call_with_metrics`，
  **不要在 dispatcher 里再加一层计时**（会重复计时）。

**需要补充的测试**
1. 契约测试：三条路径各产出**相同事件序列**（同一 stub client）。
2. `prompt_name` tag 断言：三条路径产出正确的指标 tag（防止重构丢指标）。
3. fallback 路径：只有 `chat` 没有 `astream_chat` 时，走路径 3 且 tag = `chat_fallback`。
4. 回归守卫：断言 `runner_v2` 与 `chat_reasoner` **不再各自实现分派**（可用 AST 断言
   `scripts/clone_survey.py` 的 payload 口径，或简单断言函数体不含 `iter_with_metrics`）。

**风险点与回滚**
- 风险：事件顺序/标签细微变化 → SSE 前端契约。**必须先跑 chat SSE 集成测试**。
- 风险：C 的 `_stream_preprocess` 注入后若忘记套用，thinking/tool_call 事件会丢。
- 回滚：dispatcher 是**纯新增文件**，回滚只需三处调用点还原（单文件 revert）。

**预计收益**：~50 行重复消除；策略变更从"改 3 处"降为"改 1 处"；为 §6 P1（LLM 隔离）
提供唯一的注入点。**优先级 P0。**

---

### U2 — `foundation/auth/db.py` 两个 `_init_schema` 合并

**位置**：`foundation/auth/db.py:128`（`UserRepository`）+ `:325`（`ApiKeyRepository`）

**重复表现**：**逐字相同**，且**都同时创建 `users` + `api_keys` 两张表**，
都执行同一段「`PRAGMA table_info(users)` → 检出 `password_hash` → DROP 两表 → 重建」。

**是否建议提取**：✅ 建议，但**用模块级函数，不要用继承**。
原方案（`code-reuse-optimization.md` R3 做法 B）提的「`ApiKeyRepository` 继承 `UserRepository`」
**方向错误** —— 它不是 `UserRepository`，且会连带引入 `exists()`/`count()`/`get_by_email()` 等用户域方法。

**推荐复用方式**

```python
# foundation/auth/db.py —— 模块级私有函数
def _create_auth_schema(conn: sqlite3.Connection) -> None:
    """建 users + api_keys 两张表（含 Phase 2.5 旧 schema 迁移）。

    两张表由同一段 DDL 创建，两个 repository 共享。
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "password_hash" in columns:
        conn.executescript("DROP TABLE IF EXISTS api_keys; DROP TABLE IF EXISTS users;")
    conn.executescript(""" ... """)
    conn.commit()
```

**参数设计**：只收 `conn`，不收 flag —— 因为**确实没有差异部分**（这正是与原方案「做法 A」的关键区别）。

**依赖与副作用处理**：函数内 `conn.commit()` 与现状一致，**不要**改成由调用方提交
（会改变两个 repository 的事务边界，超出「去重」范围）。

**顺带**：同文件 `_ensure_dir`(92) ↔ `_ensure_dir`(312) 同样 8 行同构 → 一并提取。

**需要补充的测试**
- 两个 repository 各自建表后，schema 等价（列 + 索引）。
- 旧 schema（含 `password_hash`）迁移路径仍生效 —— **必须有**，这是最容易被"去重"误伤的语义。

**风险点与回滚**：低。风险集中在迁移分支。回滚 = 单文件 revert。

**预计收益**：减 ~45 行（37 payload + 8 `_ensure_dir`）；消除「加字段要改两处」的陷阱。**优先级 P1。**

---

### U3 — 删掉 `ResearchDelegate` / `WikiDelegate` 中间层

**位置**：`apps/chat/db/research_delegate.py`(318) + `wiki_delegate.py`(150)

**重复表现**：44 个方法全是单行转发，`ChatDatabase → Delegate → ResearchDatabase/WikiDatabase` 三层。

**是否建议提取**：❌ **不提取 —— 要删**。
「抽公共函数」是**再加一层**，正确解法是删中间层。详见
`code-reuse-optimization.md` R1（含复核修订：保留惰性语义、补 2 个 delegate 测试文件）。

**与性能的关系（新增）**：删层同时消掉**每个转发方法的一次属性查找 + 一次函数调用**，
以及 `ResearchDelegate.__init__` 里 `data_dir` 的持有开销。但**收益很小**（转发是纳秒级），
**这条完全按「减少重复 + 收窄 API 面」驱动，不要按性能驱动**。

**预计收益**：删 468 行；转发 487 → ~240 行。**优先级 P1（独立 PR）。**

---

### U4 — `apps/research/db.py` 的 `get_sub_queries` / `get_sources`

**位置**：`apps/research/db.py:431` + `:509`

**重复表现**：同一套「`SELECT *` → `row_factory = sqlite3.Row` → 逐行 `dict(r)` →
`json.loads` 解 `result` 字段（失败则保留原值）」模式。

**是否建议提取**：✅ 建议，但**只抽 JSON 解码那一段**，不要把两个查询合并成一个通用查询函数 ——
两者的表、过滤条件、返回字段不同，合并会造出 if/else 开关。

```python
# apps/research/db.py —— 模块级私有
def _decode_row(r: sqlite3.Row) -> dict:
    """把一行结果转 dict，并解码 JSON 字段（失败保留原值）。"""
    d = dict(r)
    if d.get("result"):
        try:
            d["result"] = json.loads(d["result"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d
```

**参数设计**：只收 row，不收表名/字段名（避免参数化过度）。

**依赖与副作用**：`json.loads` 失败静默保留原值 —— **这是现状语义，必须保留**。

**测试**：两个方法各自覆盖「result 是合法 JSON / 非法 JSON / None」三态。

**风险点**：低。**优先级 P2。**

---

### U5 / U6 / U7 / U8 / U9 / U10 — 逐字重复的小型提取

| ID | 提取方式 | 注意 |
|----|---------|------|
| **U5** `_build_merge_notice` | 后者调前者；**同时把私有名改为公开 `build_merge_notice`**（跨模块 import 下划线私有名是 smell）。依赖方向已验证安全：`kernel/wiki/mixins/core/utility.py:11` 本就 import `kernel.storage.backend`，而 `backend.py` 不反向 import `kernel/wiki` | ⚠️ 它在 `kernel/storage/backend.py:437`，**热路径**（见 §5 P5）—— 提取时保持纯函数、零分配 |
| **U6** `_format_run_not_found` | 提到 `apps/chat/skills/errors.py`（已有同族模块） | 纯字符串格式化，冷路径，随便提 |
| **U7** crud skills `_get_*` ×5 | 提一个 `get_dependency(kind)` 辅助；**不要建"五个 skill 的通用基类"** | 5 处每处只有 4 行 payload；用一个参数化 helper 即可，别上继承 |
| **U8** `_search_youtube`/`_search_news` | 提 `_search_video_platform(platform)` | 注意两者 URL 模板/参数不同 —— 参数化要留出差异位 |
| **U9** `list_tools` | 提 `build_tool_specs(tools)` | 两个实现的工具来源不同（wiki tools vs skill tools）—— 抽"组装 spec"那段，**不要**合并数据源 |
| **U10** `get_mcp_config`/`get_search_config` | 提 `_load_config_section(name)` | 配置加载在**启动/初始化**路径（见 §5 P7）—— 提取后保留惰性，不引入 import 期 IO |

**统一优先级**：P2。**统一原则**：这些都是"抽 3–18 行纯函数"，**不做类、不做继承、不做注册表**。

---

## 4. 不建议提取清单及原因

| 候选 | 不提取理由 |
|------|-----------|
| `apps/chat/agent/protocols.py` 的 4 组 Protocol 方法 | **抽象桩** —— 方法体全是 `...`，payload = 0 行。docstring 口径看着 45 行，实际无一行逻辑。抽它 = 抽文档 |
| `agent_runner.execution_context` + `ChatDBBase._init_schema` + `BaseDatabase._init_db` | 同上，三个抽象桩，payload 各 2 行（`raise NotImplementedError`）。**这三个方法名和语义都不同**（一个是上下文访问器，两个是建表钩子），抽公共基类会造出错误的 is-a |
| `apps/chat/agent/unified/handlers/chat_reasoner.py` 的 `execution_context` | 与 `kernel/agent/loop.py:292` 语义重复，但 **runner_v2 是 kernel 的薄封装**（payload 仅 8–10 行）。收益 < 抽象成本，**降级到不做** |
| `foundation/extractors/` 7 个模块的公共壳 | 7 个提取器**输出契约不同**（`ExtractedContent` 字段组合各异）。抽公共基类会产生大量 `if` 分支 —— 正是约束里点名的反模式 |
| `apps/research/` 5 模块环内的引擎骨架 | `engine/gates/observer/reasoner/resume` 是**有意的循环依赖**（ReAct 阶段互相回调），强行拆开会破坏 ReAct 语义。**保持现状 + 文档化** |
| `apps/chat/skills/` 大量 `Skill` 子类的 `name`/`help`/`run` 骨架 | 插件式架构的**契约**，不是重复。`SkillRegistry` 的存在就是为了让它们互不相同 |
| `interfaces/cli/_app.py` 的 `WikiCLI` 23 个转发方法 | 每个方法调**不同的**命令函数 —— 这是**表驱动 dispatch** 候选（可用一张 `{name: fn}` 表替代 23 个方法体），但那是**另一种重构**（注册表化），不是"抽公共函数"。建议单独立项，优先级低 |
| 任何"万能 CommonUtils" | 约束明令禁止。本方案**没有**提出任何此类建议 |
| `apps/chat/db` 三层的**再抽一层** | U3 的正确解法是**删层**。抽公共函数 = 四层，更糟 |

---

## 5. 关键性能点清单与瓶颈证据

> 证据等级：**E1** = 仓库内已有基准脚本/历史修复佐证 · **E2** = 源码级静态可达性 · **E3** = 需运行时确认

| ID | 性能点 | 位置 | 瓶颈证据 | 级别 | 耦合问题 |
|----|-------|------|---------|:---:|---------|
| **P1** | **LLM 分派 ×3 + 每次调用新建 HTTP 连接** | `runner_v2.py:924` / `chat_reasoner.py:201` / `base.py:463`；`foundation/llm/streamable.py:411,559,690`；`foundation/llm/connection.py:398` | 每次 LLM 调用新建 `httpx.Client`/`AsyncClient` → **每次 TCP+TLS 握手**；`LLMClient.__init__` 不持有 session 对象。**无任何响应缓存 / prompt 缓存**（全仓 grep `response_cache\|cached_response\|llm_cache\|cache_hit\|prompt_cache` **零命中**） | **E2** | 分派逻辑重复 3 份（U1）+ client 生命周期藏在构造函数里，**无法替换实现、无法基准测试** |
| **P2** | **`get_connection()` 按 path 单例吞掉 PRAGMA 策略** | `foundation/db.py:276-296` | 注册表 key = `str(db_path)`，`**kwargs` **仅首次创建生效**。Chat/Wiki/Research 共用同一 `.llmwiki_agent.db` → **谁先构造谁决定整进程策略**。`AutoResearchDatabase.__init__`(`_facade.py:734-740`) 先 `super().__init__()`（Chat，默认 FK=ON）→ research 的 `foreign_keys=False`（`apps/research/db.py:59`，docstring `:76-83` 明说"故意关闭"）**被静默丢弃** | **E2** | 连接策略不是数据而是"第一个构造者的副作用" —— 换构造顺序就换语义，**不可测** |
| **P3** | **`async def` 路由里跑同步重活** | `wiki_routes.py:57`(status) `:118`(lint) `:128`(recommend) `:148`(guide) `:113`(sink_status) | FastAPI：sync `def` → 线程池；**`async def` → 事件循环线程**。`/graph`(`:150`)/`/graph_analyze`(`:143`) 已是 sync `def`（`6f44e8b8` 修过），**其余全是 `async def`**。<br>· `/status` → `wiki.status()`(`status.py:46-98`) = **3 次文件系统遍历**(`_wiki_pages` / `raw_dir.rglob` / 每子目录 `rglob`) + 2 次 SQL + **每次请求 `RelationEngine.__init__` 跑 DDL**(`relation.py:96-98`)<br>· `/lint` → `wiki.lint()` → **同步 LLM 调用**（`analyzer.py:508` `_llm_detect_gaps` → `:321` `client.chat_json`） | **E2** | 业务逻辑与执行位置耦合：**handler 里直接调重活**，没有"这个操作该在哪个线程跑"的表达位 |
| **P4** | **lint 管线重复遍历/重复读取** | `kernel/wiki/lint/__init__.py:66-71`(`Rule.run`) · `:112-122`(`_load_pages`) · `analyzer.py:58-67`(`_scan_all_pages`) · `:500`(`_build_lint_context`) | 8 条规则里 **6 条是普通 `Rule`**，各自 `_wiki_pages()`+`read_text()`，且**在 `max_results` break 之前读**（`lint/__init__.py:66-71`）→ 零命中的规则也读满全量。`shared_pages`(`:176-185`) 只有 2 条 `CrossPageRule` 共享。<br>`_build_lint_context`(`analyzer.py:226-301`) **在 `if core is None:` 块之外**(`:500`) → **缓存命中也照跑**：读 `wiki.md` + `_get_existing_page_names()` rglob + `raw_dir.rglob` + 最多 20 次 `_find_source_summary_page`（其内部再 `sources_dir.rglob` + 逐页 `read_text`）→ **O(raw × sources)** | **E2** | 页面读取散在 5 个地方各写一遍 rglob/read_text，**没有统一的"页面快照"概念** |
| **P5** | **`add_relations`：O(N) 提交 + O(N) 全树遍历** | `kernel/wiki/engines/relation.py:456-472` | 循环 `add_relation`；每次 `resolve_entity`(`:259`) → `_get_wiki_pages()`(`:143`) **`wiki_dir.rglob("*.md")` 全树遍历** + 5 次 SELECT；再加去重 SELECT(`:417-425`) + INSERT(`:430`) + **COMMIT**(`:443`)，`add_alias` 再 COMMIT(`:358`)。<br>⇒ 每条 relation ≈ **2 次全树遍历 + ~10 SELECT + 1–2 次 fsync** | **E2** | 实体解析、查重、写入、事务边界全在**一个方法**里 —— 无法单独基准测试，也无法换成批量实现 |
| **P6** | **缓存失效是全局的 + key 空间混用** | `kernel/graph/cache.py:167-182` · `interfaces/server/core.py:374-378` | 文件监听回调 `cache_invalidate()` **无参** → 清空**全部** wiki 的 `_STORE` + `_FP_MEMO`。<br>另：`_STORE` key 用 `str(wiki.root)`(`cache.py:120-121`) 而 `cache_invalidate(str(self.wiki_dir))`(`backend.py:163,171` / `link.py:127` / `index.py:596`) → **key 不匹配，该调用对 `_STORE` 是 no-op**（目前靠指纹变化兜住，属**潜伏陷阱**） | **E2** | 失效策略（全局 vs 按 wiki）没有表达位；`wiki_key` 与 `wiki_dir` 两个概念共用一个字符串参数 |
| **P7** | **启动期/客户端构造期的同步网络 IO** | `foundation/llm/context_windows.py:89` `requests.get(...)`（5s 超时）· 经 `token_budget.py:69`→`context_windows.py:160`→ `StreamableLLMClient.__init__`(`streamable.py:157`) / `LLMClient.__init__`(`base.py:113`) | 客户端**构造时**就发同步 HTTP；从 async 路径可达（`apps/wiki/service.py:89-107` `get_llm()` ← `bridge_backend.py:106` 在 async `_llm_stream_with_retry` 内）→ **事件循环上 5s 超时的同步 GET** | **E2** | 客户端构造 = 「配置解析 + 内存探测 + 网络探测」三件事捆在一起，**无法离线构造、无法预热** |
| **P8** | **聊天 LLM 路径无并发上限** | 唯一 semaphore 在 `apps/agent/maintenance/__init__.py:32,47`（`LLM_CONCURRENCY=3`，仅后台维护用）。聊天侧：`subagent_manager.py:124` cap=2（限的是 subagent 不是 LLM 调用）· `dag.py:181` `max_concurrent_agents=8` · `gatherer.py:396-400` cap=8（限 sub-query）。**限流只靠传输层 429 重试**(`connection.py:442`) | 五处各自为政的并发上限，没有一个统一的"LLM 调用闸门" | **E2** | 并发策略散落各处，**改一个旋钮要动 5 个文件** |
| **P9** | **三层重试叠加** | 传输层 `foundation/llm/connection.py:65,130`（3 次，base 1.0/factor 2.0/jitter 0.5，状态 {429,500,502,503,504}）· 应用层 `apps/chat/retry_managers.py:198`（3 次，base 2.0s，`asyncio.wait_for` 120s，**按异常消息字符串判可重试** `:182-195`）· 工具层 `apps/chat/agent/tool_executor.py:167`（首 chunk 重试） | 最坏情况**一轮对话 ≈ 3×4×2 = 24 次上游请求**；且工具层重复重试传输层已处理过的首连失败 | **E2** | 重试策略没有单一所有者，外层不知道内层重试过什么 |
| **P10** | **事件循环上的 `time.sleep`** | `foundation/llm/connection.py:423,461` · `foundation/llm/streamable.py:445,488` | 同步退避 sleep。**是否落在事件循环线程上取决于可达路径** —— 与 P1/P3 组合时可达 | **E3** | 同步退避与异步编排混用 |
| **P11** | **`asyncio.gather` 无界扇出** | `apps/chat/gatherer.py:199-200` | 对 sub-query 里**所有 URL** 直接 `gather(*tasks)`，无 semaphore（`:400` 的 cap 限的是 sub-query 数 8，不是 URL 数） | **E2** | 扇出规模与信号量分离 |
| **P12** | **模块级 `asyncio.Lock` 单例跨事件循环** | `apps/research/base.py:50` `_WIKI_LOCKS` · `apps/api/openai_server.py:278` | import 期创建；Python ≥3.10 惰性绑定首个 loop → 跨 loop 复用会 "bound to a different event loop" | **E3** | 全局锁字典无 owner、无淘汰（`apps/research/routes.py:90` `_ENGINE_CACHE` 同样无界） |
| **P13** | **每次 lint 调用重算 token（~2×）** | `foundation/llm/budget_decorator.py:59-61` → `token_budget.py:91`（`count_messages` 全量分词）+ `:95-99`（**再逐条 `count_tokens` 求 max**） | 每次 LLM 调用前对整段 prompt **分词两遍**，且只用于日志（`token_budget.py:130-152`）。tiktoken `encode` 在长 prompt 上是纯 CPU 开销 | **E2** | 预算检查与日志耦合在调用链上，无法单独关闭 |
| **P14** | **读操作开事务 + 双提交** | `apps/research/db.py` 全部方法用 `with self._connect() as conn:`，而 `_connect()`(`:67-85`) 返回**共享** conn（`sqlite3.Connection.__exit__` 只提交/回滚，**不关闭**），方法内又显式 `conn.commit()`（18 处） | 读方法也开事务；每次写 **2× 提交** | **E2** | 事务边界在代码里不可见（靠 with 隐式 + 显式 commit 叠加） |
| **P15** | **线程局部连接在 worker 线程永不关闭** | `foundation/db.py`（`threading.local`）+ `close()` + `close_all()`（atexit） | `close_all()` 只看**调用线程**的槽位 → HTTP 线程池里每个用过 DB 的线程都留一个打开的 SQLite 句柄（含 WAL/shm） ｜ ⚠️ 2026-10-27：`close_all()` **有意保持线程内语义**（跨线程关闭会打断在途写操作）；已新增 `close_all_threads()` 作显式跨线程释放通道，并解决 sqlite3 `check_same_thread` 拒绝跨线程 close 的问题 ｜ **E3** | 连接生命周期 = 隐式 thread-local，无显式 owner；**根治仍需 worker 线程自己 close** |
| **P16** | **admin 统计 N+1** | `apps/chat/db/admin_stats_repo.py:52-64`（6× `COUNT(*)`）· `:185-193`（11× `COUNT(*)` + `stat()`）· `:117-120`（同一组 `sqlite_master` 探针重复 10 次） | 11 次全表扫描 | **E2** | 每个统计一个查询，没有批量聚合入口 |

---

## 6. 高优先级性能剥离详细方案

### P1 — 把 LLM 调用收敛到一个可替换、可基准的 Dispatcher + Transport

**位置与瓶颈证据**：见 §5 P1、P9、P10、P13（四个点共用同一个根）。

**当前耦合问题**
- 分派逻辑 3 份（U1）→ 策略变更要改 3 处；
- HTTP client **每次调用新建** → 无法复用连接、无法注入假 transport 做基准；
- 超时在流式路径**硬编码**（`streamable.py:412,560` `httpx.Timeout(connect=30, read=300, write=30, pool=30)`），
  而 `self.request_timeout_seconds` 只在 `chat_with_tools`(`:359`) 生效；
- 重试 3 层叠加（P9），外层不知道内层已重试；
- 分词预算在每次调用前跑 2 遍（P13），只用于日志。

**建议剥离边界**

| 层 | 类型 | 位置 | 职责 |
|----|------|------|------|
| `LLMDispatcher` | **接口 + 单一实现** | `apps/chat/agent/llm_dispatcher.py` | 选路 + 指标（= U1） |
| `LLMTransport` | **接口**（Protocol） | `foundation/llm/transport.py` | 「发一个请求 → 收一个响应」；**生产实现用 httpx，测试实现用 fake** |
| `TimeoutPolicy` | **数据**（dataclass） | `foundation/llm/` | 一次解析，四处生效；替代硬编码 |
| `RetryPolicy` | **接口** | `foundation/llm/retry.py` | `should_retry(exc, attempt, phase)` + 尝试元数据，让外层不重复重试 |
| `TokenAccounting` | **服务** | `foundation/llm/` | 按 message 记忆分词结果 + max 采样，替代 2× 全量分词 |

**建议的接口签名**

```python
# foundation/llm/transport.py
class LLMTransport(Protocol):
    def post_stream(self, url: str, payload: dict, timeout: TimeoutPolicy) -> Iterator[bytes]: ...
    def post_json(self, url: str, payload: dict, timeout: TimeoutPolicy) -> dict: ...

# foundation/llm/ — 客户端持有 transport，不再每次新建
class StreamableLLMClient:
    def __init__(self, spec: LLMSpec, transport: LLMTransport | None = None) -> None:
        self._transport = transport or HttpxTransport()   # 可注入 → 可基准、可假
```

**数据流**

```
runner_v2 / chat_reasoner / base
        │  messages, tools
        ▼
  LLMDispatcher.stream()          ← 唯一选路点（U1）
        │  选路 + 指标
        ├──► chat_service._llm_stream_with_retry  (路径1)
        ├──► client.astream_chat(...)             (路径2)
        └──► client.chat(...)                     (路径3 兜底)
                 │
                 ▼
         StreamableLLMClient
           ├── TokenAccounting.check()   ← 记忆化分词（替 2× 全量）
           ├── RetryPolicy.should_retry()← 单一重试所有者（替 3 层叠加）
           └── LLMTransport.post_stream()← 复用连接（替每次新建）
```

**性能约束**
- **复杂度**：`TokenAccounting` 从 O(2×tokens) → O(新消息 tokens)；`RetryPolicy` 单次决策 O(1)。
- **内存**：transport 持有**单个**长连接（keep-alive）→ 连接数从「每次调用 +1」降到「每进程 +1」。
- **并发**：`LLMDispatcher` 可注入一个 `asyncio.Semaphore`（P8 的统一闸门）。
- **超时**：`TimeoutPolicy` 一次解析（`resolver.py:241` 默认 120s），**四处路径统一**，
  不再有 300s 硬编码。
- **批量**：不涉及。

**需要的基准测试 / 压测**
1. `benchmark_llm_dispatch` —— 三条路径各产出**同一事件序列**（fake transport，零网络）。
2. `benchmark_transport_reuse` —— N 次调用 vs N 次建连的耗时/连接数对比（用 fake transport 计调用数）。
3. `benchmark_token_accounting` —— 10k-token prompt，记忆化 vs 现状 2× 分词的耗时比。
4. `benchmark_retry_policy` —— 注入 429/500/超时，断言**总上游请求数**从 24 降到预期值。

**监控指标与告警**
| 指标 | 类型 | 告警建议 |
|------|------|---------|
| `llm_call_total{prompt_name, path}` | counter | — |
| `llm_call_duration_seconds` | histogram | p99 > 60s 告警 |
| `llm_upstream_requests_total` | counter | **与 `llm_call_total` 比值 > 2 告警**（暴露重复重试） |
| `llm_retry_total{reason}` | counter | 429 突增 → 触发并发闸门 |
| `llm_cache_hit_ratio` | gauge | 新增缓存后 < 0.3 说明 key 设计有问题 |
| `llm_concurrency_inflight` | gauge | > cap → 闸门失效 |

**风险点、兼容性、回滚**
- 风险：**改 transport = 改所有 LLM 行为**。必须**逐路径**切换，禁止一次性换。
- 风险：重试收敛后，**上游错误暴露频率会上升**（原本被多层重试掩盖）→ 需要告警配套。
- 回滚：`transport` 默认实现 = 现有 httpx 逻辑，**注入点默认关闭** → 单参数回滚。

**优先级：P0**（与 U1 合并为一个 PR —— 它们是同一处代码）

---

### P2 — 连接策略从「构造顺序的副作用」变成「显式的数据」

**位置与瓶颈证据**：§5 P2（`foundation/db.py:276-296`）

**当前耦合问题**：`get_connection(path, **kwargs)` 用 path 做单例 key，kwargs 只在首次生效。
于是**连接策略 = 谁先构造**，而不是**调用方声明了什么**。
`AutoResearchDatabase` 先建 Chat → research 的 `foreign_keys=False` 被静默丢弃，
而 `apps/research/db.py:76-83` 的 docstring 明说 FK 是"故意关闭"的 —— **代码与文档相反**。

**建议剥离边界**：**接口 + 显式 profile**

```python
# foundation/db.py
@dataclass(frozen=True)
class ConnectionProfile:
    """连接 PRAGMA 策略。显式声明，不靠构造顺序。"""
    foreign_keys: bool = True
    wal: bool = False
    busy_timeout: int | None = None
    synchronous: str | None = None

PROFILE_DEFAULT = ConnectionProfile()
PROFILE_RESEARCH = ConnectionProfile(foreign_keys=False, wal=True,
                                      busy_timeout=5000, synchronous="NORMAL")
```

```python
def get_connection(db_path, profile: ConnectionProfile = PROFILE_DEFAULT) -> ManagedConnection:
    """按 (path, profile) 单例。同 path 不同 profile → 不同连接。"""
    key = (str(db_path), profile)
    ...
```

**为什么用 `(path, profile)` 而不是把 profile 并进 path**：
`PRAGMA foreign_keys` 是**连接级**而非文件级属性。同一文件的两条连接可以有不同的 FK 策略。
research 需要 FK 关、chat 需要 FK 开 → **两条连接、同一文件**，正是 SQLite 的正确用法。

**接口签名与数据流**

```
ChatDatabase      → get_connection(db_path, PROFILE_DEFAULT)   → FK ON
ResearchDatabase  → get_connection(db_path, PROFILE_RESEARCH)  → FK OFF, WAL, busy_timeout
WikiDatabase      → get_connection(db_path, PROFILE_DEFAULT)   → FK ON
```

**性能约束**
- 连接数从「每 path 1 条」变成「每 (path, profile) 1 条」→ **+1 条连接**（可接受）。
- WAL 是**文件级**的：research 先开 WAL 后，chat 连接也会看到 WAL 模式（SQLite 特性），
  所以 `wal=True` 放 research profile 上实际会影响 chat —— 需在评审时确认这是否可接受。
- `busy_timeout=5000` 同理是连接级，只有 research 连接有 → **chat 的写竞争无超时保护**，
  需评估是否要把 busy_timeout 提到默认 profile。

**需要的测试**
1. `test_research_profile_disables_fk`：research profile 的连接 `PRAGMA foreign_keys` == 0。
2. `test_default_profile_enables_fk`：default profile == 1。
3. `test_profile_isolation`：两个 profile 拿到**不同的** `ManagedConnection` 实例但同一文件。
4. `test_research_insert_allows_orphan_fk`：research 写入违反 FK 的 fixture **不报错**
   （这是 `research/db.py:76-83` 描述的语义，**必须回归**）。

**监控指标与告警**
- `db_connection_count{profile}` gauge —— profile 维度，防止 profile 无限增长。
- `db_fk_violation_total` counter（research 连接）—— 若 > 0 说明 profile 没生效。
- `db_busy_timeout_total` counter —— 写竞争信号。

**风险点、兼容性、回滚**
- 风险：**改变了 research 的实际 FK 行为**（从「实际 ON」变成「文档说的 OFF」）。
  这可能让原本能通过的写入开始失败 —— **但那正是文档承诺的行为**，属 bug 修复。
  **必须先跑全量测试确认没有依赖 FK=ON 的 research 路径**。
- 风险：WAL / busy_timeout 的副作用如上。
- 回滚：`profile` 参数默认 `PROFILE_DEFAULT` 且**按旧 key 单例** → 改回去即可。

**优先级：P0**（正确性缺陷，收益不在性能）

---

### P3 — 给「重活」一个明确的执行位置（线程池 vs 事件循环）

**位置与瓶颈证据**：§5 P3

**当前耦合问题**：`async def` handler 里直接调同步重活。**代码里没有任何地方能表达
"这个操作该在哪个线程跑"** —— 只能靠读者自己知道 FastAPI 的 sync/async 规则。
`/graph` 已经被修成 sync `def`（`6f44e8b8`），但 `/status` `/lint` `/recommend` `/guide` 仍是 `async def`。

**建议剥离边界**：**接口 + 适配器**（不是"把函数挪走"）

```python
# kernel/wiki/protocols.py（或新增 kernel/wiki/snapshot.py）
class WikiStatusProvider(Protocol):
    """提供 wiki 状态快照。实现可同步可异步；调用方不关心。"""
    def snapshot(self) -> WikiStatusSnapshot: ...
```

```python
# kernel/wiki/snapshots.py
class LocalWikiStatusProvider:
    """本地实现：跑文件系统遍历 + SQL。**必须**在 worker 线程调用。"""
    def snapshot(self) -> WikiStatusSnapshot: ...
```

**建议的接口签名与数据流**

```
routes.py:
    @wiki_router.get("/status")
    def wiki_status(wiki = Depends(get_wiki)):      # ← 改 sync def（进线程池）
        return enrich_status(wiki.status())

    @wiki_router.get("/lint")
    def wiki_lint(mode="check", limit=10, force=False, wiki = Depends(get_wiki)):
        return wiki.lint(mode=mode, limit=limit, force=force)
```

**为什么改 sync `def` 而不是 `await asyncio.to_thread(...)`**：
- FastAPI 对 sync `def` 自动用线程池，**零额外代码**；
- `to_thread` 需要在每个 handler 显式写，且**默认线程池同样是 AnyIO 的 40 线程** —— 不解决 GIL 问题；
- 改 `def` 与 `/graph` 现有写法一致，**风格统一**。

**⚠️ 但要注意**：sync `def` 只解决**阻塞事件循环**，**不解决 GIL 争用**。
`/status` 的 3 次文件系统遍历 + DDL 主要是 IO（释放 GIL），改 sync `def` 收益明显；
但 `/graph` 的纯 Python 建图是**真 CPU**，改 sync `def` 后仍会与事件循环争 GIL ——
所以 P3 之后仍需要 P4（减少工作量）。

**性能约束**
- IO 密集（status/lint/recommend）：线程池足够，**GIL 释放**，无争用。
- CPU 密集（graph/graph_analyze）：**需要独立的有界 CPU 执行器**（P4/§6 P-extra），
  否则 40 个并发 graph 会打满 Starlette 默认线程池 + 争 GIL。
- `/lint` 里的 **LLM 调用**（`analyzer.py:508`）即使在 worker 线程也**会占住一个线程几十秒** →
  线程池会被 lint 请求占满。**必须配合缓存命中率提升（P4）**，或给 lint 单独的池。

**需要的基准测试**
1. `benchmark_status_snapshot` —— `wiki.status()` 墙钟耗时（1500 页规模）。
2. `benchmark_event_loop_responsiveness` —— 并发 N 个 `/status` 时，事件循环线程的
   **最大单次阻塞**（这才是用户体感）。
3. `bench_http_with_graph_inflight`（**仓库已有** `scripts/repro_bench_graph.py:111-127`）——
   **注意：这个脚本的前提已经反了**（它把 status 当对照组，但 status 才是阻塞的那个）。
   需要重写为「graph 在飞行时，status 的 p95」。

**监控指标与告警**
| 指标 | 告警 |
|------|------|
| `http_request_duration_seconds{route}` | `/status` p99 > 1s |
| `event_loop_lag_seconds` | > 0.5s → 告警（**直接对应用户体感**） |
| `threadpool_active_threads` | 持续 > 32/40 |
| `wiki_status_duration_seconds` | p99 > 2s |

**风险点、兼容性、回滚**
- 风险：sync `def` 会在**请求上下文**里跑同步代码 —— 若其中用了 `contextvar`
  或依赖 async-only 的上下文，行为会变（Starlette 的线程池不复制 contextvar）。
  **需审计 `/status` `/lint` 调用链里的 contextvar 使用**。
- 风险：线程池打满 → 排队而非崩溃 → 必须配上面板。
- 回滚：改回 `async def` 即可（单行）。

**优先级：P0**（与 P1/P2 并列，且**改动最小** —— 改 5 个 `async def` → `def`）

---

### P4 — 一次 lint，一份页面快照

**位置与瓶颈证据**：§5 P4

**当前耦合问题**：页面读取散在 5 处，各写一遍 `rglob` + `read_text`；
**没有「页面快照」这个概念**。`shared_pages` 只在 2 条 `CrossPageRule` 之间共享，
6 条普通 `Rule` 各自重读；`_build_lint_context` 更是在缓存命中时也重跑。

**建议剥离边界**：**接口 + 快照对象**

```python
# kernel/wiki/snapshot.py
@dataclass(frozen=True)
class PageSnapshot:
    """一次 lint 运行内所有页面内容的不可变快照。"""
    names: tuple[str, ...]
    contents: Mapping[str, str]      # 只读映射

class PageSource(Protocol):
    """提供页面快照。实现决定遍历与读取策略（可缓存、可预热、可假）。"""
    def snapshot(self, *, exclude: Callable[[Path], bool] | None = None) -> PageSnapshot: ...
```

**数据流**

```
LintEngine.run_all()
   │
   ├─► snapshot = page_source.snapshot()          ← 一次遍历 + 一次读取
   │      （普通 Rule 与 CrossPageRule 共用；RunRule 传入 snapshot）
   │
   ├─► _scan_all_pages()  ← 改用同一 snapshot 的 contents，不再重读
   ├─► _build_lint_context() ← 改用同一 snapshot 的 names，不再 rglob
   └─► 规则只做纯计算，不再碰文件系统
```

**性能约束**
- **复杂度**：从 `O(规则数 × 页面数)` 次读降到 `O(页面数)` 次读。
  6 条普通 Rule + 2 条 CrossPage + `_scan_all_pages` ≈ **8 次全量读 → 1 次**。
- **内存**：`PageSnapshot` 持有全量内容 = **O(总字节)**。1400 页 × ~4KB ≈ 5.6 MB，可接受；
  但**必须设上限**（如 > 200MB 降级为流式/分块），否则大 wiki 会 OOM。
- **并发**：快照是不可变对象 → **可跨线程共享**，无锁。
- **超时**：快照构建是 IO 密集 → 走 worker 线程（P3）。

**顺带修掉的两个缺陷**（评审时一并处理）

1. **`except TypeError` 无效重试**：`lint/__init__.py:118-121` 与 `analyzer.py:63-66` 都是
   ```python
   try:  page.read_text(encoding="utf-8")
   except TypeError: page.read_text(encoding="utf-8")   # ← 参数完全相同，不可能成功
   ```
   两次都传了 `encoding=`，说明这处 `TypeError` 兜底是历史残留（早期签名不同）。
   **且它没捕获 `UnicodeDecodeError`** → 一个非 UTF-8 文件会让整次 lint 崩掉。
   项目里已有正确写法：`foundation/io.py:50-66` `safe_read_text`、
   `kernel/storage/index.py:181` `read_text(errors="replace", encoding="utf-8")`。
   → **统一走 `safe_read_text`**。

2. **`_build_lint_context` 的 O(raw × sources) 嵌套**：`analyzer.py:250-252` 对最多 20 个 raw 文件
   各调一次 `_find_source_summary_page`，其内部 `sources_dir.rglob("*.md")` + 逐页 `read_text`
   → **O(raw × sources) 次读**。
   → 改为**先建一次 `raw_file → source_page` 映射**（`SourceIndex`）再查表。

**需要的基准测试**
1. `benchmark_lint_snapshot` —— 1400 页：现状 vs 快照版的**总读文件数**与墙钟。
   断言：快照版 `read_text` 调用次数 == 页面数（用 counter/fake source 断言，不测时间）。
2. `benchmark_lint_context_build` —— `_build_lint_context` 的 raw×sources 读次数。
3. `test_lint_handles_non_utf8_page` —— 写一个含非法字节的页面，**断言 lint 不抛异常**
   （当前会崩 —— 这是回归测试）。

**监控指标与告警**
- `lint_duration_seconds{stage}` histogram —— stage 细分：`snapshot` / `rules` / `context` / `llm`。
- `lint_pages_read_total` counter —— **直接监控 IO 放大**，异常增长即回归。
- `lint_snapshot_bytes` gauge —— 逼近上限时告警。

**风险点、兼容性、回滚**
- 风险：**规则签名变更**（`detect(page_name, content, wiki, results)` → 需要 snapshot 或预加载内容）。
  影响 8 条规则 + 它们的测试。
- 风险：**内存**。必须设上限并有降级路径。
- 风险：规则若依赖「读取时看到最新文件」，快照会引入**一致性延迟** ——
  但 lint 本身就是一次快照语义，可接受。
- 回滚：保留旧 `Rule.run` 路径做开关（`_use_snapshot`），**逐条规则切换**。

**优先级：P1**（收益最大，但改动面比 P1/P2/P3 大）
**建议拆分**：P4-a 只做 `_build_lint_context` 的缓存 + `safe_read_text` 统一（低风险，~30 行）；
P4-b 再做全量快照（改 8 条规则签名）。

---

### P5（附加）— `add_relations` 批量化

**位置**：`kernel/wiki/engines/relation.py:456-472`

**瓶颈证据**：§5 P5 —— 每条 relation 2 次全树遍历 + ~10 SELECT + 1–2 次 fsync。

**建议剥离边界**：**模块 + 接口**

```python
class RelationStore(Protocol):
    def add_relations_bulk(self, relations: Sequence[RelationInput]) -> int: ...
```

**约束**
- 实体解析：把 `_get_wiki_pages()`(`:143`) 的 rglob **提到循环外**（预加载页名集合一次）
- 提交：循环内**不 commit**，循环结束 commit 一次
- 保持 `add_relation` 单条 API 不变（供小批量路径用），新增批量 API

**性能约束**：从 `O(N × 页面数)` → `O(页面数 + N)`；提交从 N 次 → 1 次。

**测试**：批量结果 == 逐条结果（顺序无关，去重后集合相等）；空输入不报错。

**回滚**：新增方法是纯增量，旧路径保留。

**优先级：P2**（取决于生产里单次 relation 写入量 —— **这是 G1/G2 缺口**）

---

## 7. 不建议剥离清单及原因

| 性能点 | 不剥离原因 |
|--------|-----------|
| **`kernel/graph/cache.py` 的指纹缓存** | **已经设计得很好**：`graph_fingerprint` = 3 个 `COUNT/MAX` 查询；`file_fingerprint` = `os.scandir` 单趟 stat + **600s memo**。指纹比它守护的工作**便宜得多**。不要动结构。<br>⚠️ 唯一可改：DB 侧那 3 个 COUNT **没被 memo**（`_FP_MEMO` 只 memo 文件侧）。可加 5–10s memo，但**收益小**，且要防「DB 变了但 memo 未过期」—— **不建议现在做** |
| **`build_graph` 的 O(E) 字典去重** | **已修**（`6f44e8b8`，`kernel/graph/export.py:24`）。`repro_bench_graph.py:22-60` 已固化为基准。**不要重写** |
| **`missing_cross_ref` 的 O(N²) → O(N)** | **已修**（`kernel/wiki/lint/rules/missing_cross_refs.py:41` 注释：150s → 秒级）。不要动 |
| **`LintEngine` 的 `CrossPageRule` / `shared_pages` 机制** | **已有的正确抽象**。P4 是**扩展**它（让普通 Rule 也能用），不是重写 |
| **`foundation/llm/connection.py` 的传输层重试** | 传输层重试（连接级失败）语义正确，**只是不该被外层重复**。方案是加 `phase` 让外层知道，不是不做 |
| **`kernel/codegen/code_tools.py:167-171` 的 sandbox `join(timeout=120)`** | 生成代码在**独立线程**跑（`threading.Thread` + `join`），**不占事件循环**，只是阻塞调用方线程。执行不可信代码**必须**隔离到进程/容器 —— 抽成"更干净的接口"不降低风险。**先做沙箱强度评估，不做接口剥离** |
| **`apps/chat/skills/workflows/executor.py` 的 `ThreadPoolExecutor`** | DAG 阶段并发，**已有界**（`max_concurrent_agents`）。`time.sleep` 在池内线程，**不占事件循环**。无需剥离 |
| **`apps/agent/maintenance/__init__.py` 的 `LLM_CONCURRENCY=3` semaphore** | 后台维护任务的限流，**已正确**。P8 建议的是给**聊天主路径**加闸门，不是改这个 |
| **`apps/chat/gatherer.py` 的 8 路 sub-query 并发** | 有界且合理。真正的问题是 **URL 级扇出无界**（`:199-200`），那是**加信号量**（1 行），不是"剥离" |
| **`apps/research/base.py` 的 `_WIKI_LOCKS` / `routes.py` 的 `_ENGINE_CACHE`** | P12 的问题是**跨事件循环复用**（E3 待验证）+ **无界缓存**。修法是 per-loop registry + 淘汰策略，**不是接口剥离**（没有调用方需要换实现） |
| **把 `wiki.status()` 的 3 次遍历合并成 1 次** | 比 P4 更省，但**风险更高**：`status()` 返回的 `pages_by_type` 需要**分类**（按子目录），合并遍历要重建这个语义。先做 P4（快照），分类逻辑自然收敛 |
| **`admin_stats_repo` 的 N+1 统计** | 冷路径（管理接口），用户无感。**改成一条聚合 SQL** 即可，不需要"剥离接口" |
| **`graph_fingerprint` 的 DB 侧 memo** | 见上。收益小、风险（陈旧指纹）大于收益 |
| **为 `Wiki` / `SkillContext` 等 god-node 拆分** | 组合根与数据类，**高扇入是设计意图**。拆分是"大文件治理"议题，与复用/性能无关，另议 |

---

## 8. 复用与性能冲突判定及处理顺序

### 8.1 同时命中「重复热点 ∩ 性能热点」的代码

| ID | 位置 | 重复性质 | 性能性质 | **处理顺序** |
|----|------|---------|---------|-------------|
| **U1 / P1** | LLM 三处分派 + 每次新建 client | 语义重复（~50 行 × 3） | 每次调用 TCP+TLS 握手；3 层重试；2× 分词 | **先性能隔离，后复用**：<br>① 先建 `LLMTransport` 注入点（transport 默认实现 = 现状，零行为变化）→ **此时已能基准测试**<br>② 再把 3 处分派收敛为 `LLMDispatcher`（复用收益落地）<br>③ 最后换 transport 实现 / 加缓存 / 加并发闸门（性能收益落地）<br>**理由**：没有可注入的 transport，就无法用假实现基准测试，合并分派时无法证明行为等价 |
| **U4 / P5** | `apps/research/db.py` 读方法同构 / `add_relations` | 结构重复 | N+1 + commit-in-loop | **先复用后性能**：把 `get_sub_queries`/`get_sources` 的解码段提取后，再谈批量写。提取本身不改变 IO 模式 |
| **U5 / P5** | `_build_merge_notice` | 完全重复（17 payload） | 在 `kernel/storage/backend.py`（**写入热路径**） | **先复用**：提取时保持纯函数、零分配、零全局状态。**禁止**为了复用把它变成类或加配置 |
| **U3** | DB 三层转发 | 完全重复（44 方法） | 转发是纳秒级，**无性能意义** | **纯按重复驱动**。不要用性能理由包装这条 |
| **U2 / P2** | `auth/db.py` 两个 `_init_schema` | 完全重复（37 payload） | **与 P2 无关**，但同文件 | **先 P2 再 U2**：P2 改的是 `foundation/db.py` 的连接层，U2 改的是 `foundation/auth/db.py` 的 schema —— **不同文件，可并行**。但建议同一 PR 内做完 auth/db 的两件事，避免两次动同一个文件 |

### 8.2 明确不建议复用（会损害性能）

| 提案 | 为什么损害性能 |
|------|--------------|
| 把 `LLMTransport` 做成**万能 HTTP 工具类**（含缓存、重试、指标、序列化） | 每次调用多一层间接 + 一次参数 dict 构造 + 一次 isinstance 分派。P1 的 transport 必须是**薄适配器**，只做「发请求」 |
| 为「统一」而给 `PageSnapshot` 加**泛型 / 可插拔 loader 链** | 快照在 IO 阶段构建，**泛型分派成本 × 页面数**。P4 的 `PageSource` 只允许 2 个实现（local / cached），不允许插件链 |
| 把 `wiki.status()` 的结果**缓存起来**以免重复计算 | status 反映**实时**状态（页数、目录结构），缓存会给出**过期答案**。正确做法是**减少工作量**（合并遍历），不是缓存 |
| 把 `LintEngine` 的规则做成**动态注册的插件系统** | 规则集是**固定 8 条**，每次运行要遍历 registry + 类型判断。现状是 dict 直查，**不要引入插件化** |
| 用**反射 / 动态属性**统一三处 LLM 路径（`getattr` 链已经够用） | `getattr` 链是运行时的，**只执行一次**；反射式元编程会引入 import 期开销与不可静态分析的分支 |
| 给 `RetryPolicy` 加**策略对象工厂 + 配置 DSL** | 重试决策在**异常路径**上，调用频率 = 错误频率（低）。但**如果**成功路径也走策略选择，就会给每次调用加开销。策略对象必须**在构造期选定**，不在调用期查表 |
| 把 `PageSnapshot` 的 contents 换成**惰性属性**以省内存 | 会把「一次读」变成「按需读」→ **重新引入重复 IO**，正是 P4 要消除的。快照必须**物化** |
| 给 `LLMDispatcher` 加**同步 + 异步两套实现** | 现有 3 处全是 async。同步变体没有调用方 → YAGNI，且会让 dispatcher 内部出现分支 |
| 让 `LLMDispatcher` **自己构造 client** | 会把 client 生命周期（连接复用）藏进 dispatcher → P1 的 transport 注入点失效，退回每次新建 |
| 在 `foundation/llm/` 引入**通用缓存框架** | 目前零缓存。引入框架前应先证明「缓存键能稳定命中」（模型+消息+参数的 hash）—— 否则只是加了一层 miss 开销 |

### 8.3 判定规则

```
【复用优先】当且仅当：
  (1) 业务语义一致（不是"代码长得像"）
  (2) 重复次数 ≥ 3，或 次数=2 且 影响范围大 或 修改频率高
  (3) 提取后不引入：全局状态 / 反射 / 额外 IO / 每调用分配
  (4) 提取单元有单一职责、输入输出明确、可单独测试
  → 动作：提取纯函数 / 薄适配器

【性能隔离优先】当且仅当：
  (1) 该代码在「热路径 × 大数据量 × 高频」交叉点上
  (2) 存在可注入的边界（transport / source / provider）
  (3) 剥离后能被单独基准测试（假实现 + 计数器断言）
  → 动作：先建接口 + 默认实现 = 现状，再在接口后优化

【两者冲突时】先性能隔离，后复用。
  理由：性能隔离产出的「可注入边界」正是复用所需的「稳定接口」。
        反过来（先合并分派再想基准）会得到一个「无法单独测试的大函数」，
        既不能证明等价，也没法优化。

【不满足任一条件】→ 不动。
  「三次出现再抽象」仍然有效；
  唯一例外：修改频率高 + 漏改风险大（U1 的 runner_v2 churn=22）可提前提取。
```

---

## 9. 分阶段实施计划

> 原则：**小步提交 · 每批可回滚 · 每批有测试或基准保护 · 不跨批次做大重构**

### 批次 0 — 修正确性缺陷 + 建基准设施（不改架构）

| # | 事项 | 关联 | 风险 |
|---|------|------|------|
| 0.1 | **`get_connection` 按 (path, profile) 单例** | P2 | 中 —— 改 research 的实际 FK 行为。**必须先跑全量测试** ｜ ✅ **已完成**（新增 `ConnectionProfile` / `PROFILE_DEFAULT` / `PROFILE_RESEARCH`；`research/db.py` 改用 `PROFILE_RESEARCH`） |
| 0.2 | **修 `achat` 返回契约不一致** —— `streamable.py:704` 返回 `str`，`context_manager.py:308` 调 `.get()` → `AttributeError` 被 `:324` 的宽 `except` 吞掉 → **对话压缩永远静默失效，退化成截断** | 新发现 | 低 —— 但要**同时**修 `consolidator.py:256` / `dream.py:301` 的防御性写法 ｜ ✅ **已完成**（新增 `foundation/llm/response.py::as_text`，三处调用点共用） |
| 0.3 | **修 `except TypeError` 无效重试** → 统一 `safe_read_text`（`foundation/io.py:50-66`） | P4-a | 低 |
| 0.4 | **引入 `pytest-benchmark` + 5 个基准**（见 §10） | G3 | 无（纯新增） |
| 0.5 | **给 `check_architecture.py` 补测试**（上一轮 N1 修复无回归网） | — | 无 ｜ ✅ **已完成**（`tests/test_check_architecture.py`，9 个用例） |
| 0.6 | **给 `scripts/clone_survey.py` 补测试**（新增 495 行分析工具，零测试） | — | 无 ｜ ✅ **已完成**（`tests/test_clone_survey.py`，26 个用例） |

**产出**：3 个 bug 修复 + 基准设施。**不改任何架构。**

> ✅ **批次 0 的 0.1 / 0.2 / 0.5 / 0.6 已于 2026-10-27 落地**（与 N1 同批）。实现要点：
>
> - **0.1**：`PRAGMA foreign_keys` 是**连接级**属性 → chat(FK=ON) 与 research(FK=OFF) 必须是**两条连接**、同一文件。
>   `get_connection()` 的单例 key 因此从 `path` 改为 `(path, profile)`；遗留 `**kwargs` 折进 profile（与 `profile` 互斥抛 `TypeError`）。
>   ⚠️ 副作用：`journal_mode=WAL` 是**文件级**属性 —— research 连接先开 WAL 会让 chat 连接也进入 WAL 模式；
>   当前两个 profile 的 `wal` 同值（均 `True`），无实际分歧，但若将来要差异化 WAL，**必须走独立文件**。
> - **0.2**：不改 provider 契约（`achat` / `chat` 都声明 `-> str`，是两个实现的共同声明），
>   而是加 `as_text()` 做归一化，`context_manager` / `dream` / `consolidator` 三处共用 —— 结构上杜绝复发。
>   ⚠️ 更正：`achat` 失败**不是完全静默** —— 它被 `logger.warning(..., exc_info=True)` 记录了；
>   准确表述是「压缩功能失效并退化为截断，warning 日志可见」。
> - **附带（连接生命周期）**：`ManagedConnection` 登记所有线程的连接，新增 `close_all_threads()` 供**显式**跨线程释放。
>   ⚠️ `close_all()` **保持线程内语义不变**（只关调用线程的连接）—— 跨线程关连接会打断该线程正在进行的写操作。
>   ⚠️ 关键实现细节：sqlite3 默认 `check_same_thread=True`，**拒绝**在别的线程 `close()`；
>   因此 `ManagedConnection` 的连接以 `check_same_thread=False` 打开
>   （thread-local 存储已保证「一线程一连接」，该守卫在正常使用中本就从不触发，
>   但没有它 `close_all_threads()` 就是一个会静默失败的空壳）。
>   P15「worker 线程句柄永不关闭」这一条**尚未真正闭环** —— 根治要靠 worker 线程自己
>   在 `finally` 里调 `close()`，或由 owner 在退出时显式调 `close_all_threads()`。
> - **0.5 / 0.6**：两个脚本此前都**没有回归网**，而它们正是方案里的证据来源。
>   补测过程中查出 `clone_survey.py` 的 `detect_layer_violations()` 恒返回 `[]`（假阴性，
>   根因是 `"llmwikify." + mod` 二次拼前缀），详见 `codebase-survey.md` §4 N1b。
>   「层违规 0」这一结论**不变**（`check_architecture.py` 本就报 0），但现在两路都真跑过。

### 批次 1 — 性能隔离（只建边界，默认实现 = 现状）

| # | 事项 | 关联 | 可回滚性 |
|---|------|------|---------|
| 1.1 | **`LLMTransport` 协议 + `HttpxTransport` 默认实现**（从 `streamable.py` 抽出，不改行为） | P1 | ✅ 纯新增，默认走旧路径 |
| 1.2 | **`TimeoutPolicy` 数据类**，四处硬编码 timeout 统一 | P1 | ✅ |
| 1.3 | **`RetryPolicy` 接口** + `phase` 概念（先不改上层，只让传输层吐出 attempt 元数据） | P1/P9 | ✅ |
| 1.4 | **`TokenAccounting`**（记忆化分词） | P1/P13 | ✅ |
| 1.5 | **`/status` `/lint` `/recommend` `/guide` `/sink_status` 改 sync `def`** | P3 | ✅ 单行 × 5 |
| 1.6 | **基准断言**：1.1–1.4 前后，事件序列与调用数**完全一致** | — | — |

**产出**：全部性能热路径变成「可注入 + 可基准」。**此时还没换实现**。

### 批次 2 — 复用收敛（在边界内合并重复）

| # | 事项 | 关联 | 备注 |
|---|------|------|------|
| 2.1 | **`LLMDispatcher` 收敛 3 处分派**（U1） | U1/P1 | ⚠️ 单个 PR 只做这一个点，diff 必须小 |
| 2.2 | **U2** auth/db `_create_auth_schema` + `_ensure_dir` | U2 | 同文件，一次做完 |
| 2.3 | **U5/U6** `_build_merge_notice`（改公开名）+ `_format_run_not_found` | U5/U6 | |
| 2.4 | **U4** research `_decode_row` | U4 | |
| 2.5 | **U7/U8/U9/U10** 四个小型纯函数提取 | — | 每个单独 commit |

**产出**：~120 行重复消除，LLM 策略变更从"改 3 处"降为"改 1 处"。

### 批次 3 — 性能收益落地（在边界后换实现）

| # | 事项 | 关联 |
|---|------|------|
| 3.1 | **transport 改长连接复用**（keep-alive） | P1 —— 每次调用省一次 TCP+TLS 握手 |
| 3.2 | **重试收敛到单层**（消除 3×4×2 放大） | P9 —— ⚠️ 配套告警 |
| 3.3 | **`/status` 走 `WikiStatusProvider`**，合并遍历 + 去掉每请求 DDL | P3 |
| 3.4 | **P4-a**：`_build_lint_context` 缓存 + `SourceIndex` 去 O(raw×sources) | P4 |
| 3.5 | **P4-b**：全量 `PageSnapshot`，6 条普通 Rule 改签名 | P4 —— 最大一个 PR |
| 3.6 | **P5** `add_relations_bulk` | P5 |
| 3.7 | **LLM 并发闸门**（`LLMDispatcher` 注入 semaphore） | P8 |
| 3.8 | **有界 CPU 执行器**给 graph/graph_analyze | P3 补充 |

**产出**：可量化性能收益。**每项都有 §10 的基准做前后对比。**

### 批次 4 — 结构性删层（独立 PR，独立 commit）

| # | 事项 | 关联 |
|---|------|------|
| 4.1 | **U3 删 `ResearchDelegate`**（保留惰性语义） | U3 |
| 4.2 | **删 `WikiDelegate`** | U3 |
| 4.3 | **修 delegate docstring 的「91/32 callers」误导表述** | U3 |
| 4.4 | **R5** `__version__` 下沉到 `foundation/version.py`（**两处**：status.py:5 + utility.py:59） | 见 `code-reuse-optimization.md` |

### 批次 5 — 跨层共享（最后考虑）

- 只有当 `foundation/` 里出现**第三个**来自 `apps/` 的真实共性需求时才提。
- 共享库规范（owner / 版本 / 文档 / 废弃策略 / 兼容测试）**见 §9.3**。

### 9.3 共享库规范（若走到批次 5）

| 项 | 规范 |
|----|------|
| **owner** | 每个共享模块指定 **1 名主 owner + 1 名备份**（需你补人名 —— **G4 缺口**） |
| **位置** | 只能放 `foundation/`（当前零依赖层）。`kernel/` 共享需先证明无 `apps/` 依赖 |
| **版本** | 跟随主版本号；**不**独立发版。破坏性变更走 deprecate → 两个版本 → 移除 |
| **文档** | 每个公开模块必须有：职责一句话、**不做**什么、依赖方向约束、示例 |
| **废弃策略** | `@deprecated` 标注 + `docs/deprecations.md` 登记 + **至少 1 个版本的宽限期** + 迁移脚本 |
| **兼容测试** | 每个共享模块有**契约测试**（Protocol 实现必须通过），确保第三方实现不被打破 |
| **准入门槛** | **三次出现**才进 `foundation/`；两次只在原层内共享 |

---

## 10. 测试、基准测试与回滚建议

### 10.1 必须新增的基准（G3 —— 当前无基准设施）

| ID | 基准 | 断言方式 | 保护的性能点 |
|----|------|---------|-------------|
| B1 | `benchmark_llm_dispatch` | **事件序列相等**（fake transport，零网络） | U1/P1 |
| B2 | `benchmark_transport_reuse` | **调用数计数器** + 建连次数 | P1（连接复用） |
| B3 | `benchmark_token_accounting` | 分词次数计数器（记忆化后应 ≈ 1× 而非 2×） | P13 |
| B4 | `benchmark_retry_policy` | **上游请求总数**（应从 24 降到 ≤ 4） | P9 |
| B5 | `benchmark_lint_snapshot` | **`read_text` 调用次数**（应 == 页面数） | P4 |
| B6 | `benchmark_status_snapshot` | 墙钟 + 遍历次数 | P3 |
| B7 | `benchmark_relation_bulk` | 遍历次数 + commit 次数 | P5 |
| B8 | `benchmark_event_loop_lag` | **事件循环最大单次阻塞** | P3（**最贴近用户体感**） |

> **原则**：基准优先断言**计数器**（调用次数、遍历次数、提交次数）而非纯时间。
> 计数器断言稳定、不受机器负载影响、能直接证明「IO 放大被消除」。
> 时间断言只作为参考并设置宽松阈值。

### 10.2 必须新增的测试（回归保护）

| # | 测试 | 保护 |
|---|------|------|
| T1 | `test_research_profile_disables_fk` | P2 / U2 ｜ ✅ 已落地：`tests/test_batch0_db_profile.py::TestResearchDatabaseForeignKeys` |
| T2 | `test_default_profile_enables_fk` | P2 ｜ ✅ 已落地：同上 |
| T3 | `test_research_insert_allows_orphan_fk` | P2 —— **research FK 关闭的既有语义** ｜ ✅ 已落地：同上 |
| T4 | `test_achat_returns_consistent_shape` | 0.2（压缩失效 bug） ｜ ✅ 已落地：`TestAsTextContract` |
| T5 | `test_compaction_actually_compacts` | 0.2 —— **断言压缩真的发生**，不再静默退化 ｜ ✅ 已落地：`TestContextManagerCompaction`（str + dict 两种响应形态） |
| T6 | `test_lint_handles_non_utf8_page` | 0.3 / P4 |
| T7 | `test_llm_dispatch_paths_equivalent` | U1 —— 三路径事件序列一致 |
| T8 | `test_prompt_name_tags_preserved` | U1 —— 指标 tag 不丢 |
| T9 | `test_no_duplicate_dispatch_implementations` | U1 —— AST 断言防回潮 |
| T10 | `test_status_route_not_blocking_loop` | P3 |
| T11 | `test_bulk_relations_equal_sequential` | P5 |
| T12 | `test_safe_read_text_used_everywhere` | 0.3 —— grep 守卫，禁止新的 `read_text(encoding=)` 裸调用 |

> ✅ T1–T5 已随批次 0.1 / 0.2 落地。测试按主题拆成三个文件，**每个修复与自己的测试网同 commit**
> （无红提交、可独立回滚）：
>
> | 文件 | 用例 | 配套修复 |
> |------|------|----------|
> | `tests/test_batch0_db_profile.py` | 12 | 0.1 FK profile 化 |
> | `tests/test_batch0_db_lifecycle.py` | 4 | 连接生命周期加固 |
> | `tests/test_batch0_llm_contract.py` | 8 | 0.2 `as_text` 契约统一 |

### 10.3 回滚策略

| 批次 | 回滚方式 | 风险 |
|------|---------|------|
| 0 | 单文件 revert；0.1 的 profile 改动需同步 revert `research/db.py` 的调用点 | 0.1 有行为变化 → **单独 commit**，便于精确 revert |
| 1 | 全部是**新增接口 + 默认实现 = 现状** → 删掉接口调用即回滚 | 低 |
| 2 | U1 单独 PR（**唯一有 diff 风险的**）→ 单文件 revert | 中 —— SSE 契约需端到端验证 |
| 3 | 每项独立 PR，各自对应一个基准；基准回退即代码回退 | 中 —— 3.2 重试收敛会让上游错误暴露变多，**必须先上告警再上代码** |
| 4 | 删层是纯删除 → revert 即恢复；但 4.1/4.2 要连带恢复 `__init__.py` 的 export | 中 |

### 10.4 上线顺序（性能相关）

```
① 先上基准设施 + 告警（B1–B8 计数器版 + event_loop_lag 面板）
② 再上「只建边界」的批次 1（行为零变化，仪表盘基线稳定）
③ 再上复用收敛批次 2（行为等价，有 B1/B7 等价性测试）
④ 最后上性能收益批次 3 —— 每项单独灰度，看指标再全量
```

---

## 11. 代码评审 checklist

### 11.1 复用合理性

| # | 检查项 | 判据 |
|---|--------|------|
| R-1 | **业务语义一致**，不只是代码长得像 | 能用一句话说清「这两处在业务上做的是同一件事」 |
| R-2 | **三次出现**（或 2 次但修改频率高 + 影响范围大） | U1 命中（churn=22）；2 次低频的不够 |
| R-3 | **提取单元单一职责** | 一个函数/一个类只做一件事；名字能说清 |
| R-4 | **无全局状态** | 不引入模块级可变单例（除非有明确 owner + 淘汰） |
| R-5 | **输入输出明确** | 有类型标注；不用 `Any` 兜底（除非真的动态） |
| R-6 | **依赖方向合规** | `foundation` 不依赖上层；`kernel` 不依赖 `apps`（`scripts/check_architecture.py` 必须 0 违规） |
| R-7 | **不是万能工具类** | 没有 `CommonUtils` / `Helpers` / `Utils` 命名；不承载多个无关职责 |
| R-8 | **不是继承强行复用** | 优先组合/委托；`is-a` 关系必须真实存在 |
| R-9 | **没有 if/else 开关代替抽象** | 不出现 `if provider == "x"` 的多态分支 |
| R-10 | **参数不过度** | 不为「通用」引入 6 个可选 flag；差异用清晰的小接口表达 |
| R-11 | **副作用显式** | 副作用在签名或 docstring 里写明；不藏起 IO/网络写 |
| R-12 | **测试到位** | 提取前后行为等价有测试证明（不是"跑通了"） |
| R-13 | **未回潮** | `scripts/clone_survey.py` 双口径扫描无新增组 |

### 11.2 性能隔离合理性

| # | 检查项 | 判据 |
|---|--------|------|
| P-1 | **有数据支撑**，不凭感觉 | 附基准数字或计数器证据；"我觉得慢"不算 |
| P-2 | **边界可注入** | 有 Protocol/接口，**且有 fake 实现**（否则不可测） |
| P-3 | **默认实现 = 现状** | 剥离 PR 本身零行为变化；优化是后续 PR |
| P-4 | **可单独基准测试** | 有对应基准 + 计数器断言 |
| P-5 | **可监控** | 有指标 + 有告警阈值 |
| P-6 | **可替换实现** | 换实现不需要改调用方 |
| P-7 | **未增加间接层开销** | 热路径上没多出：反射 / 装箱 / 额外拷贝 / 每调用分配 / 日志 |
| P-8 | **执行位置明确** | IO 密集 → worker 线程；CPU 密集 → 有界执行器；**不是**事件循环 |
| P-9 | **命名体现性能语义** | 不叫 `Utils`；名字能看出这是热路径（如 `Snapshot` / `Transport` / `Budget`） |
| P-10 | **没有藏进万能类** | 性能代码有自己的模块，不塞进已有大文件 |
| P-11 | **有界** | 并发有信号量、缓存有上限、内存有阈值（超出有降级路径） |
| P-12 | **GIL 意识** | 纯 Python CPU 工作移出事件循环**也不够** —— 需独立执行器，否则只是换个线程争 GIL |

### 11.3 通用（两栏都适用）

| # | 检查项 |
|---|--------|
| G-1 | `ruff check` 干净 |
| G-2 | 相关测试全绿（列出实际跑的命令与结果） |
| G-3 | `python scripts/check_architecture.py` → 0 违规（**Windows 控制台需 UTF-8** —— 上一轮 N1 已修） |
| G-4 | 改动行数与 PR 规模匹配（**一个 PR 只处理少量调用点**） |
| G-5 | 有回滚路径（revert 粒度、是否需要配套配置回退） |
| G-6 | 文档同步（`docs/designs/` 里受影响的方案文档已更新） |
| G-7 | 未引入新的未跟踪文件（`git status` 干净） |

---

## 12. 需要你补充的信息

| # | 缺什么 | 怎么补 | 补了之后我会做什么 |
|---|-------|-------|------------------|
| **1** | **线上 wiki 规模**（页数 / raw 文件数 / `page_links` 行数 / `relations` 行数） | `ls wiki/wiki/**/*.md \| wc -l` 之类 | 把 §5 的「按 1400 页估算」换成实际值，重排 P4/P5 优先级 |
| **2** | **一次线上 `/api/wiki/lint` 与 `/api/wiki/status` 的真实耗时** | 仓库已有 `scripts/profile_lint_paths.py`（带 `--wiki` 参数），跑一次贴结果 | 验证 §6 P3/P4 的收益量级 |
| **3** | **一次 `/api/wiki/graph` 在飞行时 `/api/wiki/status` 的 p95** | `scripts/repro_bench_graph.py --base-url http://127.0.0.1:8765` | ⚠️ 该脚本的前提已反（status 才是阻塞方），我会先重写它再让你跑 |
| **4** | **是否存在生产 APM / 火焰图**（APM 平台名 + 截图/导出） | 有的话直接给 | 把 §5 从「静态可达性」升级为「实测」，重排全部优先级 |
| **5** | ~~**research 表的 FK 实际值**（线上 `PRAGMA foreign_keys`）~~ | ~~`sqlite3 .llmwiki_agent.db "PRAGMA foreign_keys;"`~~ | ✅ **不再需要** —— 批次 0.1 之后 FK 值由 `ConnectionProfile` 决定，不再取决于构造顺序；research 恒 OFF、chat 恒 ON，且有回归测试锁定 |
| **6** | **LLM 供应商实际并发上限** | 供应商文档 / 账户配额 | 定 P8 闸门默认值（现假设 3） |
| **7** | **共享库 owner 人选**（G4） | 给出名字 + 备份 | 补 §9.3 的 owner 表 |
| **8** | **本次优先级取舍** | 见下方问卷 | 见下 |

**我的默认取舍**（若你不特别指定）：

1. **正确性优先于性能**：P2（连接 profile）与 0.2（压缩失效）先做，即使它们不是性能项 —— 因为它们让后续性能优化的**基线可信**。
2. **先建边界再换实现**：批次 1 全部是「加接口、默认实现不变」，单独可上线、零风险。
3. **U1 是唯一的复用大 PR**：其余提取都很小（< 20 行），可并行 review。
4. **性能收益全部用计数器断言**，不靠时间阈值 —— 避免 CI 抖动导致的假回归。

---

## 附录 A：本次分析的方法与可复现命令

```powershell
# 1) 图谱（AST，无 LLM 成本）
graphify extract . --code-only
graphify cluster-only . --no-label --no-viz
graphify god-nodes --top 20

# 2) 克隆检测（双口径：docstring / payload）
python scripts/clone_survey.py out.json

# 3) 分层守卫
python scripts/check_architecture.py        # 需 UTF-8 控制台

# 4) 变更频率
git log -60 --name-only --pretty=format: -- "src/**"

# 5) 已有基准脚本（仓库自带）
python scripts/profile_lint_paths.py --wiki <wiki-dir>
python scripts/repro_bench_graph.py --db <db> --base-url http://127.0.0.1:8765
```

**证据分级**：本文每条性能结论标注 **E1**（仓库内已有基准/历史修复佐证）·
**E2**（源码级静态可达性）· **E3**（需运行时确认）。
**E3 项在 §12 列出**，拿到 profile 后应重排优先级。

## 附录 B：本次分析覆盖与未覆盖

**已覆盖**：LLM 调用与客户端生命周期 · SQLite 连接/事务/索引 · 文件系统 IO 与缓存 ·
lint 与 graph 管线 · 并发原语与事件循环阻塞 · HTTP 路由 sync/async 分布 ·
git churn · AST 克隆（双口径）。

**未覆盖**（本次未展开，建议单独立项）：
- `apps/research/` 的 ReAct 阶段机内部（5 模块环内）
- `apps/chat/skills/` 插件体系与 DAG 执行器内部
- `ui/webui` 前端（React）侧的性能
- `reproduction/` 量化复现管线（与主线复用/性能议题弱相关）
- WebSocket / SSE 传输层（`chat_sse.py` churn 28，历史热点）
