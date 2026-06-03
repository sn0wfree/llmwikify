#!/usr/bin/env python3
"""One-shot repair script for PPT tasks with partial-format presentation_json.

Usage:
    python scripts/repair_corrupted_ppt_task.py <task_id>

Prints the before/after state and updates the DB row in-place.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

AGENT_DB = Path.home() / ".llmwikify" / "agent" / ".llmwiki_agent.db"


def repair_task(task_id: str) -> None:
    with sqlite3.connect(AGENT_DB) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, title, subtitle, theme, source_type, source_id, "
            "presentation_json, slide_count "
            "FROM ppt_tasks WHERE id = ?",
            (task_id,),
        ).fetchone()

        if not row:
            print(f"❌ Task {task_id} not found")
            sys.exit(1)

        raw = row["presentation_json"]
        if not raw:
            print(f"❌ Task {task_id} has no presentation_json")
            sys.exit(1)

        pres_dict = json.loads(raw)
        before_keys = sorted(pres_dict.keys()) if isinstance(pres_dict, dict) else "NOT A DICT"
        print(f"Before keys: {before_keys}")
        is_partial = isinstance(pres_dict, dict) and "partial" in pres_dict
        print(f"Is partial: {is_partial}")

        if not is_partial:
            print(f"✅ Task {task_id} already has full format — nothing to repair")
            return

        # Reconstruct full Presentation dict from row fields + stored slides
        slides = pres_dict.get("slides", [])
        full_pres = {
            "title": row["title"] or "Untitled",
            "subtitle": row["subtitle"] or "",
            "theme": {"id": row["theme"] or "minimal-white"},
            "source": {"type": row["source_type"] or "topic", "id": row["source_id"]},
            "slides": slides,
        }

        new_json = json.dumps(full_pres, ensure_ascii=False)
        conn.execute(
            "UPDATE ppt_tasks SET presentation_json = ?, slide_count = ? WHERE id = ?",
            (new_json, len(slides), task_id),
        )
        conn.commit()

        after_keys = sorted(full_pres.keys())
        print(f"After keys:  {after_keys}")
        print(f"Slides: {len(slides)}")
        print(f"✅ Task {task_id} repaired successfully")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/repair_corrupted_ppt_task.py <task_id>")
        sys.exit(1)
    repair_task(sys.argv[1])
