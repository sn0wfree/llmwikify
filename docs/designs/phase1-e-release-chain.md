# Phase 1 / E — 发布链路修复

日期: 2026-11-02 · 分支: v0.41-dev

## 三处断点

### 1. wheel 不带 UI（`pip install` 后 `serve --web` 404）

`find_webui_dist()`（`interfaces/server/utils/webui.py`）只找仓库布局：

```python
repo_root = Path(__file__).resolve().parent.parent.parent.parent.parent.parent
candidate = repo_root / "ui" / "webui" / "dist"
```

装成 wheel 后 `__file__` 在 `site-packages/llmwikify/...`，算出来的
`repo_root` 是 site-packages，`site-packages/ui/webui/dist` 永远不存在。
`[tool.setuptools.package-data]` 也没有 `ui/webui/dist` 的条目。

**修法**：前端构建产物直接落到 Python 包内——这是这类项目的标准做法。

| 改动 | 内容 |
|------|------|
| `ui/webui/vite.config.ts` | `build.outDir` → `../../src/llmwikify/webui/dist` |
| `src/llmwikify/webui/__init__.py` | 新增：包标记 + `DIST_DIR` / `dist_exists()` |
| `pyproject.toml` | `package-data` 增加 `"llmwikify.webui" = ["dist/**/*"]` |
| `MANIFEST.in` | `recursive-include src/llmwikify/webui/dist *` |
| `.gitignore` | `src/llmwikify/webui/dist/` 不入仓 |
| `find_webui_dist()` | **先**找包内 `llmwikify/webui/dist`，**再**退回仓库旧路径 |
| `AGENTS.md` | 构建说明同步新路径 |

**验证**：构建 wheel 后检查内容——

```
webui entries: 39
  llmwikify/webui/dist/index.html
  llmwikify/webui/dist/assets/AgentChat-*.js
  ...
index.html present: True
```

`find_webui_dist()` → `src\llmwikify\webui\dist`，`index.html` 存在。

### 2. 版本号发版后不同步（真实 bug）

版本有两个真源：

- `pyproject.toml` → `version = "0.40.6"`（构建后端读这个）
- `src/llmwikify/foundation/version.py` → `__version__ = "0.40.6"`（运行时读这个）

而 `version-bump.yml` 的 sed **只改 pyproject.toml**：

```yaml
sed -i "s/^version = \".*\"/version = \"${NEW_VERSION}\"/" pyproject.toml
```

→ 发版后 `llmwikify.__version__` 仍是旧值。版本号下沉到
`foundation/version.py` 时（commit `c4bfc242`）workflow 没跟着改。

**修法**：

- sed 同时改 `foundation/version.py`
- 新增一步校验两处一致，不一致直接失败
- `add-paths` 从三个路径改为实际会变的两个：
  `pyproject.toml` + `src/llmwikify/foundation/version.py`
  （原来的 `src/llmwikify/_version.py` **根本不存在**，
  `src/llmwikify/__init__.py` 也不再含版本串）

### 3. `all` extras 漏了 `llm`

```toml
all = [ "llmwikify[extractors,mcp,config,watch,graph,web,agent]",]
```

漏了 `llm`（tiktoken）——`.[all]` 装出来的环境没有 tiktoken。

## 回归网

`tests/test_package_version.py`（7 项）：

1. `pyproject.toml` 版本 == `foundation/version.py` 版本
2. `llmwikify.__version__` == 叶模块版本
3. 版本号格式合法
4. release workflow 同时 sed 两处
5. workflow 不再引用不存在的路径
6. 两个版本源文件真实存在

`tests/test_webui_cache_headers.py` 的 `test_returns_repo_relative_path`
改为断言新契约（包内 `llmwikify/webui/dist` 或仓库旧布局 `ui/webui/dist`）。

## 验证

```
pytest tests/test_package_version.py tests/test_webui_cache_headers.py → 13 passed
python -m build --wheel → wheel 含 39 个 webui 条目 + index.html
find_webui_dist() → src\llmwikify\webui\dist（index.html 存在）
ruff check → clean
```
