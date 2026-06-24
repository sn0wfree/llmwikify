"""Integration: pipeline 框架 smoke test (S3 阶段).

模拟 pipeline 编排: factor → backtest → persist 流程, 全 mock 不连真实.

详见: docs/designs/pipeline_framework.md Section 29.9
"""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from llmwikify.reproduction.persist import factor_library, sessions


class TestFactorToBacktestToPersist:
    """Test 完整 flow: 写因子 → 读 → 持久化 (mock 全部)."""

    def test_full_flow_mocked(self, tmp_path: Path) -> None:
        """完整流程 mock."""
        # 1. 写因子 (新格式)
        factor_dir = tmp_path / "quant" / "factors" / "test_flow_factor"
        factor_dir.mkdir(parents=True)
        result = factor_library.write_factor_yaml(
            "test_flow_factor",
            {"factor": {"name": "test_flow", "category": "alpha"}},
            project_root=tmp_path,
        )
        assert "Created" in result

        # 2. 读因子
        data = factor_library.read_factor_yaml("test_flow_factor", project_root=tmp_path)
        assert data["factor"]["name"] == "test_flow"

        # 3. 写 session 到 DB
        db = sessions.ReproductionDatabase(db_path=tmp_path / "session.db")
        sid = db.create_session(
            wiki_id="w1", paper_id="p1", source_type="pdf",
            source_ref="ref", symbol="test_flow:all",
            start_date="20200101", end_date="20241231",
        )
        assert sid

        # 4. 记录事件
        db.record_event(sid, "factor.written", name="test_flow")
        events = db.get_events(sid)
        assert any(e["event_type"] == "factor.written" for e in events)

        # 5. 更新 index
        factor_library.update_index(project_root=tmp_path)
        factors = factor_library.list_factors(project_root=tmp_path)
        # 修复后: 1 个因子, 不是 2
        assert len(factors) == 1


class TestPipelineDataFlow:
    """Test 数据流契约 (2 测试)."""

    def test_factor_dir_layout(self, tmp_path: Path) -> None:
        """因子目录布局正确."""
        factor_dir = tmp_path / "quant" / "factors" / "stk_alpha_001_abc"
        factor_dir.mkdir(parents=True)
        (factor_dir / "factor.yaml").write_text(
            'factor:\n  name: test\n', encoding="utf-8"
        )

        # 读 + 验证布局
        data = factor_library.read_factor_yaml("stk_alpha_001_abc", project_root=tmp_path)
        assert data["factor"]["name"] == "test"

    def test_session_db_path(self, tmp_path: Path) -> None:
        """session DB path 可配置."""
        db_path = tmp_path / "subdir" / "test.db"
        db = sessions.ReproductionDatabase(db_path=db_path)
        assert db is not None
        # DB 文件已创建
        assert db_path.parent.exists()
