"""``db`` command — database management (stats / list / clean / export)."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .._base import Command
from .._output import print_error, print_warning


def _resolve_data_dir(wiki: Any) -> Any:
    """Return the data directory for the agent database."""
    return wiki.root / ".llmwikify" / "agent"


def _open_app_db(wiki: Any) -> Any:
    """Open an AppDatabase (auto-creates tables if missing)."""
    from llmwikify.apps.db import AppDatabase
    return AppDatabase(_resolve_data_dir(wiki))


def _get_db_stats(app_db: Any) -> dict:
    """Compute DB statistics across all 3 facades."""
    db_path = app_db.db_path
    if not db_path.exists():
        return None
    stats: dict = {}
    with sqlite3.connect(db_path) as conn:
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for table in sorted(tables):
            try:
                row = conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()
                stats[table] = row[0] if row else 0
            except Exception:
                stats[table] = 0
        size_mb = db_path.stat().st_size / 1024 / 1024
    return {"tables": stats, "size_mb": round(size_mb, 2)}


def _get_wiki_stats(app_db: Any, wiki_id: str) -> dict:
    """Count rows for a specific wiki_id across facades."""
    db_path = app_db.db_path
    out = {"wiki_id": wiki_id, "chat_sessions": 0, "research_sessions": 0,
           "research_sources": 0, "tool_calls": 0, "ingest_log": 0,
           "dream_proposals": 0, "notifications": 0,
           "confirmations": 0}
    with sqlite3.connect(db_path) as conn:
        def count(sql):
            r = conn.execute(sql, (wiki_id,)).fetchone()
            return r[0] if r else 0
        try:
            out["chat_sessions"] = count(
                "SELECT COUNT(*) FROM chat_sessions WHERE wiki_id = ?"
            )
        except Exception:
            pass
        try:
            out["research_sessions"] = count(
                "SELECT COUNT(*) FROM autoresearch_sessions WHERE wiki_id = ?"
            )
        except Exception:
            pass
        try:
            out["research_sources"] = count(
                """SELECT COUNT(*) FROM autoresearch_sources s
                   JOIN autoresearch_sessions s2 ON s.session_id = s2.id
                   WHERE s2.wiki_id = ?"""
            )
        except Exception:
            pass
        try:
            out["tool_calls"] = count(
                """SELECT COUNT(*) FROM tool_calls t
                   JOIN chat_sessions c ON t.session_id = c.id
                   WHERE c.wiki_id = ?"""
            )
        except Exception:
            pass
        for t in ("dream_proposals", "notifications", "confirmations", "ingest_log"):
            try:
                out[t] = count(f"SELECT COUNT(*) FROM {t} WHERE wiki_id = ?")
            except Exception:
                pass
    return out


def _list_all_wikis(app_db: Any) -> list[dict]:
    """Aggregate wiki stats across all facades."""
    db_path = app_db.db_path
    wiki_ids: set[str] = set()
    with sqlite3.connect(db_path) as conn:
        for tbl in ("chat_sessions", "autoresearch_sessions",
                    "dream_proposals", "notifications",
                    "confirmations", "ingest_log"):
            try:
                rows = conn.execute(
                    f"SELECT DISTINCT wiki_id FROM {tbl} WHERE wiki_id IS NOT NULL"
                ).fetchall()
                for r in rows:
                    wiki_ids.add(r[0])
            except Exception:
                pass
    return [
        _get_wiki_stats(app_db, wid) for wid in sorted(wiki_ids)
    ]


def _delete_wiki_data(app_db: Any, wiki_id: str) -> dict:
    """Delete all data for a wiki across facades."""
    db_path = app_db.db_path
    result: dict = {}
    with sqlite3.connect(db_path) as conn:
        deletions = [
            ("chat_sessions", "wiki_id"),
            ("autoresearch_sessions", "wiki_id"),
        ]
        for tbl, col in deletions:
            try:
                cur = conn.execute(
                    f"DELETE FROM {tbl} WHERE {col} = ?", (wiki_id,)
                )
                result[tbl] = cur.rowcount
            except Exception:
                pass
        # Cascading deletes
        try:
            cur = conn.execute(
                """DELETE FROM chat_messages
                   WHERE session_id IN
                   (SELECT id FROM chat_sessions WHERE wiki_id = ?)""",
                (wiki_id,),
            )
            result["chat_messages"] = cur.rowcount
        except Exception:
            pass
        try:
            cur = conn.execute(
                """DELETE FROM autoresearch_sub_queries
                   WHERE session_id IN
                   (SELECT id FROM autoresearch_sessions WHERE wiki_id = ?)""",
                (wiki_id,),
            )
            result["autoresearch_sub_queries"] = cur.rowcount
        except Exception:
            pass
        try:
            cur = conn.execute(
                """DELETE FROM autoresearch_sources
                   WHERE session_id IN
                   (SELECT id FROM autoresearch_sessions WHERE wiki_id = ?)""",
                (wiki_id,),
            )
            result["autoresearch_sources"] = cur.rowcount
        except Exception:
            pass
        for t in ("dream_proposals", "notifications", "confirmations", "ingest_log"):
            try:
                cur = conn.execute(
                    f"DELETE FROM {t} WHERE wiki_id = ?", (wiki_id,)
                )
                result[t] = cur.rowcount
            except Exception:
                pass
        conn.commit()
    return result


def _export_wiki_data(app_db: Any, wiki_id: str) -> dict:
    """Export all wiki data to a JSON-serializable dict."""
    db_path = app_db.db_path
    data: dict = {}
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        # Chat sessions/messages
        try:
            rows = conn.execute(
                "SELECT * FROM chat_sessions WHERE wiki_id = ?", (wiki_id,)
            ).fetchall()
            data["chat_sessions"] = [dict(r) for r in rows]
        except Exception:
            data["chat_sessions"] = []
        try:
            rows = conn.execute(
                """SELECT * FROM chat_messages
                   WHERE session_id IN
                   (SELECT id FROM chat_sessions WHERE wiki_id = ?)""",
                (wiki_id,),
            ).fetchall()
            data["chat_messages"] = [dict(r) for r in rows]
        except Exception:
            data["chat_messages"] = []
        # Research
        for tbl, key in (
            ("autoresearch_sessions", "research_sessions"),
            ("autoresearch_sub_queries", "research_sub_queries"),
            ("autoresearch_sources", "research_sources"),
        ):
            try:
                rows = conn.execute(
                    f"SELECT * FROM {tbl} WHERE wiki_id = ?", (wiki_id,)
                ).fetchall()
                data[key] = [dict(r) for r in rows]
            except Exception:
                data[key] = []
        # Tool calls
        try:
            rows = conn.execute(
                """SELECT * FROM tool_calls
                   WHERE session_id IN
                   (SELECT id FROM chat_sessions WHERE wiki_id = ?)""",
                (wiki_id,),
            ).fetchall()
            data["tool_calls"] = [dict(r) for r in rows]
        except Exception:
            data["tool_calls"] = []
        # Wiki-ops
        for t in ("dream_proposals", "notifications", "confirmations", "ingest_log"):
            try:
                rows = conn.execute(
                    f"SELECT * FROM {t} WHERE wiki_id = ?", (wiki_id,)
                ).fetchall()
                data[t] = [dict(r) for r in rows]
            except Exception:
                data[t] = []
    return data


def _db_stats(wiki: Any, args: Any) -> int:
    """Show database statistics."""
    db_path = _resolve_data_dir(wiki) / ".llmwiki_agent.db"
    if not db_path.exists():
        print_error("No agent database found.")
        return 1

    app_db = _open_app_db(wiki)
    stats = _get_db_stats(app_db)

    print("📊 Database Statistics")
    print(f"   Path: {db_path}")
    print(f"   Size: {stats['size_mb']:.2f} MB")
    print()

    wiki_id = getattr(args, "wiki_id", None)
    if wiki_id:
        wiki_stats = _get_wiki_stats(app_db, wiki_id)
        print(f"   Wiki: {wiki_stats['wiki_id']}")
        print(f"     Chat sessions: {wiki_stats['chat_sessions']}")
        print(f"     Research sessions: {wiki_stats['research_sessions']}")
        print(f"     Research sources: {wiki_stats['research_sources']}")
    else:
        print("   Tables:")
        for table, count in stats["tables"].items():
            print(f"     {table}: {count} rows")

    return 0


def _db_list(wiki: Any, args: Any) -> int:
    """List all wikis."""
    db_path = _resolve_data_dir(wiki) / ".llmwiki_agent.db"
    if not db_path.exists():
        print_error("No agent database found.")
        return 1

    app_db = _open_app_db(wiki)
    wikis = _list_all_wikis(app_db)

    if not wikis:
        print("No wikis found in database.")
        return 0

    print("📋 Wikis in Database")
    print()
    for wiki_entry in wikis:
        print(f"  {wiki_entry['wiki_id']}")
        print(f"    Chat sessions: {wiki_entry['chat_sessions']}")
        print(f"    Research sessions: {wiki_entry['research_sessions']}")
        print(f"    Research sources: {wiki_entry['research_sources']}")
        print()

    return 0


def _db_clean(wiki: Any, args: Any) -> int:
    """Delete all data for a wiki."""
    wiki_id = args.wiki_id
    force = getattr(args, "force", False)

    if not force:
        print_warning(f"This will delete all data for wiki '{wiki_id}'.")
        confirm = input("Type 'yes' to confirm: ")
        if confirm.lower() != "yes":
            print("Cancelled.")
            return 0

    db_path = _resolve_data_dir(wiki) / ".llmwiki_agent.db"
    if not db_path.exists():
        print_error("No agent database found.")
        return 1

    app_db = _open_app_db(wiki)
    result = _delete_wiki_data(app_db, wiki_id)

    print(f"✅ Deleted data for wiki '{wiki_id}':")
    for tbl, count in result.items():
        print(f"   {tbl}: {count}")

    return 0


def _db_export(wiki: Any, args: Any) -> int:
    """Export wiki data to JSON."""
    wiki_id = args.wiki_id
    output = args.output

    db_path = _resolve_data_dir(wiki) / ".llmwiki_agent.db"
    if not db_path.exists():
        print_error("No agent database found.")
        return 1

    app_db = _open_app_db(wiki)
    data = _export_wiki_data(app_db, wiki_id)

    with open(output, "w") as f:
        json.dump(data, f, indent=2, default=str)

    print(f"✅ Exported data for wiki '{wiki_id}' to {output}")
    for tbl, rows in data.items():
        print(f"   {tbl}: {len(rows)}")

    return 0


def run_db(wiki: Any, args: Any) -> int:
    """Database management dispatcher.

    Args:
        wiki: A Wiki instance (used for ``.root``).
        args: Parsed argparse Namespace with ``db_subcommand``.

    Returns:
        0 on success, 1 on error.
    """
    subcommand = getattr(args, "db_subcommand", "stats")

    if subcommand == "stats":
        return _db_stats(wiki, args)
    elif subcommand == "list":
        return _db_list(wiki, args)
    elif subcommand == "clean":
        return _db_clean(wiki, args)
    elif subcommand == "export":
        return _db_export(wiki, args)
    else:
        print(f"Unknown db subcommand: {subcommand}")
        return 1


class DbCommand(Command):
    """``db`` command — database management."""

    name = "db"
    help = "Database management commands"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        db_parsers = subparsers.add_parser(self.name, help=self.help)
        db_sub = db_parsers.add_subparsers(dest="db_subcommand", help="DB subcommands")

        # db stats
        p = db_sub.add_parser("stats", help="Show database statistics")
        p.add_argument("wiki_id", nargs="?", help="Wiki ID (optional, shows all if omitted)")

        # db list
        db_sub.add_parser("list", help="List all wikis")

        # db clean
        p = db_sub.add_parser("clean", help="Delete all data for a wiki")
        p.add_argument("wiki_id", help="Wiki ID to delete")
        p.add_argument("--force", "-f", action="store_true", help="Skip confirmation")

        # db export
        p = db_sub.add_parser("export", help="Export wiki data to JSON")
        p.add_argument("wiki_id", help="Wiki ID to export")
        p.add_argument("output", help="Output file path")

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_db(wiki, args)
