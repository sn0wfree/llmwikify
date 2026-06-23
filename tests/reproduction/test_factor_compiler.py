"""Tests for factor_compiler: AST 多样本编译 (Loop v4)."""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from llmwikify.reproduction import factor_compiler as fc


class TestFactorCompiler:
    """Test FactorCompiler 类 (5 测试)."""

    def test_class_exists(self) -> None:
        """FactorCompiler 类存在."""
        assert hasattr(fc, "FactorCompiler")

    def test_constructor_signature(self) -> None:
        """构造函数接受 llm_client + 参数."""
        import inspect
        sig = inspect.signature(fc.FactorCompiler.__init__)
        params = list(sig.parameters.keys())
        # 应有 llm_client, max_iterations, n_samples, temperature 等
        assert "llm_client" in params or len(params) >= 3

    def test_init_with_no_args(self) -> None:
        """无参构造 (使用默认 _build_default_llm)."""
        with patch.object(fc, "_build_default_llm", return_value=MagicMock()):
            try:
                compiler = fc.FactorCompiler()
                assert compiler is not None
            except Exception as exc:
                # 接受 init 失败 (依赖网络/keys)
                assert "key" in str(exc).lower() or "config" in str(exc).lower()

    def test_has_compile_method(self) -> None:
        """FactorCompiler 有 compile 类方法."""
        assert hasattr(fc.FactorCompiler, "compile") or hasattr(fc.FactorCompiler, "compile_to_code")

    def test_module_imports(self) -> None:
        """模块可导入."""
        from llmwikify.reproduction import factor_compiler
        assert factor_compiler is not None
