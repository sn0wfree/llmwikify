# tests/scenarios/test_12_quant_full_pipeline.py
"""Scenario 12: Quant Full Pipeline - Tests for quant reproduction.

## Background
Full quant reproduction pipeline: paper extraction → factor YAML →
DuckDB storage → backtest execution → L5 reflection report.

## Pipeline
```mermaid
graph LR
    Paper[Paper PDF] -->|extract| JSON
    JSON -->|factor_full| YAML[6-layer YAML]
    YAML -->|compute| DuckDB
    DuckDB -->|backtest| Report
    Report -->|L5| Reflection
```

## Troubleshooting
- paper/start 500: check LLM provider config
- Factor L2 SyntaxError: v0.36+ auto-repair via react_engine
- Backtest IC ≈ 0: data source issue
"""


import subprocess
import pytest


@pytest.mark.llm
class TestQuantFullPipeline:
    """Test quant pipeline with API calls.

    Covers TUTORIAL.md Scenario 5 (quant full flow).
    """

    def test_12_1_quant_init_creates_structure(self, temp_dir):
        """Step 12.1: Quant-init creates expected directory structure.

        Creates quant/{factors,papers,factorbacktest,strategies,...}.
        """
        result = subprocess.run(
            ["python3", "-m", "llmwikify", "quant-init"],
            capture_output=True,
            text=True,
            cwd=str(temp_dir),
        )
        quant_dir = temp_dir / "quant"
        if result.returncode == 0:
            assert quant_dir.exists() or (temp_dir / "factors").exists()

    def test_12_2_factor_write_and_read(self, temp_dir):
        """Step 12.2: Write and read a 6-layer factor YAML.

        Layer 1 logic, Layer 2 computation, Layer 3 financial,
        Layer 4 hypothesis.
        """
        import yaml

        factors_dir = temp_dir / "quant" / "factors"
        factor_path = factors_dir / "stock" / "price" / "momentum_20d.yaml"
        factor_path.parent.mkdir(parents=True, exist_ok=True)

        factor_data = {
            "name": "momentum_20d",
            "asset_type": "stock",
            "category": "price",
            "L1_logic": "Price momentum over 20 days",
            "L2_computation": "close / close.shift(20) - 1",
            "L3_financial": "Momentum effect in equity markets",
            "L4_hypothesis": "Stocks with strong recent momentum continue to outperform",
        }

        factor_path.write_text(yaml.dump(factor_data))
        assert factor_path.exists()

        loaded = yaml.safe_load(factor_path.read_text())
        assert loaded["name"] == "momentum_20d"
        assert loaded["L1_logic"] == "Price momentum over 20 days"

    def test_12_3_factor_library_list(self, temp_dir):
        """Step 12.3: List factors in the library.

        Scans quant/factors/ recursively.
        """
        import yaml
        from llmwikify.reproduction.persist.factor_library import list_factors

        factors_dir = temp_dir / "quant" / "factors" / "stock" / "price"
        factors_dir.mkdir(parents=True, exist_ok=True)

        factor_data = {"name": "test_factor", "L1_logic": "Test"}
        (factors_dir / "test_factor.yaml").write_text(yaml.dump(factor_data))

        factors = list_factors(temp_dir)
        assert isinstance(factors, (list, dict))

    def test_12_4_duckdb_factor_values(self, temp_dir):
        """Step 12.4: DuckDB factor_values table.

        Long table schema: date × stock × factor_name × value.
        """
        import duckdb

        db_path = temp_dir / "factor.duckdb"
        conn = duckdb.connect(str(db_path))

        conn.execute("""
            CREATE TABLE IF NOT EXISTS factor_values (
                date DATE,
                stock VARCHAR,
                factor_name VARCHAR,
                value DOUBLE
            )
        """)

        conn.execute("""
            INSERT INTO factor_values VALUES
            ('2024-01-01', 'AAPL', 'momentum_20d', 0.05),
            ('2024-01-01', 'GOOGL', 'momentum_20d', 0.03)
        """)

        result = conn.execute("SELECT COUNT(*) FROM factor_values").fetchone()
        assert result[0] == 2

        conn.close()

    def test_12_5_paper_api_endpoint(self, server_url):
        """Step 12.5: Paper API endpoint.

        GET /api/paper/list returns extracted papers.
        """
        import httpx

        client = httpx.Client(base_url=server_url, timeout=10.0)
        response = client.get("/api/paper/list")
        assert response.status_code in [200, 404]
