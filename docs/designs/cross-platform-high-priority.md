# 跨平台部署兼容性修复（高优 6 项）

> 分支 `feat/auto-doc-ingest` · 2026-07 · 对应跨平台审查高优

## 问题与修复

### 1. 路径守卫分隔符（高）

`registry_routes.py:137` 用 `str(resolved).startswith(str(home) + "/")`
判断路径是否在 home 下——Windows 路径分隔符是 `\`，合法 home 子路径
全部被拒（安全 + 功能双杀）。

**修复**：改用 `Path.relative_to(home)`，跨平台正确且天然拒绝
home 外路径（ValueError）。

### 2. wiki_id 提取（高）

`core.py:92` 用 `str(wiki.root).split("/")[-1]` 取末段——Windows
反斜杠切不出，得到整条绝对路径作为 wiki_id。

**修复**：改 `Path(wiki.root).name`。

### 3. `/tmp` 回退（高）

`maintenance/__init__.py:104` 无 wiki 时回退 `Path("/tmp")`——
Windows 无 `/tmp`，落到 `<drive>:\tmp` 或写失败。

**修复**：改 `tempfile.gettempdir()`。

### 4. 日志编码（高）

`foundation/logging.py:81-88` `RotatingFileHandler` 未指定
`encoding=`——Windows 默认 GBK 下中文日志 mojibake 或
`UnicodeEncodeError`。

**修复**：补 `encoding="utf-8"`。

### 5. graphviz `dot` 兜底（高）

`graph/export.py:304-305` 调用 `dot` 无 `FileNotFoundError`
处理——Windows 常未装 Graphviz，直接崩。

**修复**：捕获 `FileNotFoundError`，清理 .dot 临时文件后抛出
带安装指引的 `RuntimeError`；`subprocess` 补 `encoding="utf-8"`。

### 6. SQLite timeout（高）

裸 `sqlite3.connect()` 无 `timeout`——Windows 并发/杀软易
`PermissionError` / `database is locked`（已知 `.llmwikify.db`
PermissionError 根因之一）。

**修复**：全部补 `timeout=5.0`：
- `foundation/db.py:57`（主连接工厂）
- `kernel/storage/index.py:59`
- `kernel/storage/jieba_dict_gen.py:68,260`
- `interfaces/cli/commands/db.py` ×5
- `apps/chat/db_migrations.py` ×3

## 验证

- 全部文件 `py_compile` 通过
- `ruff check` 通过
- 相关回归与 stash 基线一致（5 failed 均为既存：Windows 路径
  分隔符 / sink flow / knowledge_graph CLI）
