"""Tests for Phase 14E: CLI entry point."""
from __future__ import annotations

import pytest

from llmwikify.reproduction.pipeline.cli.__main__ import build_parser, main


class TestBuildParser:
    def test_creates_parser(self):
        parser = build_parser()
        assert parser is not None

    def test_run_command(self):
        parser = build_parser()
        args = parser.parse_args(["run", "ws1", "--start", "5", "--end", "50"])
        assert args.command == "run"
        assert args.workspace == "ws1"
        assert args.start == 5
        assert args.end == 50
        assert args.skip_existing is False

    def test_run_skip_existing(self):
        parser = build_parser()
        args = parser.parse_args(["run", "ws1", "--skip-existing"])
        assert args.skip_existing is True

    def test_list_command(self):
        parser = build_parser()
        args = parser.parse_args(["list"])
        assert args.command == "list"

    def test_prompts_command(self):
        parser = build_parser()
        args = parser.parse_args(["prompts", "list", "ws1"])
        assert args.command == "prompts"
        assert args.workspace == "ws1"

    def test_no_command(self, capsys):
        main([])
        captured = capsys.readouterr()
        assert "usage:" in captured.out.lower()


class TestMain:
    def test_run_command(self, capsys):
        main(["run", "ws1"])
        captured = capsys.readouterr()
        assert "Running workspace=ws1" in captured.out

    def test_list_command(self, capsys):
        main(["list"])
        captured = capsys.readouterr()
        assert "Listing workspaces" in captured.out
