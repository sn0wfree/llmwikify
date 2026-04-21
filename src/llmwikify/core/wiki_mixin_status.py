"""Wiki status mixin — wiki status reporting, orphan detection config."""

import logging

logger = logging.getLogger(__name__)


class WikiStatusMixin:
    """Wiki status reporting and orphan detection configuration."""

    def _should_exclude_orphan(self, page_name: str, page_path) -> bool:
        """Check if a page should be excluded from orphan detection."""
        import re
        page_name_lower = page_name.lower()

        for pattern in self._default_exclude_patterns:
            if re.match(pattern, page_name_lower):
                return True

        for pattern in self._user_exclude_patterns:
            if re.match(pattern, page_name_lower):
                return True

        if page_path.exists():
            content = page_path.read_text()
            for key in self._exclude_frontmatter_keys:
                if f"{key}:" in content:
                    return True

        try:
            rel_path = page_path.relative_to(self.wiki_dir)
            for part in rel_path.parts:
                if part.lower() in self._archive_dirs:
                    return True
        except ValueError:
            pass

        return False

    def status(self) -> dict:
        """Get wiki status."""
        result = {
            "initialized": self.is_initialized(),
            "root": str(self.root),
            "page_count": len(self._wiki_pages()),
            "source_count": len([f for f in self.raw_dir.rglob("*") if f.is_file()]),
            "indexed_pages": self.index.get_page_count() if self.is_initialized() else "N/A",
            "total_links": self.index.get_link_count() if self.is_initialized() else "N/A",
        }

        pages_by_type = {}
        for subdir in ["sources", "entities", "concepts", "comparisons", "synthesis", "claims"]:
            sub_path = self.wiki_dir / subdir
            if sub_path.exists():
                pages_by_type[subdir] = sorted(
                    str(p.relative_to(self.wiki_dir))[:-3]
                    for p in sub_path.rglob("*.md")
                )
        root_pages = [
            str(p.relative_to(self.wiki_dir))[:-3]
            for p in self.wiki_dir.glob("*.md")
            if p.stem not in ("index", "log")
        ]
        if root_pages:
            pages_by_type["root"] = sorted(root_pages)
        result["pages_by_type"] = pages_by_type

        if self.is_initialized():
            try:
                engine = self.get_relation_engine()
                stats = engine.get_stats()
                result["graph_stats"] = stats
            except Exception:
                logger.debug("Failed to load graph stats")
                result["graph_stats"] = {"total_relations": 0, "unique_concepts": 0}

        return result

    def recommend(self) -> dict:
        """Generate smart recommendations."""
        import re
        missing_pages = []
        orphan_pages = []

        link_counts = {}
        for page in self._wiki_pages():
            content = page.read_text()
            links = re.findall(r'\[\[(.*?)\]\]', content)
            for link in links:
                target = link.split('|')[0].split('#')[0].strip()
                if target not in (self._index_page_name, self._log_page_name):
                    link_counts[target] = link_counts.get(target, 0) + 1

        for target, count in link_counts.items():
            if count >= 2:
                if self._resolve_wikilink_target(target) is None:
                    missing_pages.append({
                        "page": target,
                        "reference_count": count,
                    })

        for page in self._wiki_pages():
            page_name = self._page_display_name(page)

            if self._should_exclude_orphan(page_name, page):
                continue

            inbound = self.index.get_inbound_links(page_name)
            if not inbound:
                orphan_pages.append({"page": page_name})

        return {
            "missing_pages": missing_pages,
            "orphan_pages": orphan_pages,
            "summary": {
                "total_missing_pages": len(missing_pages),
                "total_orphans": len(orphan_pages),
            },
        }

    def hint(self) -> dict:
        """Generate smart suggestions for wiki improvement.

        Deprecated: Use `lint(format="brief")` instead.
        """
        import warnings
        warnings.warn(
            "hint() is deprecated; use wiki.lint(format='brief') instead",
            DeprecationWarning,
            stacklevel=2,
        )
        return self._generate_hints()

    def _generate_hints(self) -> dict:
        """Internal: generate smart suggestions for wiki improvement."""
        import re
        hints = []

        orphan_count = 0
        for page in self._wiki_pages():
            page_name = self._page_display_name(page)
            if self._should_exclude_orphan(page_name, page):
                continue
            inbound = self.index.get_inbound_links(page_name)
            if not inbound:
                orphan_count += 1

        if orphan_count > 0:
            hints.append({
                "type": "orphan",
                "priority": "medium",
                "message": f"You have {orphan_count} orphan page(s). Consider adding cross-references to connect them.",
            })

        link_counts = {}
        for page in self._wiki_pages():
            content = page.read_text()
            links = re.findall(r'\[\[(.*?)\]\]', content)
            for link in links:
                target = link.split('|')[0].split('#')[0].strip()
                if target not in (self._index_page_name, self._log_page_name):
                    link_counts[target] = link_counts.get(target, 0) + 1

        missing = []
        for target, count in link_counts.items():
            if count >= 2:
                if self._resolve_wikilink_target(target) is None:
                    missing.append(target)

        if missing:
            hints.append({
                "type": "missing",
                "priority": "high",
                "message": f"Pages referenced but don't exist: {', '.join(missing[:5])}",
            })

        page_count = len(self._wiki_pages())
        if page_count < 5:
            hints.append({
                "type": "growth",
                "priority": "low",
                "message": "Wiki is small. Consider ingesting more sources to build knowledge.",
            })
        elif page_count < 20:
            hints.append({
                "type": "growth",
                "priority": "low",
                "message": "Wiki is growing well. Consider running lint to check health.",
            })

        broken_count = 0
        for page in self._wiki_pages():
            content = page.read_text()
            links = re.findall(r'\[\[(.*?)\]\]', content)
            for link in links:
                target = link.split('|')[0].split('#')[0].strip()
                if target in (self._index_page_name, self._log_page_name):
                    continue
                if self._resolve_wikilink_target(target) is None:
                    broken_count += 1

        if broken_count > 0:
            hints.append({
                "type": "broken_links",
                "priority": "high",
                "message": f"Found {broken_count} broken link(s). Consider fixing or removing them.",
            })

        return {
            "hints": hints,
            "summary": {
                "total_hints": len(hints),
                "high_priority": sum(1 for h in hints if h['priority'] == 'high'),
            }
        }
