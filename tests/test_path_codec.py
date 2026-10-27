"""Unit tests for kernel.path_codec (Windows FS-safe page names)."""

from __future__ import annotations

import os

from llmwikify.kernel.path_codec import from_fs_name, to_fs_name


class TestPathCodec:
    def test_linux_identity(self):
        if os.name == "nt":
            return
        assert to_fs_name("Query: Gold") == "Query: Gold"
        assert from_fs_name("Query: Gold") == "Query: Gold"

    def test_windows_roundtrip(self):
        if os.name != "nt":
            return
        logical = "Query: Gold Mining"
        fs = to_fs_name(logical)
        assert ":" not in fs
        assert "：" in fs
        assert from_fs_name(fs) == logical

    def test_no_colon_unchanged(self):
        name = "concepts/Factor Investing"
        assert to_fs_name(name) == name
        assert from_fs_name(name) == name

    def test_multiple_colons(self):
        logical = "A: B: C"
        if os.name == "nt":
            fs = to_fs_name(logical)
            assert fs.count("：") == 2
            assert from_fs_name(fs) == logical
        else:
            assert to_fs_name(logical) == logical

    def test_empty(self):
        assert to_fs_name("") == ""
        assert from_fs_name("") == ""
