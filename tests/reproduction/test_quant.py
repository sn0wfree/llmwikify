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
        from llmwikify.reproduction.quant_wiki import QuantWiki

        qw = QuantWiki(quant_root)
        result = qw.write_page("test-paper", "# Test Content\n\nHello", "papers")
        assert "Created" in result

        page = qw.read_page("test-paper", "papers")
        assert page is not None
        assert page["content"] == "# Test Content\n\nHello"

    def test_read_nonexistent(self, quant_root):
        from llmwikify.reproduction.quant_wiki import QuantWiki

        qw = QuantWiki(quant_root)
        result = qw.read_page("nonexistent", "papers")
        assert result is None

    def test_list_pages(self, quant_root):
        from llmwikify.reproduction.quant_wiki import QuantWiki

        qw = QuantWiki(quant_root)
        qw.write_page("paper-a", "# A", "papers")
        qw.write_page("paper-b", "# B", "papers")
        pages = qw.list_pages("papers")
        assert len(pages) == 2
        names = [p.get("_slug") or p.get("page_name") for p in pages]
        assert "paper-a" in names
        assert "paper-b" in names

    def test_write_factor_yaml(self, quant_root):
        from llmwikify.reproduction.quant_wiki import QuantWiki

        qw = QuantWiki(quant_root)
        data = {"factor": {"name": "test", "l1": {"definition": "test factor"}}}
        result = qw.write_factor_yaml("stock/price/test", data)
        assert "Created" in result

        loaded = qw.read_factor_yaml("stock/price/test")
        assert loaded is not None
        assert loaded["factor"]["name"] == "test"

    def test_list_factor_yamls(self, quant_root):
        from llmwikify.reproduction.quant_wiki import QuantWiki

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
        from llmwikify.reproduction.quant_wiki import QuantWiki

        qw = QuantWiki(quant_root)
        content = "---\ntitle: Test Page\nauthor: test\n---\n\n# Content"
        qw.write_page("test-fm", content, "papers")
        page = qw.read_page("test-fm", "papers")
        assert page is not None
        assert page["title"] == "Test Page"
        assert page["author"] == "test"
        assert "# Content" in page["content"]

    def test_invalid_page_type(self, quant_root):
        from llmwikify.reproduction.quant_wiki import QuantWiki

        qw = QuantWiki(quant_root)
        with pytest.raises(ValueError, match="Unknown page_type"):
            qw.write_page("test", "content", "invalid_type")


# ── Factor Library Tests ──────────────────────────────────────


class TestFactorLibrary:
    """Tests for factor_library read/write/list operations."""

    def test_write_and_read_factor(self, project_root):
        from llmwikify.reproduction.factor_library import read_factor_yaml, write_factor_yaml

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
        from llmwikify.reproduction.factor_library import read_factor_yaml

        result = read_factor_yaml("nonexistent", project_root)
        assert result is None

    def test_list_factors_by_category(self, project_root):
        from llmwikify.reproduction.factor_library import list_factors_by_category, write_factor_yaml

        write_factor_yaml("stock/price/mom", {"factor": {"name": "mom", "category": "price"}}, project_root)
        write_factor_yaml("stock/price/vol", {"factor": {"name": "vol", "category": "price"}}, project_root)
        write_factor_yaml("stock/fundamental/val", {"factor": {"name": "val", "category": "fundamental"}}, project_root)

        cats = list_factors_by_category(project_root)
        assert "price" in cats
        assert "fundamental" in cats
        assert len(cats["price"]) == 2
        assert len(cats["fundamental"]) == 1

    def test_update_index(self, project_root):
        from llmwikify.reproduction.factor_library import list_factors, update_index, write_factor_yaml

        write_factor_yaml("stock/price/mom", {"factor": {"name": "mom", "category": "price", "status": "已注册"}}, project_root)
        write_factor_yaml("stock/price/vol", {"factor": {"name": "vol", "category": "price", "status": "已通过"}}, project_root)

        update_index(project_root)
        factors = list_factors(project_root)
        assert len(factors) == 2
        names = {f["name"] for f in factors}
        assert names == {"mom", "vol"}

    def test_update_index_empty(self, project_root):
        from llmwikify.reproduction.factor_library import list_factors, update_index

        update_index(project_root)
        factors = list_factors(project_root)
        assert len(factors) == 0

    def test_list_factors_empty(self, project_root):
        from llmwikify.reproduction.factor_library import list_factors

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
        from llmwikify.reproduction import factor_library
        monkeypatch.setattr(factor_library, "_get_factors_dir", lambda *a, **k: tmp_path / "nonexistent")

        client, _ = factor_client
        r = client.get("/api/factor/list")
        assert r.status_code == 200

    def test_list_with_factors(self, factor_client, monkeypatch, tmp_path):
        from llmwikify.reproduction import factor_library

        factors_dir = tmp_path / "quant_factors"
        factors_dir.mkdir()
        monkeypatch.setattr(factor_library, "_get_factors_dir", lambda *a, **k: factors_dir)

        # Write a factor YAML
        factor_data = {
            "factor": {
                "name": "test_factor",
                "category": "price",
                "l1": {"definition": "test"},
            }
        }
        factor_dir = factors_dir / "stock" / "price"
        factor_dir.mkdir(parents=True)
        (factor_dir / "test_factor.yaml").write_text(
            yaml.dump(factor_data, allow_unicode=True),
            encoding="utf-8",
        )

        client, _ = factor_client
        r = client.get("/api/factor/list")
        assert r.status_code == 200
        categories = r.json()["categories"]
        assert "price" in categories

    def test_get_factor(self, factor_client, monkeypatch, tmp_path):
        from llmwikify.reproduction import factor_library

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
        from llmwikify.reproduction import factor_library
        monkeypatch.setattr(factor_library, "_get_factors_dir", lambda *a, **k: tmp_path / "nonexistent")

        client, _ = factor_client
        r = client.get("/api/factor/nonexistent")
        assert r.status_code == 404


# ── Strategy API Tests (Modified) ─────────────────────────────


class TestStrategyAPIRedirected:
    """Tests for strategy API reading from quant/strategies/."""

    def test_list_empty(self, strategy_client, monkeypatch, tmp_path):
        from llmwikify.reproduction import quant_wiki
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
        from llmwikify.reproduction import quant_wiki

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
        from llmwikify.reproduction import factor_library
        monkeypatch.setattr(factor_library, "_get_factors_dir", lambda *a, **k: tmp_path / "empty")

        client, _ = factor_client
        r = client.get("/api/factor/library/list")
        assert r.status_code == 200
        assert r.json()["categories"] == {}

    def test_library_list_with_factors(self, factor_client, monkeypatch, tmp_path):
        from llmwikify.reproduction import factor_library

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
        from llmwikify.reproduction import factor_library

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
        from llmwikify.reproduction import factor_library
        monkeypatch.setattr(factor_library, "_get_factors_dir", lambda *a, **k: tmp_path / "empty")

        client, _ = factor_client
        r = client.get("/api/factor/library/nonexistent")
        assert r.status_code == 404

    def test_library_update_factor(self, factor_client, monkeypatch, tmp_path):
        from llmwikify.reproduction import factor_library

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


# ── _extract_factor_from_page Tests ──────────────────────────


class TestExtractFactorFromPage:
    """Tests for the factor page-to-YAML converter."""

    def test_extract_factor_from_page(self):
        from llmwikify.interfaces.server.http.paper import _extract_factor_from_page

        page = {
            "page_name": "factor-test-paper-momentum",
            "content": (
                "---\ntitle: Momentum Factor\n"
                "factor_class: momentum\n"
                "factor_params: {lookback: 20}\n"
                "signal_type: momentum\n"
                "signal_params: {lookback: 20}\n"
                "status: draft\n---\n\n"
                "# Factor\n\nSome content"
            ),
        }
        result = _extract_factor_from_page(page, "test-paper")
        # generate_slug("Momentum Factor") = "momentum-factor"
        assert result["name"] == "factor_test-paper_momentum-factor"
        assert result["l1"]["definition"] == "Factor extracted from test-paper"
        # frontmatter may parse as string or int depending on YAML parser
        params = result["l1"]["default_params"]
        assert params["lookback"] == 20 or params["lookback"] == "20"
        assert result["l2"]["complexity"] == "O(T × N)"

    def test_extract_factor_string_params(self):
        from llmwikify.interfaces.server.http.paper import _extract_factor_from_page

        page = {
            "page_name": "factor-test-rsi",
            "content": (
                "---\ntitle: RSI\n"
                "factor_class: rsi\n"
                "signal_params: '{\"period\": 14}'\n"
                "signal_type: rsi\n---\n"
            ),
        }
        result = _extract_factor_from_page(page, "test")
        assert result["l1"]["default_params"] == {"period": 14}

    def test_extract_factor_missing_fields(self):
        from llmwikify.interfaces.server.http.paper import _extract_factor_from_page

        page = {
            "page_name": "factor-test-unknown",
            "content": "---\ntitle: Unknown\n---\n",
        }
        result = _extract_factor_from_page(page, "test")
        # generate_slug("Unknown") = "unknown"
        assert result["name"] == "factor_test_unknown"
        assert result["l1"]["definition"] == "Factor extracted from test"
        assert result["l1"]["default_params"] == {}


# ── QuantWiki / FactorLibrary Edge Case Tests ────────────────


class TestQuantWikiEdgeCases:
    """Edge case tests for QuantWiki."""

    def test_ensure_dirs(self, tmp_path):
        from llmwikify.reproduction.quant_wiki import QuantWiki

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
        from llmwikify.reproduction.quant_wiki import QuantWiki

        qw = QuantWiki(quant_root)
        pages = qw.list_pages("papers")
        assert pages == []

    def test_list_factor_yamls_empty(self, quant_root):
        from llmwikify.reproduction.quant_wiki import QuantWiki

        qw = QuantWiki(quant_root)
        factors = qw.list_factor_yamls()
        assert factors == []

    def test_malformed_frontmatter(self, quant_root):
        from llmwikify.reproduction.quant_wiki import QuantWiki

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
        from llmwikify.reproduction.quant_wiki import QuantWiki

        qw = QuantWiki(quant_root)
        result = qw.write_page("empty", "", "papers")
        assert "Created" in result
        page = qw.read_page("empty", "papers")
        assert page["content"] == ""

    def test_write_and_read_factorbacktest(self, quant_root):
        from llmwikify.reproduction.quant_wiki import QuantWiki

        qw = QuantWiki(quant_root)
        result = qw.write_page("bt-001", "# Backtest Result", "factorbacktest")
        assert "Created" in result
        page = qw.read_page("bt-001", "factorbacktest")
        assert page is not None
        assert "# Backtest Result" in page["content"]

    def test_write_and_read_strategies(self, quant_root):
        from llmwikify.reproduction.quant_wiki import QuantWiki

        qw = QuantWiki(quant_root)
        result = qw.write_page("strat-001", "# Strategy", "strategies")
        assert "Created" in result
        page = qw.read_page("strat-001", "strategies")
        assert page is not None


class TestFactorLibraryEdgeCases:
    """Edge case tests for factor_library."""

    def test_corrupt_yaml(self, project_root):
        from llmwikify.reproduction.factor_library import read_factor_yaml

        # Write corrupt YAML
        factors_dir = project_root / "quant" / "factors"
        d = factors_dir / "stock" / "price"
        d.mkdir(parents=True)
        (d / "corrupt.yaml").write_text("{{invalid yaml: [", encoding="utf-8")

        result = read_factor_yaml("stock/price/corrupt", project_root)
        assert result is None

    def test_missing_index(self, project_root):
        from llmwikify.reproduction.factor_library import list_factors

        factors_dir = project_root / "quant" / "factors"
        # index.yaml doesn't exist
        result = list_factors(project_root)
        assert result == []

    def test_update_index_stats(self, project_root):
        from llmwikify.reproduction.factor_library import list_factors, update_index, write_factor_yaml

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
        from llmwikify.reproduction import quant_wiki

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
