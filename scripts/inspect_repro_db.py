"""Inspect a CKbase .llmwikify.db for graph-repro planning."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def main() -> None:
    db = Path(sys.argv[1])
    conn = sqlite3.connect(db)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    print("db:", db)
    print("tables:", tables)
    for t in ("pages", "page_links", "relations"):
        if t in tables:
            n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"{t}: {n}")
    if "page_links" in tables:
        uniq = conn.execute(
            "SELECT COUNT(*) FROM (SELECT DISTINCT source_page, target_page FROM page_links)"
        ).fetchone()[0]
        print("unique_page_links:", uniq)
    print("wiki_dir_exists:", (db.parent / "wiki").is_dir())


if __name__ == "__main__":
    main()
