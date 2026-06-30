"""
03 — 多 wiki 注册表（in-process）

对应 TUTORIAL.md §场景 3
======================

演示：
1. 创建 3 个独立 wiki（个人/项目/学习）
2. 用 WikiRegistry 统一管理
3. 在代码里做"跨 wiki 检索"模拟
4. 列 / 切换 / 扫描

注意：本剧本不启动 server（多 wiki server 启动见 TUTORIAL §3.2
Step 3 的 llmwikify serve --multi-wiki 命令）。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from llmwikify import create_wiki
from llmwikify.kernel.multi_wiki import (
    WikiInstance,
    WikiRegistry,
    WikiType,
)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        # Step 1：建 3 个 wiki
        personal = Path(tmp) / "personal"
        project = Path(tmp) / "project"
        study = Path(tmp) / "study"

        for label, p in [("personal", personal), ("project", project),
                         ("study", study)]:
            w = create_wiki(p)
            w.init(agent="generic")
            # 写一条占位页面，便于后续 search
            w.write_page(f"welcome-{label}",
                         f"# Welcome to {label}\n\nSome notes about {label}.")
            w.close()

        # Step 2：构造 Registry 并注册 3 个 local wiki
        from llmwikify.foundation.config import load_config
        config = load_config(personal)  # 用其中一个 wiki 读默认 config

        registry = WikiRegistry(config)
        registry.initialize()

        for label, p, name in [
            ("personal", personal, "Personal Wiki"),
            ("project", project, "Project Wiki"),
            ("study", study, "Study Notes"),
        ]:
            inst = registry.register_wiki(
                wiki_id=label, name=name, root=p,
            )
            print(f"📌 Registered: {inst.wiki_id} ({inst.wiki_type.value}) → {inst.root}")

        # Step 3：list
        all_wikis = registry.list_wikis()
        print(f"\n📋 Total wikis: {len(all_wikis)}")
        for w in all_wikis:
            print(f"   - {w.wiki_id:10s} {w.name:20s} {w.wiki_type.value}")

        # Step 4：set_default_wiki
        registry.set_default_wiki("project")
        default_id = registry.get_default_wiki_id()
        print(f"\n🎯 Default: {default_id}")

        # Step 5：跨 wiki 检索（直接在代码里 iter）
        print("\n🔍 Cross-wiki search for 'Welcome':")
        for inst in all_wikis:
            w = create_wiki(inst.root)
            hits = w.search("Welcome", limit=2)
            print(f"   {inst.wiki_id:10s} → {len(hits)} hits")
            for h in hits:
                print(f"      - {h.get('page_name', '?')}")
            w.close()

        # Step 6：scan（用 discovery 找同级目录）
        from llmwikify.kernel.multi_wiki.discovery import WikiDiscovery
        disc = WikiDiscovery()
        found = disc.scan([tmp], depth=2)
        print(f"\n🛰️  Discovery scan([{tmp}], depth=2): {len(found)} wikis")
        for inst in found:
            print(f"   - {inst['wiki_id']} root={inst['root']}")

        print(f"\n🎉 Done. Registry has {len(registry.list_wikis())} wikis.")


if __name__ == "__main__":
    main()
    sys.exit(0)
