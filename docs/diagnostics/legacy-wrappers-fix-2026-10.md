# 遗留包装器修复（Bug 3 + Bug 4）— 调查与修复记录

> 日期: 2026-10-14
> 范围: `apps/chat/research_agent.py`（Bug 3）· `interfaces/server/__init__.py`（Bug 4）
> 背景: `ci-green-plan-2026-10.md` §4 的 mypy 排查发现（`[call-arg]` ×2）
> 状态: **修复完成，验证通过，待提交**（文档先行 → 代码 → 测试）

---

## 1. TL;DR

两个**遗留包装器**在重构后失联，调用即 `TypeError`：

| # | 位置 | 失败模式 |
|---|---|---|
| 3 | `ResearchAgent(llm_client=...)` 不传 `engine` | fallback 仍按旧签名构造 `ResearchEngine(llm_client=...)`，但 Phase 4（`91ef936`）后 `wiki`/`db` 已成必填 → 构造即崩 |
| 4 | `interfaces/server/__init__.py::create_unified_server` | 把不存在的 `agent=` 传给 `WikiServer` → 调用即崩（同名正确版在 `interfaces/mcp/server.py`，e2e 用的是后者） |

两者都是**无现存调用方**的潜伏/死路径（已全仓核实），按"快速失败 + 明确指引"修复。

## 2. 取证

### 2.1 Bug 3：ResearchAgent

- 构造签名：`ResearchAgent(llm_client, engine=None, system_prompt=...)`
- `engine is None` 分支（`research_agent.py:69-71`）：
  ```python
  from llmwikify.apps.research.engine import ResearchEngine as _RE
  engine = _RE(llm_client=llm_client)     # ← ResearchEngine 现签名 (wiki, db, llm_client, config=None)
  ```
- `91ef936`（Phase 4 合并 apps/research）改签名后 wrapper 未同步
- **All 10 个调用点**（tests ×10）均显式传 `engine=`；src 内无调用 → 仅"直接使用公共导出"的用户会踩
- 影响：构造即 `TypeError: missing required positional arguments`（信息不含指引）

### 2.2 Bug 4：server 包 wrapper

- `interfaces/server/__init__.py` 的 `create_unified_server` 传 `agent=agent` → `WikiServer.__init__` 无此参数
- 同名函数在 `interfaces/mcp/server.py:55` 是**正确版**（`# noqa: ARG001` 丢弃 agent 参数），
  且被 `interfaces/mcp/__init__.py`、`tests/e2e/conftest.py`、`tests/test_v025_web_ui.py` 使用
- server 包版本**无任何调用方**（仅 `__all__` 导出）→ 死路径
- 影响：仅直接调用时崩；两处同名是结构性坏味道（本次只修不合并，避免超范围）

## 3. 修复设计

### Bug 3 — 快速失败 + 指引（保留签名兼容）

```python
if engine is None:
    # 2026-10-14 fix (Bug 3): the llm_client-only fallback built
    # ResearchEngine(llm_client=...) which has been missing the now-required
    # wiki/db args since the v0.40 apps/research migration (91ef936).
    raise TypeError(
        "ResearchAgent requires an explicit `engine=...`: ResearchEngine "
        "needs wiki + db. Build ResearchEngine(wiki=..., db=..., "
        "llm_client=...) and pass it in."
    )
```

同步更新 docstring（`engine` 参数说明：None 会 raise）。

### Bug 4 — 对齐 mcp 版本（丢弃 agent 参数）

```python
def create_unified_server(
    wiki,
    agent=None,  # noqa: ARG001 - kept for backward compat
    api_key=None,
    mcp_name=None,
) -> Any:
    """..."""
    # 2026-10-14 fix (Bug 4): WikiServer has no `agent` parameter — the
    # previous call passed it and raised TypeError on every invocation.
    server = WikiServer(
        wiki,
        api_key=api_key,
        mcp_name=mcp_name,
        enable_mcp=True, enable_rest=True, enable_webui=True,
    )
    return server.app
```

## 4. 测试设计

| 落点 | 用例 | 断言 |
|---|---|---|
| `tests/test_apps_chat_research_agent.py::TestResearchAgentConstruction` | `test_engine_none_raises_actionable_error`（回归） | `ResearchAgent(llm_client=llm)` → `pytest.raises(TypeError, match="engine")`（旧代码是原生缺参 TypeError，match 失败） |
| `tests/test_v025_web_ui.py::TestUnifiedServer` | `test_server_package_wrapper_drops_agent`（回归） | monkeypatch `server_pkg.WikiServer` 断言 `agent` 未出现在 kwargs；旧代码断言失败 |

## 5. 验收清单

- [x] 两处代码修复（`research_agent.py` raise + `server/__init__.py` 丢 agent）
- [x] `ruff check` 通过
- [x] 新测试 + 目标回归（22 passed, 2 skipped）
- [x] 扩展回归：`test_wiki_server.py` / `test_api_routes.py` / `test_apps_chat_base.py`（57 passed, 9 skipped）
- [ ] 汇报文件清单，待用户确认后 commit

## 6. 验证结果（2026-10-14）

```
ruff check research_agent.py server/__init__.py test_apps_chat_research_agent.py test_v025_web_ui.py
  → All checks passed

pytest tests/test_apps_chat_research_agent.py tests/test_v025_web_ui.py tests/test_apps_chat_integration.py
  → 22 passed, 2 skipped

pytest tests/test_wiki_server.py tests/test_api_routes.py tests/test_apps_chat_base.py
  → 57 passed, 9 skipped
```

关键回归用例（旧代码必挂）：

- `test_engine_none_raises_actionable_error` —— 旧代码抛的是缺参 TypeError，
  消息不含小写 `engine`，`match="engine"` 失败；新代码给出 actionable 指引。
- `test_server_package_wrapper_drops_agent` —— 旧代码把 `agent=` 传给 FakeWikiServer
  → 断言 `"agent" not in kwargs` 失败。
