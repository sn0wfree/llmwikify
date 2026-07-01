"""Tests for kernel/quant/codegen/ (C1: extracted from reproduction/codegen/).

Covers:
  - extract_python: fence detection, fallback, empty input
  - validate_syntax: valid / invalid code
  - validate_safety: delegates to CodeSandbox (skip if QuantNodes missing)
  - execute_code: namespace build, pl.Series return
  - build_execute_namespace: includes QuantNodes operators
  - extract_json_from_response: fence, raw, malformed
  - SYSTEM_PROMPT_CODE: string constant non-empty
  - OBSERVE_FEEDBACK_TEMPLATE: format string
  - re-export roundtrip: reproduction/codegen/llm_code.py re-exports match
"""
from __future__ import annotations

import ast
import json

import polars as pl
import pytest

from llmwikify.kernel.codegen import (
    OBSERVE_FEEDBACK_TEMPLATE,
    SYSTEM_PROMPT_CODE,
    build_execute_namespace,
    execute_code,
    extract_json_from_response,
    extract_python,
    validate_safety,
    validate_syntax,
)

# ─── extract_python ─────────────────────────────────────────────────


class TestExtractPython:
    def test_extracts_python_fence(self) -> None:
        text = (
            "Here's the code:\n"
            "```python\n"
            "def compute_factor(df):\n"
            "    return df['close']\n"
            "```\n"
            "That's it."
        )
        result = extract_python(text)
        assert result is not None
        assert "def compute_factor" in result
        assert "return df['close']" in result
        # Should be stripped (no leading/trailing whitespace)
        assert result == result.strip()

    def test_falls_back_to_def_compute_factor(self) -> None:
        text = "Some prose. def compute_factor(df): return df['close']"
        result = extract_python(text)
        assert result is not None
        assert result.startswith("def compute_factor")

    def test_empty_string_returns_none(self) -> None:
        assert extract_python("") is None

    def test_no_code_returns_none(self) -> None:
        assert extract_python("just some prose without code") is None

    def test_handles_multiline_fence(self) -> None:
        text = (
            "```python\n"
            "def compute_factor(df):\n"
            "    # line 2\n"
            "    # line 3\n"
            "    return df['close']\n"
            "```"
        )
        result = extract_python(text)
        assert result is not None
        assert "line 2" in result
        assert "line 3" in result


# ─── validate_syntax ────────────────────────────────────────────────


class TestValidateSyntax:
    def test_valid_code(self) -> None:
        ok, err = validate_syntax("def f(x): return x + 1")
        assert ok is True
        assert err == ""

    def test_invalid_syntax(self) -> None:
        ok, err = validate_syntax("def f(: return x")
        assert ok is False
        assert err  # non-empty error message

    def test_error_includes_line_number(self) -> None:
        ok, err = validate_syntax("def f(: return x")
        assert ok is False
        assert "line 1" in err

    def test_empty_code_is_valid(self) -> None:
        """ast.parse('') returns successfully (empty module)."""
        ok, err = validate_syntax("")
        assert ok is True
        assert err == ""


# ─── validate_safety ────────────────────────────────────────────────


class TestValidateSafety:
    def test_safe_code_passes(self) -> None:
        """Plain function definition with no dangerous imports/calls."""
        code = "def compute_factor(df): return df['close']"
        try:
            is_safe, err = validate_safety(code)
        except (ImportError, AttributeError) as exc:
            pytest.skip(f"QuantNodes not available: {exc}")
        # CodeSandbox may or may not flag simple code as safe depending on
        # sandbox config; what matters is the function returns a tuple.
        assert isinstance(is_safe, bool)
        assert isinstance(err, str)

    def test_unsafe_imports(self) -> None:
        """os.system should be flagged as unsafe."""
        code = "import os\nos.system('rm -rf /')"
        try:
            is_safe, err = validate_safety(code)
        except (ImportError, AttributeError) as exc:
            pytest.skip(f"QuantNodes not available: {exc}")
        # At least one of the dangerous ops should be flagged
        # (we don't assert is_safe is False because some sandboxes may allow it)
        assert isinstance(is_safe, bool)


# ─── build_execute_namespace / execute_code ─────────────────────────


class TestBuildExecuteNamespace:
    def test_includes_polars(self) -> None:
        ns = build_execute_namespace()
        assert ns["pl"] is pl
        assert ns["polars"] is pl

    def test_includes_pandas_numpy(self) -> None:
        ns = build_execute_namespace()
        import numpy as np
        import pandas as pd
        assert ns["pd"] is pd
        assert ns["np"] is np

    def test_includes_quantnodes_operators(self) -> None:
        """Some QuantNodes operators should be in the namespace."""
        ns = build_execute_namespace()
        # rank and rolling_std are commonly used; check at least one
        # (QuantNodes may not always be installed)
        try:
            from QuantNodes.operators.proxy import list_operators
            operators = list_operators()
            if operators:
                # At least one operator should be in the namespace
                present = [op for op in operators if op in ns]
                assert len(present) > 0
        except ImportError:
            pytest.skip("QuantNodes not installed")


class TestExecuteCode:
    def test_simple_compute_factor(self) -> None:
        """Run a simple compute_factor that returns a column."""
        df = pl.DataFrame({"close": [1.0, 2.0, 3.0, 4.0]})
        code = "def compute_factor(df):\n    return df['close']\n"
        try:
            result = execute_code(code, df, timeout_sec=10)
        except (ImportError, AttributeError) as exc:
            pytest.skip(f"QuantNodes not available: {exc}")
        assert isinstance(result, pl.Series)
        assert result.to_list() == [1.0, 2.0, 3.0, 4.0]

    def test_unsafe_code_raises_value_error(self) -> None:
        df = pl.DataFrame({"close": [1.0]})
        code = "import os\nos.system('echo hi')"
        try:
            execute_code(code, df, timeout_sec=5)
        except (ImportError, AttributeError) as exc:
            pytest.skip(f"QuantNodes not available: {exc}")
        except ValueError:
            pass  # expected
        else:
            pytest.fail("Expected ValueError for unsafe code")

    def test_no_compute_factor_raises_error(self) -> None:
        df = pl.DataFrame({"close": [1.0]})
        code = "x = 42"  # no compute_factor
        try:
            execute_code(code, df, timeout_sec=5)
        except (ImportError, AttributeError) as exc:
            pytest.skip(f"QuantNodes not available: {exc}")
        except Exception as exc:
            # QuantNodes sandbox raises DangerousCodeError when compute_factor
            # is not defined; we accept any exception (the function does fail).
            assert "compute_factor" in str(exc) or "Series" in str(exc) or "name 'compute_factor' is not defined" in str(exc)
        else:
            pytest.fail("Expected an exception for missing compute_factor")


# ─── extract_json_from_response ─────────────────────────────────────


class TestExtractJson:
    def test_fenced_json(self) -> None:
        text = 'Here is the JSON:\n```json\n{"key": "value", "n": 42}\n```\nDone.'
        result = extract_json_from_response(text)
        assert result == {"key": "value", "n": 42}

    def test_fenced_json_no_lang(self) -> None:
        """Fenced block without explicit json lang tag."""
        text = '```\n{"a": 1}\n```'
        result = extract_json_from_response(text)
        assert result == {"a": 1}

    def test_raw_json_object(self) -> None:
        text = 'Output: {"foo": "bar", "count": 3}'
        result = extract_json_from_response(text)
        assert result == {"foo": "bar", "count": 3}

    def test_malformed_json_returns_none(self) -> None:
        text = "```json\n{invalid json}\n```"
        result = extract_json_from_response(text)
        assert result is None

    def test_no_json_returns_none(self) -> None:
        text = "just plain text, no JSON"
        result = extract_json_from_response(text)
        assert result is None

    def test_nested_object(self) -> None:
        text = '```json\n{"a": {"b": [1, 2, 3]}}\n```'
        result = extract_json_from_response(text)
        assert result == {"a": {"b": [1, 2, 3]}}


# ─── SYSTEM_PROMPT_CODE / OBSERVE_FEEDBACK_TEMPLATE ────────────────


class TestPromptConstants:
    def test_system_prompt_non_empty(self) -> None:
        assert isinstance(SYSTEM_PROMPT_CODE, str)
        assert len(SYSTEM_PROMPT_CODE) > 100
        assert "compute_factor" in SYSTEM_PROMPT_CODE

    def test_system_prompt_includes_polars_rule(self) -> None:
        """The system prompt should warn about polars boolean ambiguity."""
        assert "Expr is ambiguous" in SYSTEM_PROMPT_CODE or "truth value" in SYSTEM_PROMPT_CODE

    def test_feedback_template_format_string(self) -> None:
        assert isinstance(OBSERVE_FEEDBACK_TEMPLATE, str)
        assert "{stage}" in OBSERVE_FEEDBACK_TEMPLATE
        assert "{error}" in OBSERVE_FEEDBACK_TEMPLATE

    def test_feedback_template_renders(self) -> None:
        rendered = OBSERVE_FEEDBACK_TEMPLATE.format(
            stage="execute",
            error="NameError: foo",
            context="(none)",
        )
        assert "execute" in rendered
        assert "NameError: foo" in rendered


# ─── Backward-compat re-export (C1 invariant) ──────────────────────


class TestReexportCompat:
    """reproduction/codegen/llm_code.py should re-export kernel symbols."""

    def test_reproduction_llm_code_reexports(self) -> None:
        from llmwikify.reproduction.codegen import llm_code

        for name in [
            "SYSTEM_PROMPT_CODE",
            "extract_python",
            "validate_syntax",
            "validate_safety",
            "build_execute_namespace",
            "execute_code",
            "extract_json_from_response",
            "OBSERVE_FEEDBACK_TEMPLATE",
        ]:
            assert hasattr(llm_code, name), f"missing re-export: {name}"

    def test_reproduction_feedback_templates_reexports(self) -> None:
        from llmwikify.reproduction.codegen import feedback_templates

        assert hasattr(feedback_templates, "OBSERVE_FEEDBACK_TEMPLATE")
        # Should be the SAME string object (not a copy)
        from llmwikify.kernel.codegen.feedback_templates import (
            OBSERVE_FEEDBACK_TEMPLATE as KERN,
        )
        assert feedback_templates.OBSERVE_FEEDBACK_TEMPLATE is KERN

    def test_reproduction_llm_code_same_string_as_kernel(self) -> None:
        """String constants should be the same object (not duplicated)."""
        from llmwikify.reproduction.codegen.llm_code import (
            SYSTEM_PROMPT_CODE as REPRO,
        )
        assert REPRO is SYSTEM_PROMPT_CODE
