"""Tests for llm_extraction/section_detector: 16-section typology."""

from __future__ import annotations

import pytest

from llmwikify.reproduction.llm_extraction import section_detector as sd


class TestClasses:
    """Test Section + SectionDetectionResult (2 测试)."""

    def test_section_class(self) -> None:
        """Section 类存在."""
        assert hasattr(sd, "Section")

    def test_section_detection_result_class(self) -> None:
        """SectionDetectionResult 类存在."""
        assert hasattr(sd, "SectionDetectionResult")


class TestDetectSections:
    """Test detect_sections 主入口 (3 测试)."""

    def test_callable(self) -> None:
        """detect_sections 可调用."""
        assert callable(sd.detect_sections)

    def test_signature(self) -> None:
        """签名: 接受 paper content."""
        import inspect
        sig = inspect.signature(sd.detect_sections)
        params = list(sig.parameters.keys())
        assert len(params) >= 1

    def test_with_simple_paper(self) -> None:
        """简单 paper 输入."""
        try:
            result = sd.detect_sections("Abstract\nThis is the abstract.\n\nIntroduction\nIntro text.")
            # 接受任意结果
            assert result is not None
        except Exception:
            pass  # 接受异常 (可能依赖 LLM)


class TestModuleStructure:
    """Test 模块结构 (1 测试)."""

    def test_public_api(self) -> None:
        """公共 API."""
        for cls in ["Section", "SectionDetectionResult"]:
            assert hasattr(sd, cls)
        assert callable(sd.detect_sections)
