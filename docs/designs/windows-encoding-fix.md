# Windows 编码修复 — read_text/write_text/open 补 encoding

> 分支 `feat/auto-doc-ingest` · 2026-07 · 对应审查高优 #1

## 问题

Windows 下 `Path.read_text()` / `write_text()` / `open()` 默认使用 locale
编码（GBK/cp936），而 wiki 内容、index、sink 均为 UTF-8。混读导致：

- `_compute_content_hash` 哈希不一致 → 源分析缓存永不命中 / 误命中
- 中文页 `write_text` 用 GBK 落盘 → 再读 `UnicodeDecodeError` 或乱码
- `query_sink` / `index` / `page_io` 等内容路径同理

## 修复

批量为 `src/llmwikify/` 下所有 `read_text()` / `write_text()` /
文本模式 `open()` 补 `encoding="utf-8"`：

- 43 个文件，~100 处
- 重点路径：`source_analysis.py`（hash）、`query_sink.py`、`page_io.py`、
  `index.py`、`backend.py`、wiki engines/lint、memory/config/yaml 读写
- `open()` 3 处：`backend.py` log 追加、`db.py` 导出、`write_page.py` 读入
- 修复 f-string 内嵌套双引号（`analyzer.py`，Python 3.10 不合法）

## 验证

- `py_compile` 全量 0 错误
- `ruff check src/llmwikify/` 通过
- encoding 直接相关测试 20 passed
- `test_wiki_core` + `test_wiki_server` 与 stash 基线一致
  （46 passed / 19 PermissionError 为既存 SQLite 锁）
