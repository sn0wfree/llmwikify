# 01 — 个人阅读笔记 wiki

> 对应 [docs/TUTORIAL.md §场景 1](../../docs/TUTORIAL.md#场景-1个人阅读笔记-wiki)

## 跑法

```bash
cd examples/01_personal_reading_notes
python play.py
```

预期输出（节选）：

```
📥 Copied 2 fixtures to raw/
✅ Wiki initialized at /tmp/.../my-notes
   raw/   = /tmp/.../my-notes/raw
   wiki/  = /tmp/.../my-notes/wiki
📄 Ingested karpathy-llm-wiki.md → status=ok
📄 Ingested andrew-ng-ai-notes.md → status=ok

🔍 search('LLM wiki') → N hits
   - LLM-Native Wiki: ...
✍️  Wrote wiki/concepts/bidirectional-references.md
📚 Index built: 3 pages, 1 references
🔗 inbound=0 outbound=1
🩺 lint: {'broken': 0, 'orphan': 0, 'contradiction': 0}
🎉 Done.
```

## 涉及 API

| API | 用途 |
|---|---|
| `create_wiki(path)` | 创建 Wiki 实例 |
| `wiki.init(agent="generic")` | 初始化（`generic` 跳过 MCP config） |
| `wiki.ingest(src)` | 提取 + 写 raw/ |
| `wiki.search(q, limit=5)` | FTS5 全文搜索 |
| `wiki.write_page(name, content)` | 写 wiki 页面 |
| `wiki.build_index()` | 重建引用索引 |
| `wiki.get_references(name)` | 双向引用 |
| `wiki.lint(format="brief")` | 健康检查 |

## 对应 TUTORIAL 节

- §1.3 步骤 1-8
- §1.5 底层产物映射表
- §1.6 故障排查 Top-3

## 不依赖

无 LLM 配置需求（`agent="generic"`），fixture 已用 markdown 自带 frontmatter。
