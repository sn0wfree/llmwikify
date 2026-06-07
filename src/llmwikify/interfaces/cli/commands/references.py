"""``references`` command — show page references / stats / broken."""

from __future__ import annotations

import re
from typing import Any

from .._base import Command


def _show_reference_stats(wiki: Any, args: Any) -> int:
    """Show reference statistics."""
    top = getattr(args, "top", 10)

    inbound_counts: dict[str, int] = {}
    outbound_counts: dict[str, int] = {}
    orphans: list[str] = []

    for page_path in wiki._wiki_pages():
        page_name = wiki._page_display_name(page_path)

        inbound = wiki.index.get_inbound_links(page_name)
        outbound = wiki.index.get_outbound_links(page_name)

        inbound_counts[page_name] = len(inbound)
        outbound_counts[page_name] = len(outbound)

        if not inbound and not wiki._should_exclude_orphan(page_name, page_path):
            orphans.append(page_name)

    top_inbound = sorted(inbound_counts.items(), key=lambda x: -x[1])[:top]
    top_outbound = sorted(outbound_counts.items(), key=lambda x: -x[1])[:top]

    print("=== Reference Statistics ===\n")

    print(f"📈 Most Linked-To Pages (Top {top}):")
    for page_name, count in top_inbound:
        print(f"  {page_name}: {count} inbound")
    print()

    print(f"📊 Most Active Pages (Top {top}):")
    for page_name, count in top_outbound:
        print(f"  {page_name}: {count} outbound")
    print()

    if orphans:
        print(f"🟠 Orphan Pages ({len(orphans)}):")
        for page_name in orphans[:top]:
            print(f"  {page_name}")
    else:
        print("✅ No orphan pages")

    return 0


def _show_broken_references(wiki: Any, args: Any) -> int:
    """Show broken references."""
    broken = []

    for page in wiki._wiki_pages():
        content = page.read_text()
        links = re.findall(r"\[\[(.*?)\]\]", content)
        for link in links:
            target = wiki._parse_wikilink_target(link)
            if target in (wiki._index_page_name, wiki._log_page_name):
                continue
            if wiki._resolve_wikilink_target(target) is None:
                broken.append({
                    "source": wiki._page_display_name(page),
                    "target": target,
                    "file": str(page),
                })

    print("=== Broken References ===\n")

    if broken:
        for ref in broken:
            print(f"  ❌ {ref['source']} → [[{ref['target']}]]")
        print(f"\nTotal: {len(broken)} broken link(s)")
    else:
        print("✅ No broken references")

    return 0


def run_references(wiki: Any, args: Any) -> int:
    """Show page references.

    Args:
        wiki: A Wiki instance (or any object with
            ``get_inbound_links``, ``get_outbound_links``,
            ``_wiki_pages``, ``_page_display_name``,
            ``_should_exclude_orphan``, ``_parse_wikilink_target``,
            ``_resolve_wikilink_target``, ``_index_page_name``,
            ``_log_page_name``).
        args: Parsed argparse Namespace with ``page``, ``detail``,
            ``inbound``, ``outbound``, ``stats``, ``broken``, ``top``.

    Returns:
        0 on success.
    """
    page_name = args.page
    detail = getattr(args, "detail", False)
    inbound_only = getattr(args, "inbound", False)
    outbound_only = getattr(args, "outbound", False)
    stats = getattr(args, "stats", False)
    broken = getattr(args, "broken", False)

    if stats:
        return _show_reference_stats(wiki, args)

    if broken:
        return _show_broken_references(wiki, args)

    print(f"=== References: {page_name} ===\n")

    if not inbound_only:
        outbound = wiki.get_outbound_links(page_name, include_context=detail)
        if not outbound_only:
            inbound = wiki.get_inbound_links(page_name, include_context=detail)

            print(f"Inbound ({len(inbound)})")
            if inbound:
                for i, link in enumerate(inbound, 1):
                    section = link.get("section", "")
                    print(f"  {i}. {link['source']} → {section}")
                    if detail and link.get("context"):
                        print(f"     Context: \"{link['context']}\"")
                print()
            else:
                print("  (none)\n")

        print(f"Outbound ({len(outbound)})")
        if outbound:
            for i, link in enumerate(outbound, 1):
                section = link.get("section", "")
                display = link.get("display", "")
                display_str = f' [as "{display}"]' if display and display != link.get("target", "") else ""
                print(f"  {i}. {link['target']}{section}{display_str}")
                if detail and link.get("context"):
                    print(f"     Context: \"{link['context']}\"")
            print()
        else:
            print("  (none)\n")
    else:
        inbound = wiki.get_inbound_links(page_name, include_context=detail)
        print(f"Inbound ({len(inbound)})")
        if inbound:
            for i, link in enumerate(inbound, 1):
                section = link.get("section", "")
                print(f"  {i}. {link['source']} → {section}")
                if detail and link.get("context"):
                    print(f"     Context: \"{link['context']}\"")
            print()
        else:
            print("  (none)\n")

    if not detail:
        print("---\n💡 Use --detail for full context")

    return 0


class ReferencesCommand(Command):
    """``references`` command — show page references."""

    name = "references"
    help = "Show page references"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        p = subparsers.add_parser(self.name, help=self.help)
        p.add_argument("page", help="Page name")
        p.add_argument("--detail", "-d", action="store_true", help="Show full context")
        p.add_argument("--inbound", "-i", action="store_true", help="Show only inbound")
        p.add_argument("--outbound", "-o", action="store_true", help="Show only outbound")
        p.add_argument("--stats", "-s", action="store_true", help="Show reference statistics")
        p.add_argument("--broken", "-b", action="store_true", help="Show broken references")
        p.add_argument("--top", "-t", type=int, default=10, help="Top N for stats")

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_references(wiki, args)
