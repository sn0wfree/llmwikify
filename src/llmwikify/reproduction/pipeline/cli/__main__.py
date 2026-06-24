"""CLI entry point for reproduction pipeline."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="llmwikify.reproduction.cli")
    sub = parser.add_subparsers(dest="command")

    # run command
    run_p = sub.add_parser("run")
    run_p.add_argument("workspace")
    run_p.add_argument("--start", type=int, default=1)
    run_p.add_argument("--end", type=int, default=101)
    run_p.add_argument("--skip-existing", action="store_true")

    # prompts command
    prompts_p = sub.add_parser("prompts")
    prompts_sub = prompts_p.add_subparsers(dest="subcommand")
    list_p = prompts_sub.add_parser("list")
    list_p.add_argument("workspace")

    # list command
    sub.add_parser("list")

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        print(f"Running workspace={args.workspace} start={args.start} end={args.end}")
    elif args.command == "prompts":
        print(f"Prompts for workspace={args.workspace}")
    elif args.command == "list":
        print("Listing workspaces...")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
