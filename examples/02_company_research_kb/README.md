# 02 — 公司尽调知识库

> 对应 [docs/TUTORIAL.md §场景 2](../../docs/TUTORIAL.md#场景-2公司尽调知识库)

## 跑法

```bash
cd examples/02_company_research_kb
python play.py
```

预期输出：

```
📥 Ingested 2 company reports

🔍 search('Cloud') → 2 hits
   - Alibaba Cloud 2024
   - Tencent Cloud 2024
✍️  Wrote wiki/synthesis/2024-q3-china-cloud-comparison.md

📚 Index: 3 pages, 4 outbound refs
🕸️  Graph: 3 nodes, 3 edges

🩺 lint: {'broken': 0, 'orphan': 0, 'contradiction': 0}
🎉 Done.
```

## 涉及 API

| API | 用途 |
|---|---|
| `wiki.ingest(src)` × N | 批量 ingest |
| `wiki.search("Cloud", limit=10)` | 跨公司搜索 |
| `wiki.write_page("synthesis/...", ...)` | 落盘综合页 |
| `wiki.build_index()` | 重建引用索引 |
| `GraphAnalyzer(wiki).build_graph()` | 知识图谱构建 |
| `wiki.lint()` | 健康检查 |

## LLM 增强版（需 OPENAI_API_KEY）

```bash
export OPENAI_API_KEY=sk-...
llmwikify init   # 然后把 fixtures 拷到 raw/
llmwikify batch raw/reports/ --self-create
llmwikify analyze-source raw/reports/alibaba-cloud-2024.md --force
llmwikify graph-analyze --json
llmwikify suggest-synthesis
llmwikify synthesize --query "2024 Q3 中国云份额" \
    --source-pages "Alibaba Cloud 2024,Tencent Cloud 2024"
```

## 对应 TUTORIAL 节

- §2.3 步骤 1-7
- §2.5 故障排查
