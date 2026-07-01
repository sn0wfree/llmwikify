"""
02 — 公司尽调知识库（无 LLM 版）

对应 TUTORIAL.md §场景 2
======================

演示：
1. 批量 ingest 多份"公司报告"
2. search + get_references 跨页面
3. 手写 synthesize 落盘（不调 LLM）
4. 知识图谱导出 HTML

注意：本剧本不调 LLM（不需要 OPENAI_API_KEY）。analyze-source / 真
synthesize 走 LLM 的步骤在 TUTORIAL §2.3 详述。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

from llmwikify import create_wiki

FIXTURES = Path(__file__).parent / "fixtures"


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        wiki_path = Path(tmp) / "due-diligence"

        # Step 0：准备 raw/
        (wiki_path / "raw" / "reports").mkdir(parents=True)
        for f in FIXTURES.glob("*.md"):
            shutil.copy(f, wiki_path / "raw" / "reports" / f.name)

        wiki = create_wiki(wiki_path)
        wiki.init(agent="generic")

        # Step 1：批量 ingest + 写 source 页面
        sources = list((wiki_path / "raw" / "reports").glob("*.md"))
        for src in sources:
            wiki.ingest_source(str(src))
            page_name = "sources/" + src.stem
            wiki.write_page(page_name, src.read_text())
        print(f"📥 Ingested + wrote {len(sources)} company report pages")

        # Step 2：search 跨公司
        hits = wiki.search("Cloud", limit=10)
        print(f"\n🔍 search('Cloud') → {len(hits)} hits")
        for h in hits:
            print(f"   - {h.get('page_name', '?')}")

        # Step 3：手写 synthesize（落盘到 wiki/synthesis/）
        wiki.write_page(
            "synthesis/2024-q3-china-cloud-comparison",
            "# 2024 Q3 中国云市场份额对比\n\n"
            "## Top 3\n\n"
            "- **[[Alibaba Cloud 2024]]** — ¥33.5B (市场第一)\n"
            "- **[[Tencent Cloud 2024]]** — ¥21.7B (市场第二)\n"
            "- (待补) [[Huawei Cloud]]\n\n"
            "## 跨源引用\n\n"
            "两家公司均在报告中提到 [[Huawei Cloud]] 为竞争对手。\n",
        )
        print("✍️  Wrote wiki/synthesis/2024-q3-china-cloud-comparison.md")

        # Step 4：build-index + 关系
        idx = wiki.build_index()
        total_refs = sum(
            len(v) for v in idx.get("outbound_links", {}).values()
        )
        print(f"\n📚 Index: {idx.get('total_pages', 0)} pages, "
              f"{total_refs} outbound refs")

        # Step 5：graph 导出 JSON（pyvis HTML 需要 graph extra，未必装了）
        try:
            from llmwikify.kernel.graph import GraphAnalyzer
            analyzer = GraphAnalyzer(wiki)
            result = analyzer.analyze()
            stats = result.get("stats", {})
            print(f"🕸️  Graph: {stats.get('nodes', 0)} nodes, "
                  f"{stats.get('edges', 0)} edges, "
                  f"{stats.get('communities', 0)} communities")
        except (ImportError, AttributeError) as e:
            print(f"🕸️  GraphAnalyzer: {e}")

        # Step 6：lint
        lint = wiki.lint()
        print(f"\n🩺 lint: issue_count={lint.get('issue_count', 0)}")

        wiki.close()
        print(f"\n🎉 Done. Try: cd {wiki_path} && ls -R wiki/")


if __name__ == "__main__":
    main()
    sys.exit(0)
