"""write_page / read_page 的 page_type 路径对称性回归测试 (2026-10).

Bug: write_page 的 page_type 分支缺少 "/" 守卫 — 含路径的页名会被再次
拼接目录 (write_page("sources/Probe", type="ResearchReport") 落到
sources/sources/Probe.md), 而 read_page 有守卫 (按原始路径读
sources/Probe.md) — 同一组参数写进去、读不出来。

修复: page_io.py write_page 镜像 read_page 的守卫
(``if page_type and "/" not in page_name``)。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llmwikify.kernel.wiki.wiki import Wiki

WIKI_MD = """# Test Wiki

## Page Types

| Type | Location | Purpose |
|------|----------|---------|
| ResearchReport | `wiki/sources/{slug}.md` | 研报 |
| Viewpoint | `wiki/viewpoints/{slug}.md` | 观点 |
"""


@pytest.fixture
def wiki(tmp_path: Path) -> Wiki:
    """初始化临时 wiki, 并写入确定的 Page Types 映射."""
    w = Wiki(tmp_path)
    w.init(agent="generic")
    w.wiki_md_file.write_text(WIKI_MD)
    assert w._load_page_type_mapping() == {
        "ResearchReport": "sources",
        "Viewpoint": "viewpoints",
    }
    yield w
    w.close()


class TestWritePagePageTypePathSymmetry:
    """含路径页名 + page_type 时, write/read 使用同一路径解析."""

    def test_path_name_with_type_writes_single_prefix(self, wiki: Wiki):
        """write_page("sources/X", type) 只写 sources/X.md, 不再写双层目录."""
        result = wiki.write_page(
            "sources/Probe", "# Probe\n", page_type="ResearchReport"
        )
        assert (wiki.wiki_dir / "sources" / "Probe.md").exists()
        assert not (wiki.wiki_dir / "sources" / "sources" / "Probe.md").exists()
        assert "sources/Probe" in result

    def test_write_read_round_trip_with_path_name_and_type(self, wiki: Wiki):
        """同参数 write → read 往返一致 (不对称回归测试)."""
        wiki.write_page(
            "sources/Probe", "# Probe\n\n正文内容 Body\n", page_type="ResearchReport"
        )
        result = wiki.read_page("sources/Probe", page_type="ResearchReport")
        assert "error" not in result
        assert "Body" in result["content"]

    def test_plain_name_with_type_still_maps_to_directory(self, wiki: Wiki):
        """防回归: 纯名 + type 仍按映射解析目录."""
        wiki.write_page("Probe", "# Probe\n", page_type="ResearchReport")
        assert (wiki.wiki_dir / "sources" / "Probe.md").exists()

    def test_plain_name_without_type_writes_to_root(self, wiki: Wiki):
        """防回归: 纯名无 type 写入 wiki/ 根."""
        wiki.write_page("Probe", "# Probe\n")
        assert (wiki.wiki_dir / "Probe.md").exists()
