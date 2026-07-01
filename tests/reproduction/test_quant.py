"""Tests for quant_wiki, factor_library, and quant-init command."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def quant_root(tmp_path):
    """Create a quant/ directory structure for testing."""
    root = tmp_path / "quant"
    root.mkdir()
    (root / "papers").mkdir()
    (root / "factors").mkdir()
    (root / "factorbacktest").mkdir()
    (root / "strategies").mkdir()
    (root / "datacache").mkdir()
    return root


@pytest.fixture
def project_root(tmp_path):
    """Create a project root with quant/ for integration tests."""
    root = tmp_path / "project"
    root.mkdir()
    (root / "quant").mkdir()
    (root / "quant" / "papers").mkdir()
    (root / "quant" / "factors").mkdir()
    (root / "quant" / "factorbacktest").mkdir()
    (root / "quant" / "strategies").mkdir()
    (root / "quant" / "datacache").mkdir()
    return root


# ── QuantWiki Tests ───────────────────────────────────────────


class TestQuantWiki:
    """Tests for QuantWiki read/write/list operations."""

    def test_write_and_read_page(self, quant_root):
        from llmwikify.reproduction.paper_understanding.quant_wiki import QuantWiki

        qw = QuantWiki(quant_root)
        result = qw.write_page("test-paper", "# Test Content\n\nHello", "papers")
        assert "Created" in result

        page = qw.read_page("test-paper", "papers")
        assert page is not None
        assert page["content"] == "# Test Content\n\nHello"

    def test_read_nonexistent(self, quant_root):
        from llmwikify.reproduction.paper_understanding.quant_wiki import QuantWiki

        qw = QuantWiki(quant_root)
        result = qw.read_page("nonexistent", "papers")
        assert result is None

    def test_list_pages(self, quant_root):
        from llmwikify.reproduction.paper_understanding.quant_wiki import QuantWiki

        qw = QuantWiki(quant_root)
        qw.write_page("paper-a", "# A", "papers")
        qw.write_page("paper-b", "# B", "papers")
        pages = qw.list_pages("papers")
        assert len(pages) == 2
        names = [p.get("_slug") or p.get("page_name") for p in pages]
        assert "paper-a" in names
        assert "paper-b" in names

    def test_write_factor_yaml(self, quant_root):
        from llmwikify.reproduction.paper_understanding.quant_wiki import QuantWiki

        qw = QuantWiki(quant_root)
        data = {"factor": {"name": "test", "l1": {"definition": "test factor"}}}
        result = qw.write_factor_yaml("stock/price/test", data)
        assert "Created" in result

        loaded = qw.read_factor_yaml("stock/price/test")
        assert loaded is not None
        assert loaded["factor"]["name"] == "test"

    def test_list_factor_yamls(self, quant_root):
        from llmwikify.reproduction.paper_understanding.quant_wiki import QuantWiki

        qw = QuantWiki(quant_root)
        data1 = {"factor": {"name": "factor_a", "category": "price"}}
        data2 = {"factor": {"name": "factor_b", "category": "fundamental"}}
        qw.write_factor_yaml("stock/price/factor_a", data1)
        qw.write_factor_yaml("stock/fundamental/factor_b", data2)

        factors = qw.list_factor_yamls()
        assert len(factors) == 2
        names = {f["name"] for f in factors}
        assert names == {"factor_a", "factor_b"}

    def test_read_page_with_frontmatter(self, quant_root):
        from llmwikify.reproduction.paper_understanding.quant_wiki import QuantWiki

        qw = QuantWiki(quant_root)
        content = "---\ntitle: Test Page\nauthor: test\n---\n\n# Content"
        qw.write_page("test-fm", content, "papers")
        page = qw.read_page("test-fm", "papers")
        assert page is not None
        assert page["title"] == "Test Page"
        assert page["author"] == "test"
        assert "# Content" in page["content"]

    def test_invalid_page_type(self, quant_root):
        from llmwikify.reproduction.paper_understanding.quant_wiki import QuantWiki

        qw = QuantWiki(quant_root)
        with pytest.raises(ValueError, match="Unknown page_type"):
            qw.write_page("test", "content", "invalid_type")


# ── Factor Library Tests ──────────────────────────────────────


class TestFactorLibrary:
    """Tests for factor_library read/write/list operations."""

    def test_write_and_read_factor(self, project_root):
        from llmwikify.reproduction.persist.factor_library import (
            read_factor_yaml,
            write_factor_yaml,
        )

        data = {
            "factor": {
                "name": "test_factor",
                "l1": {"definition": "test"},
                "l2": {"complexity": "O(N)"},
            }
        }
        write_factor_yaml("stock/price/test_factor", data, project_root)
        result = read_factor_yaml("stock/price/test_factor", project_root)
        assert result is not None
        assert result["factor"]["name"] == "test_factor"
        assert result["factor"]["l1"]["definition"] == "test"

    def test_read_nonexistent(self, project_root):
        from llmwikify.reproduction.persist.factor_library import read_factor_yaml

        result = read_factor_yaml("nonexistent", project_root)
        assert result is None

    def test_list_factors_by_category(self, project_root):
        from llmwikify.reproduction.persist.factor_library import (
            list_factors_by_category,
            write_factor_yaml,
        )

        write_factor_yaml("stock/price/mom", {"factor": {"name": "mom", "category": "price"}}, project_root)
        write_factor_yaml("stock/price/vol", {"factor": {"name": "vol", "category": "price"}}, project_root)
        write_factor_yaml("stock/fundamental/val", {"factor": {"name": "val", "category": "fundamental"}}, project_root)

        cats = list_factors_by_category(project_root)
        assert "price" in cats
        assert "fundamental" in cats
        assert len(cats["price"]) == 2
        assert len(cats["fundamental"]) == 1

    def test_update_index(self, project_root):
        from llmwikify.reproduction.persist.factor_library import (
            list_factors,
            update_index,
            write_factor_yaml,
        )

        write_factor_yaml("stock/price/mom", {"factor": {"name": "mom", "category": "price", "status": "已注册"}}, project_root)
        write_factor_yaml("stock/price/vol", {"factor": {"name": "vol", "category": "price", "status": "已通过"}}, project_root)

        update_index(project_root)
        factors = list_factors(project_root)
        assert len(factors) == 2
        names = {f["name"] for f in factors}
        assert names == {"mom", "vol"}

    def test_update_index_empty(self, project_root):
        from llmwikify.reproduction.persist.factor_library import (
            list_factors,
            update_index,
        )

        update_index(project_root)
        factors = list_factors(project_root)
        assert len(factors) == 0

    def test_list_factors_empty(self, project_root):
        from llmwikify.reproduction.persist.factor_library import list_factors

        factors = list_factors(project_root)
        assert factors == []


# ── Quant Init Command Tests ──────────────────────────────────


class TestQuantInitCommand:
    """Tests for quant-init CLI command."""

    def test_creates_directory_structure(self, tmp_path):
        from llmwikify.interfaces.cli.commands.quant_init_cmd import run_quant_init

        class FakeWiki:
            root = tmp_path

        result = run_quant_init(FakeWiki(), tmp_path, type("args", (), {"overwrite": False})())
        assert result == 0
        assert (tmp_path / "quant").is_dir()
        assert (tmp_path / "quant" / "papers").is_dir()
        assert (tmp_path / "quant" / "factors").is_dir()
        assert (tmp_path / "quant" / "factorbacktest").is_dir()
        assert (tmp_path / "quant" / "strategies").is_dir()
        assert (tmp_path / "quant" / "datacache").is_dir()

    def test_creates_index_yaml(self, tmp_path):
        from llmwikify.interfaces.cli.commands.quant_init_cmd import run_quant_init

        class FakeWiki:
            root = tmp_path

        run_quant_init(FakeWiki(), tmp_path, type("args", (), {"overwrite": False})())
        index_path = tmp_path / "quant" / "factors" / "index.yaml"
        assert index_path.exists()
        data = yaml.safe_load(index_path.read_text())
        assert "factors" in data
        assert "statistics" in data

    def test_creates_index_md(self, tmp_path):
        from llmwikify.interfaces.cli.commands.quant_init_cmd import run_quant_init

        class FakeWiki:
            root = tmp_path

        run_quant_init(FakeWiki(), tmp_path, type("args", (), {"overwrite": False})())
        index_md = tmp_path / "quant" / "index.md"
        assert index_md.exists()
        assert "Quant Research" in index_md.read_text()

    def test_creates_duckdb(self, tmp_path):
        from llmwikify.interfaces.cli.commands.quant_init_cmd import run_quant_init

        class FakeWiki:
            root = tmp_path

        run_quant_init(FakeWiki(), tmp_path, type("args", (), {"overwrite": False})())
        duckdb_path = tmp_path / "quant" / "factor.duckdb"
        assert duckdb_path.exists()

        import duckdb
        con = duckdb.connect(str(duckdb_path), read_only=True)
        tables = con.execute("SHOW TABLES").fetchall()
        assert any("factor_values" in t[0] for t in tables)
        con.close()

    def test_idempotent(self, tmp_path):
        from llmwikify.interfaces.cli.commands.quant_init_cmd import run_quant_init

        class FakeWiki:
            root = tmp_path

        args = type("args", (), {"overwrite": False})()
        result1 = run_quant_init(FakeWiki(), tmp_path, args)
        result2 = run_quant_init(FakeWiki(), tmp_path, args)
        assert result1 == 0
        assert result2 == 0  # Should succeed (skip existing)


# ── Factor API Tests (Modified) ───────────────────────────────


class TestFactorAPIRedirected:
    """Tests for factor API reading from quant/factors/."""

    def test_list_empty(self, factor_client, monkeypatch, tmp_path):
        from llmwikify.reproduction.persist import factor_library
        monkeypatch.setattr(factor_library, "_get_factors_dir", lambda *a, **k: tmp_path / "nonexistent")

        client, _ = factor_client
        r = client.get("/api/factor/list")
        assert r.status_code == 200

    def test_list_with_factors(self, factor_client, monkeypatch, tmp_path):
        from llmwikify.reproduction.persist import factor_library

        factors_dir = tmp_path / "quant_factors"
        factors_dir.mkdir()
        monkeypatch.setattr(factor_library, "_get_factors_dir", lambda *a, **k: factors_dir)

        # Write a factor YAML
        factor_data = {
            "factor": {
                "name": "factor_x",
                "category": "price",
                "l1": {"definition": "test"},
            }
        }
        factor_dir = factors_dir / "stock" / "price"
        factor_dir.mkdir(parents=True)
        (factor_dir / "factor_x.yaml").write_text(
            yaml.dump(factor_data, allow_unicode=True),
            encoding="utf-8",
        )

        client, _ = factor_client
        r = client.get("/api/factor/list")
        assert r.status_code == 200
        categories = r.json()["categories"]
        assert "price" in categories

    def test_get_factor(self, factor_client, monkeypatch, tmp_path):
        from llmwikify.reproduction.persist import factor_library

        factors_dir = tmp_path / "quant_factors"
        factors_dir.mkdir()
        monkeypatch.setattr(factor_library, "_get_factors_dir", lambda *a, **k: factors_dir)

        factor_data = {
            "factor": {
                "name": "test_factor",
                "l1": {"definition": "test factor"},
            }
        }
        factor_dir = factors_dir / "stock" / "price"
        factor_dir.mkdir(parents=True)
        (factor_dir / "test_factor.yaml").write_text(
            yaml.dump(factor_data, allow_unicode=True),
            encoding="utf-8",
        )

        client, _ = factor_client
        r = client.get("/api/factor/library/stock/price/test_factor")
        assert r.status_code == 200
        assert r.json()["factor"]["factor"]["name"] == "test_factor"

    def test_get_not_found(self, factor_client, monkeypatch, tmp_path):
        from llmwikify.reproduction.persist import factor_library
        monkeypatch.setattr(factor_library, "_get_factors_dir", lambda *a, **k: tmp_path / "nonexistent")

        client, _ = factor_client
        r = client.get("/api/factor/nonexistent")
        assert r.status_code == 404


# ── Strategy API Tests (Modified) ─────────────────────────────


class TestStrategyAPIRedirected:
    """Tests for strategy API reading from quant/strategies/."""

    def test_list_empty(self, strategy_client, monkeypatch, tmp_path):
        from llmwikify.reproduction.paper_understanding import quant_wiki
        monkeypatch.setattr(quant_wiki, "_quant_wiki", None)
        monkeypatch.setattr(
            quant_wiki, "get_quant_wiki",
            lambda *a, **k: quant_wiki.QuantWiki(tmp_path / "quant_empty"),
        )
        (tmp_path / "quant_empty").mkdir(exist_ok=True)
        (tmp_path / "quant_empty" / "strategies").mkdir(exist_ok=True)

        client, _ = strategy_client
        r = client.get("/api/strategy/list")
        assert r.status_code == 200
        assert r.json()["strategies"] == []

    def test_list_with_strategies(self, strategy_client, monkeypatch, tmp_path):
        from llmwikify.reproduction.paper_understanding import quant_wiki

        quant_dir = tmp_path / "quant_test"
        quant_dir.mkdir()
        (quant_dir / "strategies").mkdir()
        (quant_dir / "strategies" / "test-strategy.md").write_text(
            "---\ntitle: Test Strategy\nsignal_type: momentum\n---\n\n# Strategy",
            encoding="utf-8",
        )

        monkeypatch.setattr(quant_wiki, "_quant_wiki", None)
        monkeypatch.setattr(
            quant_wiki, "get_quant_wiki",
            lambda *a, **k: quant_wiki.QuantWiki(quant_dir),
        )

        client, _ = strategy_client
        r = client.get("/api/strategy/list")
        assert r.status_code == 200
        strategies = r.json()["strategies"]
        assert len(strategies) == 1
        assert strategies[0]["title"] == "Test Strategy"


# ── Factor Library API Endpoint Tests ────────────────────────


class TestFactorLibraryAPI:
    """Tests for GET/PUT /api/factor/library/* endpoints."""

    def test_library_list_empty(self, factor_client, monkeypatch, tmp_path):
        from llmwikify.reproduction.persist import factor_library
        monkeypatch.setattr(factor_library, "_get_factors_dir", lambda *a, **k: tmp_path / "empty")

        client, _ = factor_client
        r = client.get("/api/factor/library/list")
        assert r.status_code == 200
        assert r.json()["categories"] == {}

    def test_library_list_with_factors(self, factor_client, monkeypatch, tmp_path):
        from llmwikify.reproduction.persist import factor_library

        factors_dir = tmp_path / "factors"
        factors_dir.mkdir()
        monkeypatch.setattr(factor_library, "_get_factors_dir", lambda *a, **k: factors_dir)

        # Create factor YAMLs
        for name, cat in [("mom", "price"), ("vol", "price"), ("val", "fundamental")]:
            d = factors_dir / "stock" / cat
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{name}.yaml").write_text(
                yaml.dump({"factor": {"name": name, "category": cat, "l1": {"definition": f"test {name}"}}}, allow_unicode=True),
                encoding="utf-8",
            )

        client, _ = factor_client
        r = client.get("/api/factor/library/list")
        assert r.status_code == 200
        cats = r.json()["categories"]
        assert len(cats["price"]) == 2
        assert len(cats["fundamental"]) == 1

    def test_library_get_factor(self, factor_client, monkeypatch, tmp_path):
        from llmwikify.reproduction.persist import factor_library

        factors_dir = tmp_path / "factors"
        factors_dir.mkdir()
        monkeypatch.setattr(factor_library, "_get_factors_dir", lambda *a, **k: factors_dir)

        d = factors_dir / "stock" / "price"
        d.mkdir(parents=True)
        factor_data = {"factor": {"name": "test", "l1": {"definition": "test factor"}}}
        (d / "test.yaml").write_text(yaml.dump(factor_data, allow_unicode=True), encoding="utf-8")

        client, _ = factor_client
        r = client.get("/api/factor/library/stock/price/test")
        assert r.status_code == 200
        assert r.json()["factor"]["factor"]["name"] == "test"

    def test_library_get_not_found(self, factor_client, monkeypatch, tmp_path):
        from llmwikify.reproduction.persist import factor_library
        monkeypatch.setattr(factor_library, "_get_factors_dir", lambda *a, **k: tmp_path / "empty")

        client, _ = factor_client
        r = client.get("/api/factor/library/nonexistent")
        assert r.status_code == 404

    def test_library_update_factor(self, factor_client, monkeypatch, tmp_path):
        from llmwikify.reproduction.persist import factor_library

        factors_dir = tmp_path / "factors"
        factors_dir.mkdir()
        monkeypatch.setattr(factor_library, "_get_factors_dir", lambda *a, **k: factors_dir)

        client, _ = factor_client
        update_data = {"factor": {"name": "new_factor", "l1": {"definition": "new"}}}
        r = client.put(
            "/api/factor/library/stock/price/new_factor",
            json=update_data,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

        # Verify file was created
        yaml_path = factors_dir / "stock" / "price" / "new_factor.yaml"
        assert yaml_path.exists()
        loaded = yaml.safe_load(yaml_path.read_text())
        assert loaded["factor"]["name"] == "new_factor"


# ── QuantWiki / FactorLibrary Edge Case Tests ────────────────


class TestQuantWikiEdgeCases:
    """Edge case tests for QuantWiki."""

    def test_ensure_dirs(self, tmp_path):
        from llmwikify.reproduction.paper_understanding.quant_wiki import QuantWiki

        root = tmp_path / "quant_new"
        root.mkdir()
        qw = QuantWiki(root)
        qw.ensure_dirs()
        assert (root / "papers").is_dir()
        assert (root / "factors").is_dir()
        assert (root / "factorbacktest").is_dir()
        assert (root / "strategies").is_dir()
        assert (root / "datacache").is_dir()

    def test_list_empty_dir(self, quant_root):
        from llmwikify.reproduction.paper_understanding.quant_wiki import QuantWiki

        qw = QuantWiki(quant_root)
        pages = qw.list_pages("papers")
        assert pages == []

    def test_list_factor_yamls_empty(self, quant_root):
        from llmwikify.reproduction.paper_understanding.quant_wiki import QuantWiki

        qw = QuantWiki(quant_root)
        factors = qw.list_factor_yamls()
        assert factors == []

    def test_malformed_frontmatter(self, quant_root):
        from llmwikify.reproduction.paper_understanding.quant_wiki import QuantWiki

        qw = QuantWiki(quant_root)
        # Write content with broken frontmatter
        (quant_root / "papers" / "bad.md").write_text(
            "---\ntitle: Bad\nbroken yaml {{{\n---\nContent",
            encoding="utf-8",
        )
        page = qw.read_page("bad", "papers")
        # Should not crash, returns content
        assert page is not None

    def test_write_page_empty_content(self, quant_root):
        from llmwikify.reproduction.paper_understanding.quant_wiki import QuantWiki

        qw = QuantWiki(quant_root)
        result = qw.write_page("empty", "", "papers")
        assert "Created" in result
        page = qw.read_page("empty", "papers")
        assert page["content"] == ""

    def test_write_and_read_factorbacktest(self, quant_root):
        from llmwikify.reproduction.paper_understanding.quant_wiki import QuantWiki

        qw = QuantWiki(quant_root)
        result = qw.write_page("bt-001", "# Backtest Result", "factorbacktest")
        assert "Created" in result
        page = qw.read_page("bt-001", "factorbacktest")
        assert page is not None
        assert "# Backtest Result" in page["content"]

    def test_write_and_read_strategies(self, quant_root):
        from llmwikify.reproduction.paper_understanding.quant_wiki import QuantWiki

        qw = QuantWiki(quant_root)
        result = qw.write_page("strat-001", "# Strategy", "strategies")
        assert "Created" in result
        page = qw.read_page("strat-001", "strategies")
        assert page is not None


class TestFactorLibraryEdgeCases:
    """Edge case tests for factor_library."""

    def test_corrupt_yaml(self, project_root):
        from llmwikify.reproduction.persist.factor_library import read_factor_yaml

        # Write corrupt YAML
        factors_dir = project_root / "quant" / "factors"
        d = factors_dir / "stock" / "price"
        d.mkdir(parents=True)
        (d / "corrupt.yaml").write_text("{{invalid yaml: [", encoding="utf-8")

        result = read_factor_yaml("stock/price/corrupt", project_root)
        assert result is None

    def test_missing_index(self, project_root):
        from llmwikify.reproduction.persist.factor_library import list_factors

        factors_dir = project_root / "quant" / "factors"
        # index.yaml doesn't exist
        result = list_factors(project_root)
        assert result == []

    def test_update_index_stats(self, project_root):
        from llmwikify.reproduction.persist.factor_library import (
            list_factors,
            update_index,
            write_factor_yaml,
        )

        write_factor_yaml("stock/price/a", {"factor": {"name": "a", "category": "price", "status": "已注册"}}, project_root)
        write_factor_yaml("stock/price/b", {"factor": {"name": "b", "category": "price", "status": "已通过"}}, project_root)
        write_factor_yaml("stock/fundamental/c", {"factor": {"name": "c", "category": "fundamental", "status": "已注册"}}, project_root)

        update_index(project_root)
        factors = list_factors(project_root)
        assert len(factors) == 3

        # Check stats
        index_path = project_root / "quant" / "factors" / "index.yaml"
        index_data = yaml.safe_load(index_path.read_text())
        stats = index_data["statistics"]
        assert stats["total"] == 3
        assert stats["by_category"]["price"] == 2
        assert stats["by_category"]["fundamental"] == 1


# ── Strategy / Paper Edge Case Tests ─────────────────────────


class TestStrategyEdgeCases:
    """Edge case tests for strategy API."""

    def test_get_strategy_not_found(self, strategy_client, monkeypatch, tmp_path):
        from llmwikify.reproduction.paper_understanding import quant_wiki

        quant_dir = tmp_path / "quant_test"
        quant_dir.mkdir()
        (quant_dir / "strategies").mkdir()

        monkeypatch.setattr(quant_wiki, "_quant_wiki", None)
        monkeypatch.setattr(
            quant_wiki, "get_quant_wiki",
            lambda *a, **k: quant_wiki.QuantWiki(quant_dir),
        )

        client, _ = strategy_client
        r = client.get("/api/strategy/nonexistent")
        assert r.status_code == 404


class TestPaperEdgeCases:
    """Edge case tests for paper API."""

    def test_list_raw_empty(self, paper_client, monkeypatch):
        client, _, _ = paper_client
        r = client.get("/api/paper/list-raw")
        assert r.status_code == 200
        assert r.json()["files"] == []

    def test_upload_to_raw(self, paper_client):
        client, wiki, _ = paper_client
        # Create a fake PDF in the upload dir (which is now raw/)
        import io
        pdf_content = b"%PDF-1.4 fake content"
        r = client.post(
            "/api/paper/upload",
            data={"paper_id": "test-paper"},
            files={"file": ("test.pdf", io.BytesIO(pdf_content), "application/pdf")},
        )
        assert r.status_code == 200
        assert r.json()["paper_id"] == "test-paper"
        # Verify file is in the upload dir
        assert r.json()["filename"] == "test-paper.pdf"


# ═══════════════════════════════════════════════════════════════
# L5 Validation Engine Tests
# ═══════════════════════════════════════════════════════════════

class TestL5Validation:
    """Tests for L5 automated validation engine."""

    def _make_result(self, **overrides):
        """Create a mock FactorBacktestResult."""
        from dataclasses import dataclass, field

        @dataclass
        class MockResult:
            ic_mean: float = 0.04
            ic_std: float = 0.05
            icir: float = 0.8
            t_stat: float = 2.5
            win_rate: float = 0.55
            annual_return: float = 0.15
            max_drawdown: float = 0.12
            turnover: float = 0.3
            quantile_returns: dict = field(default_factory=lambda: {"G1": 0.20, "G2": 0.15, "G3": 0.10, "G4": 0.05, "G5": -0.05})
            ic_series: list = field(default_factory=lambda: [
                {"date": "2024-01-01", "ic": 0.05, "rank_ic": 0.04},
                {"date": "2024-02-01", "ic": 0.03, "rank_ic": 0.02},
                {"date": "2024-03-01", "ic": -0.01, "rank_ic": -0.02},
                {"date": "2024-04-01", "ic": 0.06, "rank_ic": 0.05},
            ])
            quantile_curves: dict = field(default_factory=dict)
            rank_ic_mean: float = 0.04
            rank_ic_std: float = 0.05
            rank_icir: float = 0.8
            rank_ic_pos_ratio: float = 0.75
            longshort_ann_return: float = 0.25
            longshort_sharpe: float = 1.2
            longshort_mdd: float = 0.08
            longshort_curve: list = field(default_factory=lambda: [
                {"date": "2024-01-01", "value": 1.0},
                {"date": "2024-02-01", "value": 1.02},
                {"date": "2024-03-01", "value": 1.01},
                {"date": "2024-04-01", "value": 1.05},
            ])
            universe: str = "HS300"
            adj_mode: str = "D"
            n_stocks_per_date: list = field(default_factory=list)
            group_metrics: dict = field(default_factory=lambda: {
                "G1": {"sharpe": 1.5, "max_drawdown": 0.05, "turnover": 0.3},
                "G2": {"sharpe": 1.0, "max_drawdown": 0.08, "turnover": 0.25},
            })
            total_rebalances: int = 100
            valid_rebalances: int = 95

        r = MockResult()
        for k, v in overrides.items():
            setattr(r, k, v)
        return r

    def test_analyze_ic(self):
        from llmwikify.reproduction.backtest_pkg.l5_validation import analyze_ic
        result = self._make_result()
        ic = analyze_ic(result)
        assert "ic_mean" in ic
        assert "icir" in ic
        assert "rank_ic_mean" in ic
        assert "win_rate" in ic
        assert ic["win_rate"] == 0.75  # 3 of 4 > 0

    def test_analyze_ic_empty(self):
        from llmwikify.reproduction.backtest_pkg.l5_validation import analyze_ic
        result = self._make_result(ic_series=[])
        assert analyze_ic(result) == {}

    def test_analyze_groups(self):
        from llmwikify.reproduction.backtest_pkg.l5_validation import analyze_groups
        result = self._make_result()
        ga = analyze_groups(result)
        assert ga["ls_ann_return"] == 0.25
        assert ga["ls_sharpe"] == 1.2
        assert "G1>G2" in ga["group_monotonicity"]

    def test_analyze_returns(self):
        from llmwikify.reproduction.backtest_pkg.l5_validation import analyze_returns
        result = self._make_result()
        ra = analyze_returns(result)
        assert ra["ann_return"] == 0.25
        assert ra["sharpe"] > 0

    def test_analyze_turnover(self):
        from llmwikify.reproduction.backtest_pkg.l5_validation import analyze_turnover
        result = self._make_result()
        ta = analyze_turnover(result)
        assert ta["avg_turnover"] > 0

    def test_analyze_turnover_fallback(self):
        from llmwikify.reproduction.backtest_pkg.l5_validation import analyze_turnover
        result = self._make_result(group_metrics={})
        ta = analyze_turnover(result)
        assert ta["avg_turnover"] == 0.3

    def test_analyze_stability(self):
        from llmwikify.reproduction.backtest_pkg.l5_validation import analyze_stability
        result = self._make_result()
        sa = analyze_stability(result)
        assert "yearly" in sa
        assert len(sa["yearly"]) > 0

    def test_analyze_oos(self):
        from llmwikify.reproduction.backtest_pkg.l5_validation import analyze_oos
        result = self._make_result()
        oa = analyze_oos(result)
        assert "oos_rank_ic" in oa
        assert "oos_ls_return" in oa

    def test_analyze_cost(self):
        from llmwikify.reproduction.backtest_pkg.l5_validation import analyze_cost
        result = self._make_result()
        ca = analyze_cost(result, cost_bps=15)
        assert ca["cost_bps"] == 15
        assert "net_ann_return" in ca
        assert "cost_sensitivity" in ca

    def test_compute_score_pass(self):
        from llmwikify.reproduction.backtest_pkg.l5_validation import compute_score
        result = self._make_result()
        from llmwikify.reproduction.backtest_pkg.l5_validation import (
            analyze_cost,
            analyze_groups,
            analyze_ic,
            analyze_oos,
            analyze_returns,
            analyze_stability,
            analyze_turnover,
        )
        ic = analyze_ic(result)
        ga = analyze_groups(result)
        ra = analyze_returns(result)
        ta = analyze_turnover(result)
        sa = analyze_stability(result)
        oa = analyze_oos(result)
        ca = analyze_cost(result)
        score = compute_score(ic, ga, ra, ta, sa, oa, ca)
        assert score["score"] > 0
        assert score["pass_threshold"] == 60
        assert score["status"] in ("通过", "失败", "待更新")
        assert "breakdown" in score

    def test_run_l5_validation(self):
        from llmwikify.reproduction.backtest_pkg.l5_validation import run_l5_validation
        result = self._make_result()
        l5 = run_l5_validation(result)
        assert "factor_analysis" in l5
        assert "overall_assessment" in l5
        assert "hypothesis_testing" in l5
        assert l5["overall_assessment"]["score"] > 0


class TestL5Orchestrator:
    """Tests for L5 orchestrator (non-backtest parts)."""

    def test_parse_llm_response_valid(self):
        from llmwikify.reproduction.backtest_pkg.l5_orchestrator import (
            _parse_llm_response,
        )
        resp = '''```json
{
  "hypothesis_testing": [
    {"hypothesis_id": "H1", "conclusion": "支持", "reasoning": "IC为正"}
  ],
  "final_meaning": "动量因子"
}```'''
        parsed = _parse_llm_response(resp)
        assert "hypothesis_testing" in parsed
        assert parsed["hypothesis_testing"][0]["conclusion"] == "支持"
        assert parsed["final_meaning"] == "动量因子"

    def test_parse_llm_response_invalid(self):
        from llmwikify.reproduction.backtest_pkg.l5_orchestrator import (
            _parse_llm_response,
        )
        parsed = _parse_llm_response("not json at all")
        assert parsed == {}

    def test_build_hypothesis_prompt(self):
        from llmwikify.reproduction.backtest_pkg.l5_orchestrator import (
            _build_hypothesis_prompt,
        )
        factor = {
            "name": "test_factor",
            "category": "price",
            "subcategory": "momentum",
            "l1": {"definition": "test definition"},
            "l4": {"hypotheses": [{"id": "H1", "name": "test"}]},
        }
        l5_data = {
            "factor_analysis": {
                "ic_analysis": {"ic_mean": 0.05, "icir": 1.0, "rank_ic_mean": 0.04, "win_rate": 0.6},
                "group_analysis": {"group_returns": {"G1": 0.1}, "group_monotonicity": "G1", "ls_ann_return": 0.2, "ls_sharpe": 1.0},
                "return_analysis": {"ann_return": 0.2, "sharpe": 1.0, "calmar": 0.5, "sortino": 1.2},
                "turnover_analysis": {"avg_turnover": 0.3},
                "oos_analysis": {"oos_rank_ic": 0.03, "oos_sharpe": 0.8},
                "cost_analysis": {"net_ann_return": 0.15},
            },
            "overall_assessment": {"score": 75},
        }
        prompt = _build_hypothesis_prompt(factor, l5_data)
        assert "test_factor" in prompt
        assert "H1" in prompt
        assert "0.05" in prompt


# ═══════════════════════════════════════════════════════════════
# Factor Value Store Tests
# ═══════════════════════════════════════════════════════════════

class TestFactorValueStore:
    """Tests for DuckDB factor value storage."""

    def test_store_and_query(self, tmp_path):
        import pandas as pd

        from llmwikify.reproduction.backtest_pkg.factor_value_store import (
            query_factor_values,
            store_factor_values,
        )

        db_path = tmp_path / "test.duckdb"
        dates = pd.date_range("2024-01-01", periods=5)
        stocks = ["000001.SZ", "000002.SZ"]
        data = pd.DataFrame(
            [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6], [0.7, 0.8], [0.9, 1.0]],
            index=dates,
            columns=stocks,
        )

        count = store_factor_values(data, "test_factor", db_path)
        assert count == 10  # 5 dates × 2 stocks

        result = query_factor_values("test_factor", db_path=db_path)
        assert len(result) == 10
        assert "date" in result.columns
        assert "stock" in result.columns
        assert "value" in result.columns

    def test_store_empty(self, tmp_path):
        import pandas as pd

        from llmwikify.reproduction.backtest_pkg.factor_value_store import (
            store_factor_values,
        )

        db_path = tmp_path / "test.duckdb"
        data = pd.DataFrame()
        count = store_factor_values(data, "empty_factor", db_path)
        assert count == 0

    def test_upsert(self, tmp_path):
        import pandas as pd

        from llmwikify.reproduction.backtest_pkg.factor_value_store import (
            query_factor_values,
            store_factor_values,
        )

        db_path = tmp_path / "test.duckdb"
        dates = pd.date_range("2024-01-01", periods=3)
        data1 = pd.DataFrame({"A": [1.0, 2.0, 3.0]}, index=dates)
        data2 = pd.DataFrame({"A": [4.0, 5.0, 6.0]}, index=dates)

        store_factor_values(data1, "upsert_test", db_path)
        store_factor_values(data2, "upsert_test", db_path)  # Should replace

        result = query_factor_values("upsert_test", db_path=db_path)
        assert len(result) == 3
        assert result["value"].max() == 6.0  # Should have new values

    def test_list_stored_factors(self, tmp_path):
        import pandas as pd

        from llmwikify.reproduction.backtest_pkg.factor_value_store import (
            list_stored_factors,
            store_factor_values,
        )

        db_path = tmp_path / "test.duckdb"
        dates = pd.date_range("2024-01-01", periods=3)
        data = pd.DataFrame({"A": [1.0, 2.0, 3.0]}, index=dates)

        store_factor_values(data, "factor_a", db_path)
        store_factor_values(data, "factor_b", db_path)

        factors = list_stored_factors(db_path)
        assert len(factors) == 2
        names = [f["factor_name"] for f in factors]
        assert "factor_a" in names
        assert "factor_b" in names

    def test_query_with_date_filter(self, tmp_path):
        import pandas as pd

        from llmwikify.reproduction.backtest_pkg.factor_value_store import (
            query_factor_values,
            store_factor_values,
        )

        db_path = tmp_path / "test.duckdb"
        dates = pd.date_range("2024-01-01", periods=10)
        data = pd.DataFrame({"A": range(10)}, index=dates, dtype=float)

        store_factor_values(data, "date_filter_test", db_path)

        result = query_factor_values(
            "date_filter_test",
            start_date="2024-01-03",
            end_date="2024-01-07",
            db_path=db_path,
        )
        assert len(result) == 5  # Jan 3-7


# ═══════════════════════════════════════════════════════════════
# Extract Factors Deprecated Function Tests
# ═══════════════════════════════════════════════════════════════

class TestExtractFactorsDeprecated:
    """Tests that deprecated functions in extract_factors.py redirect properly."""

    def test_read_factor_from_wiki_redirects(self):
        import warnings

        from llmwikify.reproduction.paper_understanding.extract_factors import (
            read_factor_from_wiki,
        )

        class FakeWiki:
            def __init__(self):
                self.wiki_dir = Path("/nonexistent")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = read_factor_from_wiki(FakeWiki(), "test")
            assert result is None  # factor_library.read_factor_yaml returns None for nonexistent
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "deprecated" in str(w[0].message).lower()

    def test_list_factors_redirects(self):
        import warnings

        from llmwikify.reproduction.paper_understanding.extract_factors import (
            list_factors,
        )

        class FakeWiki:
            def __init__(self):
                self.wiki_dir = Path("/nonexistent")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = list_factors(FakeWiki())
            # factor_library.list_factors reads from real index.yaml
            # so result depends on cwd. Just verify it returns a list.
            assert isinstance(result, list)
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)

    def test_build_factor_pages_warns(self):
        import warnings

        from llmwikify.reproduction.paper_understanding.extract_factors import (
            build_factor_pages,
        )

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = build_factor_pages(
                [{"name": "test", "factor_class": "momentum"}],
                "paper1",
            )
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert len(result) == 1
            assert result[0]["page_type"] == "Factor"


# ═══════════════════════════════════════════════════════════════
# L5 Validation Edge Case Tests
# ═══════════════════════════════════════════════════════════════

class TestL5ValidationEdgeCases:
    """Edge case tests for L5 validation engine."""

    def _mock_result(self, **kwargs):
        from dataclasses import dataclass, field

        @dataclass
        class R:
            ic_mean: float = 0.0
            ic_std: float = 0.01
            icir: float = 0.0
            t_stat: float = 0.0
            win_rate: float = 0.5
            annual_return: float = 0.0
            max_drawdown: float = 0.0
            turnover: float = 0.0
            quantile_returns: dict = field(default_factory=dict)
            ic_series: list = field(default_factory=list)
            quantile_curves: dict = field(default_factory=dict)
            rank_ic_mean: float = 0.0
            rank_ic_std: float = 0.01
            rank_icir: float = 0.0
            rank_ic_pos_ratio: float = 0.0
            longshort_ann_return: float = 0.0
            longshort_sharpe: float = 0.0
            longshort_mdd: float = 0.0
            longshort_curve: list = field(default_factory=list)
            universe: str = ""
            adj_mode: str = "D"
            n_stocks_per_date: list = field(default_factory=list)
            group_metrics: dict = field(default_factory=dict)
            total_rebalances: int = 0
            valid_rebalances: int = 0

        r = R()
        for k, v in kwargs.items():
            setattr(r, k, v)
        return r

    def test_analyze_ic_all_positive(self):
        from llmwikify.reproduction.backtest_pkg.l5_validation import analyze_ic
        result = self._mock_result(
            ic_series=[
                {"date": "2024-01", "ic": 0.05, "rank_ic": 0.04},
                {"date": "2024-02", "ic": 0.06, "rank_ic": 0.05},
                {"date": "2024-03", "ic": 0.04, "rank_ic": 0.03},
            ]
        )
        ic = analyze_ic(result)
        assert ic["win_rate"] == 1.0  # all positive
        assert ic["ic_mean"] > 0

    def test_analyze_ic_all_negative(self):
        from llmwikify.reproduction.backtest_pkg.l5_validation import analyze_ic
        result = self._mock_result(
            ic_series=[
                {"date": "2024-01", "ic": -0.05, "rank_ic": -0.04},
                {"date": "2024-02", "ic": -0.06, "rank_ic": -0.05},
            ]
        )
        ic = analyze_ic(result)
        assert ic["win_rate"] == 0.0  # none positive
        assert ic["ic_mean"] < 0

    def test_analyze_groups_reverse_factor(self):
        """Reverse factor: G5 > G1 (negative IC)."""
        from llmwikify.reproduction.backtest_pkg.l5_validation import analyze_groups
        result = self._mock_result(
            quantile_returns={"G1": -0.05, "G2": -0.02, "G3": 0.01, "G4": 0.03, "G5": 0.05},
            longshort_ann_return=-0.10,
            longshort_sharpe=-0.8,
            longshort_mdd=0.12,
        )
        ga = analyze_groups(result)
        assert ga["ls_ann_return"] == -0.10
        assert "G5" in ga["group_monotonicity"]

    def test_analyze_returns_zero_sharpe(self):
        from llmwikify.reproduction.backtest_pkg.l5_validation import analyze_returns
        result = self._mock_result(
            longshort_ann_return=0.0,
            longshort_mdd=0.0,
            longshort_curve=[
                {"date": "2024-01", "value": 1.0},
                {"date": "2024-02", "value": 1.0},
            ],
        )
        ra = analyze_returns(result)
        assert ra["sharpe"] == 0.0 or ra["sharpe"] == 0

    def test_analyze_turnover_high(self):
        from llmwikify.reproduction.backtest_pkg.l5_validation import analyze_turnover
        result = self._mock_result(
            group_metrics={
                "G1": {"turnover": 0.9},
                "G2": {"turnover": 0.85},
                "G3": {"turnover": 0.8},
            }
        )
        ta = analyze_turnover(result)
        assert ta["avg_turnover"] > 0.8

    def test_analyze_stability_single_year(self):
        from llmwikify.reproduction.backtest_pkg.l5_validation import analyze_stability
        result = self._mock_result(
            ic_series=[{"date": "2024-01-01", "ic": 0.05}]
        )
        sa = analyze_stability(result)
        assert len(sa["yearly"]) == 1

    def test_analyze_oos_short_series(self):
        """OOS with very short IC series (< 10 points)."""
        from llmwikify.reproduction.backtest_pkg.l5_validation import analyze_oos
        result = self._mock_result(
            ic_series=[{"date": f"2024-0{i}", "ic": 0.01} for i in range(1, 6)]
        )
        oa = analyze_oos(result)
        assert oa["oos_rank_ic"] == 0.0  # Not enough data

    def test_analyze_cost_zero_turnover(self):
        from llmwikify.reproduction.backtest_pkg.l5_validation import analyze_cost
        result = self._mock_result(turnover=0.0, group_metrics={})
        ca = analyze_cost(result, cost_bps=15)
        assert ca["net_ann_return"] == 0.0

    def test_score_all_zeros(self):
        from llmwikify.reproduction.backtest_pkg.l5_validation import compute_score
        score = compute_score({}, {}, {}, {}, {}, {}, {})
        assert score["score"] > 0  # Minimum scores for each dimension
        assert score["status"] in ("通过", "失败", "待更新")

    def test_score_perfect(self):
        """Test scoring with excellent metrics."""
        from llmwikify.reproduction.backtest_pkg.l5_validation import compute_score
        score = compute_score(
            ic_analysis={"ic_mean": 0.08, "icir": 1.5, "rank_ic_mean": 0.07},
            group_analysis={"ls_sharpe": 2.0, "ls_ann_return": 0.3, "ls_max_drawdown": 0.05,
                           "group_returns": {"G1": 0.3, "G2": 0.2, "G3": 0.1, "G4": 0.0, "G5": -0.1}},
            return_analysis={"sharpe": 1.5, "calmar": 1.2, "sortino": 2.0},
            turnover_analysis={"avg_turnover": 0.1},
            stability_analysis={"yearly": {"2022": {"rank_ic": 0.05}, "2023": {"rank_ic": 0.06}, "2024": {"rank_ic": 0.04}}},
            oos_analysis={"oos_rank_ic": 0.05},
            cost_analysis={"net_ann_return": 0.10},
        )
        assert score["score"] >= 80
        assert score["status"] == "通过"

    def test_score_reverse_factor_low(self):
        """Reverse factor with all negative metrics scores low."""
        from llmwikify.reproduction.backtest_pkg.l5_validation import compute_score
        score = compute_score(
            ic_analysis={"ic_mean": -0.05, "icir": -1.0, "rank_ic_mean": -0.04},
            group_analysis={"ls_sharpe": -1.0, "ls_ann_return": -0.2, "ls_max_drawdown": 0.1,
                           "group_returns": {"G1": -0.2, "G2": -0.1, "G3": 0.0, "G4": 0.1, "G5": 0.2}},
            return_analysis={"sharpe": -1.0, "calmar": -0.5, "sortino": -1.2},
            turnover_analysis={"avg_turnover": 0.3},
            stability_analysis={"yearly": {"2023": {"rank_ic": -0.04}}},
            oos_analysis={"oos_rank_ic": -0.03},
            cost_analysis={"net_ann_return": -0.15},
        )
        # Reverse factor scores lower than a perfect factor
        assert score["score"] < 80
        assert score["status"] in ("通过", "失败")


# ═══════════════════════════════════════════════════════════════
# L5 Orchestrator Integration Tests
# ═══════════════════════════════════════════════════════════════

class TestL5OrchestratorIntegration:
    """Integration tests for L5 orchestrator (non-backtest parts)."""

    def test_parse_llm_response_with_markdown_fences(self):
        from llmwikify.reproduction.backtest_pkg.l5_orchestrator import (
            _parse_llm_response,
        )
        resp = '''Here is the result:
```json
{
  "hypothesis_testing": [
    {"hypothesis_id": "H1", "conclusion": "支持", "reasoning": "IC positive"}
  ],
  "final_meaning": "Momentum factor"
}
```
'''
        parsed = _parse_llm_response(resp)
        assert "hypothesis_testing" in parsed
        assert len(parsed["hypothesis_testing"]) == 1

    def test_parse_llm_response_empty_json(self):
        from llmwikify.reproduction.backtest_pkg.l5_orchestrator import (
            _parse_llm_response,
        )
        parsed = _parse_llm_response("{}")
        assert parsed == {}

    def test_parse_llm_response_no_json(self):
        from llmwikify.reproduction.backtest_pkg.l5_orchestrator import (
            _parse_llm_response,
        )
        parsed = _parse_llm_response("I cannot determine the answer.")
        assert parsed == {}

    def test_build_hypothesis_prompt_includes_all_metrics(self):
        from llmwikify.reproduction.backtest_pkg.l5_orchestrator import (
            _build_hypothesis_prompt,
        )
        factor = {
            "name": "test_momentum",
            "category": "price",
            "subcategory": "momentum",
            "l1": {"definition": "20日动量"},
            "l4": {"hypotheses": [
                {"id": "H1", "name": "动量延续", "description": "高动量→涨"},
                {"id": "H2", "name": "反转回落", "description": "高动量→跌"},
            ]},
        }
        l5_data = {
            "factor_analysis": {
                "ic_analysis": {"ic_mean": 0.05, "icir": 0.8, "rank_ic_mean": 0.04, "win_rate": 0.6},
                "group_analysis": {"group_returns": {"G1": 0.2}, "group_monotonicity": "G1>G5",
                                  "ls_ann_return": 0.25, "ls_sharpe": 1.2},
                "return_analysis": {"ann_return": 0.25, "sharpe": 1.0, "calmar": 0.8, "sortino": 1.3},
                "turnover_analysis": {"avg_turnover": 0.3},
                "oos_analysis": {"oos_rank_ic": 0.03, "oos_sharpe": 0.9},
                "cost_analysis": {"net_ann_return": 0.18},
            },
            "overall_assessment": {"score": 72},
        }
        prompt = _build_hypothesis_prompt(factor, l5_data)
        # Check all key metrics are in the prompt
        assert "H1" in prompt
        assert "H2" in prompt
        assert "0.05" in prompt  # ic_mean
        assert "0.8" in prompt   # icir
        assert "72" in prompt    # score

    def test_run_l5_pipeline_factor_not_found(self):
        from llmwikify.reproduction.backtest_pkg.l5_orchestrator import run_l5_pipeline
        result = run_l5_pipeline("nonexistent/factor/path")
        assert result["success"] is False
        assert "not found" in result["error"]


# ═══════════════════════════════════════════════════════════════
# Factor Value Store Extended Tests
# ═══════════════════════════════════════════════════════════════

class TestFactorValueStoreExtended:
    """Extended tests for factor value store."""

    def test_store_single_stock(self, tmp_path):
        import pandas as pd

        from llmwikify.reproduction.backtest_pkg.factor_value_store import (
            query_factor_values,
            store_factor_values,
        )

        db_path = tmp_path / "test.duckdb"
        dates = pd.date_range("2024-01-01", periods=3)
        data = pd.DataFrame({"600000.SH": [0.1, 0.2, 0.3]}, index=dates)

        count = store_factor_values(data, "single_stock", db_path)
        assert count == 3

        result = query_factor_values("single_stock", db_path=db_path)
        assert len(result) == 3
        assert result["stock"].unique() == ["600000.SH"]

    def test_store_many_stocks(self, tmp_path):
        import pandas as pd

        from llmwikify.reproduction.backtest_pkg.factor_value_store import (
            store_factor_values,
        )

        db_path = tmp_path / "test.duckdb"
        dates = pd.date_range("2024-01-01", periods=2)
        stocks = [f"{i:06d}.SZ" for i in range(1, 51)]
        data = pd.DataFrame(
            [[i * 0.01] * 50 for i in range(2)],
            index=dates,
            columns=stocks,
        )

        count = store_factor_values(data, "many_stocks", db_path)
        assert count == 100  # 2 dates × 50 stocks

    def test_query_with_stock_filter(self, tmp_path):
        import pandas as pd

        from llmwikify.reproduction.backtest_pkg.factor_value_store import (
            query_factor_values,
            store_factor_values,
        )

        db_path = tmp_path / "test.duckdb"
        dates = pd.date_range("2024-01-01", periods=3)
        data = pd.DataFrame(
            {"A": [1.0, 2.0, 3.0], "B": [4.0, 5.0, 6.0]},
            index=dates,
        )

        store_factor_values(data, "stock_filter", db_path)
        result = query_factor_values(
            "stock_filter",
            stocks=["A"],
            db_path=db_path,
        )
        assert len(result) == 3
        assert (result["stock"] == "A").all()

    def test_store_nan_values_excluded(self, tmp_path):
        import numpy as np
        import pandas as pd

        from llmwikify.reproduction.backtest_pkg.factor_value_store import (
            store_factor_values,
        )

        db_path = tmp_path / "test.duckdb"
        dates = pd.date_range("2024-01-01", periods=4)
        data = pd.DataFrame(
            {"A": [0.1, np.nan, 0.3, 0.4]},
            index=dates,
        )

        count = store_factor_values(data, "nan_test", db_path)
        assert count == 3  # NaN excluded

    def test_multiple_factors_same_db(self, tmp_path):
        import pandas as pd

        from llmwikify.reproduction.backtest_pkg.factor_value_store import (
            list_stored_factors,
            store_factor_values,
        )

        db_path = tmp_path / "test.duckdb"
        dates = pd.date_range("2024-01-01", periods=3)

        for i, name in enumerate(["factor_a", "factor_b", "factor_c"]):
            data = pd.DataFrame({"X": [float(i)] * 3}, index=dates)
            store_factor_values(data, name, db_path)

        factors = list_stored_factors(db_path)
        assert len(factors) == 3
        names = sorted([f["factor_name"] for f in factors])
        assert names == ["factor_a", "factor_b", "factor_c"]

    def test_store_empty_wide_df(self, tmp_path):
        import pandas as pd

        from llmwikify.reproduction.backtest_pkg.factor_value_store import (
            store_factor_values,
        )

        db_path = tmp_path / "test.duckdb"
        data = pd.DataFrame(index=pd.date_range("2024-01-01", periods=3))
        count = store_factor_values(data, "empty_wide", db_path)
        assert count == 0


# ═══════════════════════════════════════════════════════════════
# Factor Library Write→Index Sync Tests
# ═══════════════════════════════════════════════════════════════

class TestFactorLibraryIndexSync:
    """Tests that write_factor_yaml auto-syncs index.yaml."""

    def test_write_creates_index(self, project_root):
        from llmwikify.reproduction.persist.factor_library import (
            list_factors,
            write_factor_yaml,
        )

        factor_data = {
            "factor": {
                "name": "sync_factor_a",
                "asset_type": "stock",
                "category": "price",
                "subcategory": "momentum",
                "l1": {"definition": "test"},
            }
        }
        write_factor_yaml("stock/price/sync_factor_a", factor_data, project_root)

        # Index should now contain the factor
        factors = list_factors(project_root)
        names = [f["name"] for f in factors]
        assert "sync_factor_a" in names

    def test_write_updates_index_stats(self, project_root):
        from llmwikify.reproduction.persist.factor_library import (
            list_factors,
            write_factor_yaml,
        )

        # Write two factors
        for name, cat in [("f1", "price"), ("f2", "fundamental")]:
            data = {
                "factor": {
                    "name": name,
                    "asset_type": "stock",
                    "category": cat,
                    "subcategory": "test",
                    "l1": {"definition": "test"},
                }
            }
            write_factor_yaml(f"stock/{cat}/{name}", data, project_root)

        factors = list_factors(project_root)
        assert len(factors) == 2

    def test_write_overwrites_existing(self, project_root):
        from llmwikify.reproduction.persist.factor_library import (
            read_factor_yaml,
            write_factor_yaml,
        )

        data1 = {"factor": {"name": "overwrite_test", "l1": {"definition": "version1"}}}
        data2 = {"factor": {"name": "overwrite_test", "l1": {"definition": "version2"}}}

        write_factor_yaml("stock/price/overwrite_test", data1, project_root)
        write_factor_yaml("stock/price/overwrite_test", data2, project_root)

        result = read_factor_yaml("stock/price/overwrite_test", project_root)
        assert result["factor"]["l1"]["definition"] == "version2"


# ═══════════════════════════════════════════════════════════════
# Paper Edge Case Tests
# ═══════════════════════════════════════════════════════════════

class TestFactorLibraryReadEdgeCases:
    """Edge cases for factor_library.read_factor_yaml."""

class TestFactorLibraryReadEdgeCases:
    """Edge cases for factor_library.read_factor_yaml."""

    def test_read_nested_path(self, project_root):
        from llmwikify.reproduction.persist.factor_library import (
            read_factor_yaml,
            write_factor_yaml,
        )

        data = {"factor": {"name": "nested_test", "l1": {"definition": "deep"}}}
        write_factor_yaml("stock/price/momentum/nested_test", data, project_root)

        result = read_factor_yaml("stock/price/momentum/nested_test", project_root)
        assert result["factor"]["l1"]["definition"] == "deep"

    def test_read_with_special_chars(self, project_root):
        from llmwikify.reproduction.persist.factor_library import (
            read_factor_yaml,
            write_factor_yaml,
        )

        data = {"factor": {"name": "special_test", "l1": {"definition": "test with 中文"}}}
        write_factor_yaml("stock/price/special_test", data, project_root)

        result = read_factor_yaml("stock/price/special_test", project_root)
        assert result["factor"]["l1"]["definition"] == "test with 中文"

    def test_list_factors_by_category_empty(self, project_root):
        from llmwikify.reproduction.persist.factor_library import (
            list_factors_by_category,
        )
        result = list_factors_by_category(project_root)
        assert result == {}


# ═══════════════════════════════════════════════════════════════
# QuantWiki Edge Cases
# ═══════════════════════════════════════════════════════════════

class TestQuantWikiExtended:
    """Extended edge cases for quant_wiki."""

    def test_read_page_invalid_type_raises(self, quant_root):
        from llmwikify.reproduction.paper_understanding.quant_wiki import QuantWiki
        wiki = QuantWiki(quant_root)
        with pytest.raises(ValueError, match="Unknown page_type"):
            wiki.read_page("test", page_type="nonexistent")

    def test_list_pages_invalid_type_raises(self, quant_root):
        from llmwikify.reproduction.paper_understanding.quant_wiki import QuantWiki
        wiki = QuantWiki(quant_root)
        with pytest.raises(ValueError, match="Unknown page_type"):
            wiki.list_pages("nonexistent")

    def test_write_page_overwrites_content(self, quant_root):
        from llmwikify.reproduction.paper_understanding.quant_wiki import QuantWiki
        wiki = QuantWiki(quant_root)
        wiki.write_page("test", "version1", page_type="papers")
        wiki.write_page("test", "version2", page_type="papers")
        result = wiki.read_page("test", page_type="papers")
        assert result["content"] == "version2"

    def test_write_page_returns_action(self, quant_root):
        from llmwikify.reproduction.paper_understanding.quant_wiki import QuantWiki
        wiki = QuantWiki(quant_root)
        result = wiki.write_page("new_page", "content", page_type="papers")
        assert "Created" in result
        result2 = wiki.write_page("new_page", "content2", page_type="papers")
        assert "Updated" in result2


# ═══════════════════════════════════════════════════════════════
# L5 Validation Module Import Tests
# ═══════════════════════════════════════════════════════════════

class TestModuleImports:
    """Test that all modules can be imported without errors."""

    def test_import_l5_validation(self):
        import llmwikify.reproduction.backtest_pkg.l5_validation as m
        assert hasattr(m, "analyze_ic")
        assert hasattr(m, "analyze_groups")
        assert hasattr(m, "analyze_returns")
        assert hasattr(m, "analyze_turnover")
        assert hasattr(m, "analyze_stability")
        assert hasattr(m, "analyze_oos")
        assert hasattr(m, "analyze_cost")
        assert hasattr(m, "compute_score")
        assert hasattr(m, "run_l5_validation")

    def test_import_l5_orchestrator(self):
        import llmwikify.reproduction.backtest_pkg.l5_orchestrator as m
        assert hasattr(m, "run_l5_pipeline")
        assert hasattr(m, "_build_hypothesis_prompt")
        assert hasattr(m, "_parse_llm_response")

    def test_import_factor_value_store(self):
        import llmwikify.reproduction.backtest_pkg.factor_value_store as m
        assert hasattr(m, "store_factor_values")
        assert hasattr(m, "query_factor_values")
        assert hasattr(m, "list_stored_factors")
        assert hasattr(m, "compute_and_store_factor")

    def test_import_factor_library(self):
        import llmwikify.reproduction.persist.factor_library as m
        assert hasattr(m, "list_factors")
        assert hasattr(m, "read_factor_yaml")
        assert hasattr(m, "write_factor_yaml")
        assert hasattr(m, "list_factors_by_category")
        assert hasattr(m, "update_index")

    def test_import_quant_wiki(self):
        import llmwikify.reproduction.paper_understanding.quant_wiki as m
        assert hasattr(m, "QuantWiki")
        assert hasattr(m, "get_quant_root")
        assert hasattr(m, "get_quant_wiki")
