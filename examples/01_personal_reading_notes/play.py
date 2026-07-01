"""
01 — 个人阅读笔记 wiki

对应 TUTORIAL.md §场景 1
=====================

演示：
1. init
2. ingest（单文件 + 批量）
3. search
4. write_page
5. build-index
6. references
7. lint

剧本规模：~50 行，可独立 `python play.py` 跑。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from llmwikify import create_wiki

FIXTURES = Path(__file__).parent / "fixtures"


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        wiki_path = Path(tmp) / "my-notes"

        # Step 0：把 fixture 拷到 raw/，模拟"我从网上下载的 PDF"
        (wiki_path / "raw").mkdir(parents=True)
        for f in FIXTURES.glob("*.md"):
            shutil.copy(f, wiki_path / "raw" / f.name)
        print(f"📥 Copied {len(list(FIXTURES.glob('*.md')))} fixtures to raw/")

        # Step 1：init（不传 agent，跳过 MCP config 生成）
        wiki = create_wiki(wiki_path)
        wiki.init(agent="generic")
        print(f"✅ Wiki initialized at {wiki_path}")
        print(f"   raw/   = {wiki.raw_dir}")
        print(f"   wiki/  = {wiki.wiki_dir}")

        # Step 2：ingest_source（只 extract + 写 raw/，不调 LLM）
        for src in (wiki_path / "raw").glob("*.md"):
            result = wiki.ingest_source(str(src))
            print(f"📄 Ingested {src.name} → status={result.get('status', '?')}")

        # Step 3：手写 create 几个页面（生产里是 LLM 拆出来的）
        wiki.write_page(
            "sources/karpathy-llm-wiki",
            (FIXTURES / "karpathy-llm-wiki.md").read_text(),
        )
        wiki.write_page(
            "sources/andrew-ng-ai-notes",
            (FIXTURES / "andrew-ng-ai-notes.md").read_text(),
        )
        print("✍️  Created 2 source pages from fixtures")

        # Step 4：search
        hits = wiki.search("LLM wiki", limit=5)
        print(f"\n🔍 search('LLM wiki') → {len(hits)} hits")
        for h in hits[:3]:
            print(f"   - {h.get('page_name', '?')}: {h.get('snippet', '')[:60]}...")

        # Step 5：手写一笔记页面（带 [[wikilink]]）
        wiki.write_page(
            "concepts/bidirectional-references",
            "# 双向引用\n\n[[sources/karpathy-llm-wiki]] 的核心概念。\n\n"
            "详见 [[sources/andrew-ng-ai-notes]]。\n",
        )
        print("\n✍️  Wrote wiki/concepts/bidirectional-references.md")

        # Step 6：build-index
        idx = wiki.build_index()
        print(f"📚 Index built: {idx.get('total_pages', 0)} pages, "
              f"{idx.get('total_references', 0)} references")

        # Step 7：references
        inb = wiki.get_inbound_links("concepts/bidirectional-references")
        outb = wiki.get_outbound_links("concepts/bidirectional-references")
        print(f"🔗 inbound={len(inb)} outbound={len(outb)}")

        # Step 8：lint
        lint = wiki.lint()
        print(f"🩺 lint: issue_count={lint.get('issue_count', 0)}")

        wiki.close()
        print(f"\n🎉 Done. Try: cd {wiki_path} && ls -R wiki/")


if __name__ == "__main__":
    main()
    sys.exit(0)
