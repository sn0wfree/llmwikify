"""``dict`` command — manage jieba segmentation dictionary."""

from __future__ import annotations

import json
from typing import Any

from .._base import Command


def run_dict(wiki: Any, args: Any) -> int:
    """Manage the jieba user dictionary for the wiki."""
    from ....kernel import Wiki

    if not isinstance(wiki, Wiki):
        wiki = Wiki(wiki)
    action = getattr(args, "action", "update")

    if action == "status":
        meta_path = wiki.root / ".wiki" / "jieba.meta.json"
        if meta_path.exists():
            print(json.dumps(json.loads(meta_path.read_text()), indent=2))
        else:
            print("No jieba dict generated yet. Run `llmwikify dict update`.")
        return 0

    # action == "update"
    from ....kernel.storage.jieba_dict_gen import generate_user_dict

    result = generate_user_dict(wiki.db_path, wiki.root)
    print(f"Fast terms: {result['fast']}  Slow terms: {result['slow']}  Pages: {result['page_count']}")
    return 0


class DictCommand(Command):
    """``dict`` command — manage jieba segmentation dictionary."""

    name = "dict"
    help = "Manage jieba segmentation dictionary"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        p = subparsers.add_parser(self.name, help=self.help)
        p.add_argument(
            "action", nargs="?", default="update",
            choices=["update", "status"],
            help="update: regenerate dict (default) | status: show meta",
        )
        p.add_argument(
            "--fast", action="store_true",
            help="Only run fast generation (frequency + TF-IDF)",
        )
        p.add_argument(
            "--pmi", action="store_true",
            help="Only run slow generation (PMI collocations)",
        )

    def run(self, args: Any, wiki: Any, config: dict[str, Any]) -> int:
        return run_dict(wiki, args)
