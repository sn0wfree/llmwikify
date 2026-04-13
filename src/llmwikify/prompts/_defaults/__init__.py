"""Built-in default prompt templates.

Available prompts:
- analyze_source
- generate_wiki_ops
- ingest_instructions
- investigate_lint
- wiki_schema
- wiki_synthesize
"""

from pathlib import Path

PROMPTS_DIR = Path(__file__).parent

AVAILABLE_PROMPTS = [
    "analyze_source",
    "generate_wiki_ops",
    "ingest_instructions",
    "investigate_lint",
    "wiki_schema",
    "wiki_synthesize",
]

__all__ = ["PROMPTS_DIR", "AVAILABLE_PROMPTS"]
