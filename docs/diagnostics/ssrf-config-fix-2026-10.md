# SSRF 配置死引用修复（Bug 1b）— 调查与修复记录

> 日期: 2026-10-14
> 范围: `foundation/utils.py::_load_ssrf_config` + `is_safe_url` 调用链
> 背景: 与 `dd63e70`（middleware `trusted_proxies`）同款根因的**第二处**；由 `ci-green-plan-2026-10.md` §4 的 mypy 排查发现
> 状态: **修复完成，验证通过，待提交**（文档先行 → 代码 → 测试）

---

## 1. TL;DR

`_load_ssrf_config()` 引用了 **`foundation.config.get_config`（该函数不存在）**：

```python
from .config import get_config   # ImportError！
config = get_config()
```

`ImportError` 被 `except Exception` 静默吞掉（只打 debug 日志）→ `ssrf_protection`
配置**自引入（`b7ae14a`）以来从未生效**，`is_safe_url()` 永远走 `enabled=False`
分支直接放行所有 URL。修复 = 改用真实单例 `foundation.config.config`（与 `dd63e70` 同款），约 5 行。

## 2. 取证

### 2.1 调用链（活跃代码，非死代码）

| 入口 | 位置 |
|---|---|
| URL ingest（web extractor） | `foundation/extractors/web.py:22,40` |
| chat `web_fetch` 工具 | `apps/chat/skills/actions/web_fetch_action.py:139` |
| ↓ | `foundation/utils.py:193 is_safe_url()` |
| ↓ | `foundation/utils.py:143 _load_ssrf_config()` |

### 2.2 失败模式

```
from .config import get_config          # ← foundation.config 中不存在
        → ImportError
        → except Exception 吞掉（logger.debug，默认级别不可见）
        → 返回 {enabled: False, blocked_networks: [], blocked_hostnames: []}
        → is_safe_url() 首行判断 `if not enabled: return True` → 放行一切
```

### 2.3 影响面

- 用户按 docstring 示例配置 `~/.llmwikify/llmwikify.json → ssrf_protection.enabled: true`
  + blocked 列表 → **永远不生效**（静默安全配置失效）
- 结合 B3：服务器已暴露公网（`8.133.234.138` + nginx），LLM 可经 `web_fetch` 抓任意 URL
  → 内网服务 / 云 metadata（`169.254.169.254`）可被访问
- 引入时间：`b7ae14a`（该特性引入时即接错）；`dd63e70` 修复 middleware 同款问题时**漏扫本处**
- 全仓已复核：本处是最后一处 `get_config` 死引用（middleware 注释行与
  `interfaces/.../agent/config.py::_get_config_data` 为无关项）

## 3. 修复设计

与 `dd63e70` 完全同款（真单例 + 保留兜底）：

```python
# 修复前
from .config import get_config
config = get_config()
ssrf_config = config.get("ssrf_protection", {})

# 修复后
from .config import config as _llmwikify_config
ssrf_config = _llmwikify_config.get("ssrf_protection", {})
```

设计要点：

- `Config.get(section, default)` 语义已核实（`foundation/config.py:140`），
  `get("ssrf_protection", {})` 恰好等价于原意图
- **保留** `except Exception → 默认值` 兜底：防御配置文件值畸形（如字符串）场景，
  但正常路径不再触发
- 默认行为不变：未配置时 `enabled=False`、全放行（向后兼容）

## 4. 测试设计

新增 `tests/test_foundation_ssrf_config.py`（镜像 `test_foundation_config.py` 的单例 reset 范式）：

| 用例 | 断言 |
|---|---|
| 无配置 → 全放行（兼容） | `is_safe_url("http://127.0.0.1/")` True |
| 真实配置文件回归（tmp `LLMWIKIFY_HOME` + `llmwikify.json`） | `enabled:true` 后 `127.0.0.1` / `metadata.google.internal` 被拦；`https://example.com` 放行 |
| blocked_networks 生效 | `10.1.2.3` 在 `10.0.0.0/8` 内被拦 |
| 非 http/https scheme | `file:///etc/passwd` 被拒 |

（autouse fixture：`Config._instance = None`；测试内将 `foundation.config.config`
monkeypatch 为全新 `Config()`，因为模块级单例在 import 时已绑定旧 HOME。）

## 5. 验收清单

- [x] `foundation/utils.py` 修复（改用 `foundation.config.config` 单例）
- [x] `ruff check` 通过
- [x] 新测试 7 个通过 + `tests/test_foundation_config.py` 回归通过（合计 34 passed）
- [x] 相关回归：`test_web_fetch_action` / `test_apps_chat_skills_actions` /
      `test_apps_chat_agent_runner_v2` / `test_skill_adapter_exposed`（750 passed）
- [ ] 汇报文件清单，待用户确认后 commit

## 6. 验证结果（2026-10-14）

```
ruff check src/llmwikify/foundation/utils.py tests/test_foundation_ssrf_config.py
  → All checks passed

pytest tests/test_foundation_ssrf_config.py tests/test_foundation_config.py
  → 34 passed

pytest tests/test_web_fetch_action.py tests/test_apps_chat_skills_actions.py \
       tests/test_apps_chat_agent_runner_v2.py tests/test_skill_adapter_exposed.py
  → 750 passed
```

关键回归用例（旧代码必挂）：`test_config_file_is_read` —— 临时
`LLMWIKIFY_HOME` 写入 `ssrf_protection.enabled: true` 后，`_load_ssrf_config()`
必须返回 `enabled=True`；旧实现因 `get_config` ImportError 只会返回 `False`。
