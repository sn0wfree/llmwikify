#!/usr/bin/env python3
"""Fix slides with layout='swot' but missing swot data.

Usage:
    python scripts/fix_swot_slide.py <task_id>

Reconstructs swot data from available context or adds placeholder data.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

AGENT_DB = Path.home() / ".llmwikify" / "agent" / ".llmwiki_agent.db"


def fix_swot_slides(task_id: str) -> None:
    with sqlite3.connect(AGENT_DB) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT presentation_json FROM ppt_tasks WHERE id = ?",
            (task_id,),
        ).fetchone()

        if not row:
            print(f"❌ Task {task_id} not found")
            sys.exit(1)

        pres = json.loads(row[0])
        slides = pres.get("slides", [])
        fixed = 0

        for slide in slides:
            if slide.get("layout") == "swot" and not slide.get("swot"):
                # Slide has swot layout but no swot data - add placeholder
                slide["swot"] = {
                    "strengths": ["（待补充）"],
                    "weaknesses": ["（待补充）"],
                    "opportunities": ["（待补充）"],
                    "threats": ["（待补充）"],
                }
                fixed += 1
                print(f"  Fixed slide '{slide.get('title', 'untitled')}' (id={slide.get('id')})")

        if fixed > 0:
            conn.execute(
                "UPDATE ppt_tasks SET presentation_json = ? WHERE id = ?",
                (json.dumps(pres, ensure_ascii=False), task_id),
            )
            conn.commit()
            print(f"✅ Fixed {fixed} slide(s) in task {task_id}")
        else:
            print(f"✅ No swot slides need fixing in task {task_id}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/fix_swot_slide.py <task_id>")
        sys.exit(1)
    fix_swot_slides(sys.argv[1])
