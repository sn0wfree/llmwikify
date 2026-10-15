# GapFiller Web 搜索静默失效修复（Bug 2）— 调查与修复记录

> 日期: 2026-10-14
> 范围: `apps/agent/maintenance/gap_filler.py::_web_search`（自维护 Track B web 证据腿）
> 背景: `ci-green-plan-2026-10.md` §4 的 mypy 排查发现（`[call-arg]`）
> 状态: **修复完成，验证通过，待提交**（文档先行 → 代码 → 测试）

---

## 1. TL;DR

`_web_search()` 里 `WebSearch()` **缺必填参数 `config`**（签名 `WebSearch(config: dict)`）→
`TypeError` 被同方法的 `except Exception` 吞成 **debug 日志** → 自维护 gap filler 的
web 证据腿**自引入以来从未工作过**，每轮 gap 提案都退化为 wiki-only。

修复 = 新增 `_search_config()`（读全局 `research` 配置段，`create_search_provider`
自带 provider 链兜底），`WebSearch()` → `WebSearch(self._search_config())`。

## 2. 取证

### 2.1 调用链

```
GapFiller.run_cycle() → _propose_entity_page() → [第 272 行]
    if self.config.web_search_enabled:
        web_sources = await self._web_search(concept)   ← 本次修复点
```

### 2.2 失败模式

```python
ws = WebSearch()                     # ← 缺 config（必填），TypeError
except Exception as exc:             # ← 被这里吞掉
    logger.debug("...web search failed: %s", exc)   # debug 级，默认不可见
    return []                        # web 腿永远为空
```

### 2.3 时间线（"生来就坏"）

| 时间 | 事件 |
|---|---|
| 2026-06-07 | `20d35f5` — `WebSearch.__init__` 重构为 **必填 `config`** |
| 2026-08-16 | `47b8c13`（B3b "entity gap research via wiki+**web**+LLM synthesis"）— 新写的 `_web_search` 仍用旧写法 `WebSearch()`，**出生即坏**，且被 except 静默 |

### 2.4 影响面

- Track B 提案的 web 证据腿永远为空 → 实体页草稿只有 wiki 上下文，质量降级
- 无崩溃、无告警（debug 日志），用户无法感知
- 严重度：MEDIUM（静默功能降级）

## 3. 修复设计

```python
def _search_config(self) -> dict[str, Any]:
    """Global search settings (~/.llmwikify/llmwikify.json → research).

    2026-10-14 fix (Bug 2): `WebSearch()` used to be called without its
    required config; the TypeError was swallowed by `_web_search`, so the
    web leg silently returned [] every cycle. `create_search_provider`
    fills in the provider chain (jina / minimax / duckduckgo) and resolves
    the minimax key from the global llm config as fallback.
    """
    try:
        from llmwikify.foundation.config import config as _llmwikify_config
        cfg = _llmwikify_config.get("research", {})
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}
```

调用点：`ws = WebSearch(self._search_config())`

设计要点：

- 配置源 = 全局 `research` 段（与 research 管线一致；`routes.py::_load_research_config` 同源）
- 层次合法：`apps/agent`（L3）→ `foundation`（L1）✓
- `create_search_provider({})` 本身就是可用链（Jina → minimax 自动取 key → DDG），
  所以即使无配置也不会再失败
- 保留既有 `except` 兜底（防单一 provider 故障影响整轮）

## 4. 测试设计

新增到 `tests/test_maintenance_gap_filler.py`（沿用 `wiki_instance` fixture）：

| 用例 | 断言 |
|---|---|
| `test_web_search_passes_config_to_websearch`（回归） | monkeypatch `WebSearch` 捕获构造参数 → 必须是 **dict**；结果正常格式化（旧代码：`WebSearch()` TypeError → `[]`、captured 为空 → 必挂） |
| `test_search_config_reads_research_section` | 临时 `LLMWIKIFY_HOME` + `llmwikify.json → research` → `_search_config()` 返回该段 |
| `test_search_config_defaults_to_empty_dict` | 无配置文件 → `{}`（provider 链由 `create_search_provider` 兜底） |

## 5. 验收清单

- [x] `gap_filler.py` 修复（`_search_config()` + `WebSearch(self._search_config())`）
- [x] `ruff check` 通过
- [x] 新测试 3 个 + `tests/test_maintenance_gap_filler.py` 全量回归（10 passed）
- [x] 维护模块回归：manager / auto_ingest / comprehensive / lifespan / extended（97 passed）
- [ ] 汇报文件清单，待用户确认后 commit

## 6. 验证结果（2026-10-14）

```
ruff check src/llmwikify/apps/agent/maintenance/gap_filler.py tests/test_maintenance_gap_filler.py
  → All checks passed

pytest tests/test_maintenance_gap_filler.py
  → 10 passed（7 既有 + 3 新增）

pytest tests/test_maintenance_manager.py tests/test_maintenance_auto_ingest.py \
       tests/test_maintenance_comprehensive.py tests/test_maintenance_lifespan.py \
       tests/test_maintenance_extended.py
  → 97 passed（73s）
```

关键回归用例（旧代码必挂）：`test_web_search_passes_config_to_websearch` ——
`FakeWebSearch.__init__(self, config)` 捕获构造参数；旧代码 `WebSearch()`
缺参 TypeError 被吞，`captured` 为空、返回 `[]`。
