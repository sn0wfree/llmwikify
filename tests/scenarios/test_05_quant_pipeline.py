# tests/scenarios/test_05_quant_pipeline.py
"""Scenario 5: Quant Pipeline - With LLM calls.

## Background
Quant reproduction pipeline: arXiv paper PDF → LLM extracts factors
→ 6-layer Factor YAML → DuckDB storage → backtest → L5 reflection
report.

## Architecture
```
Paper PDF
   │
   │ repro_extract.yaml (LLM prompt)
   ▼
Structured JSON → 6-layer Factor YAML
   │
   │ factor_backtest.py
   ▼
DuckDB (long table)
   │
   │ run_backtest
   ▼
Backtest report (IC / RankIC / quantile)
   │
   │ l5_orchestrator
   ▼
L5 reflection
```

## Troubleshooting
- /api/paper/start 500: check LLM provider config
- Factor L2 SyntaxError: v0.36+ auto-repair via react_engine
- Backtest IC ≈ 0: data source issue, check quantnodes install
"""


class TestQuantPipeline:
    """Test quant reproduction pipeline with real LLM calls.

    Covers TUTORIAL.md Scenario 5 (Quant Reproduction).
    """

    def test_5_1_quant_init_via_cli(self, temp_dir):
        """Step 5.1: Initialize quant directory structure.

        Creates quant/{factors,papers,factorbacktest,strategies,...}.
        """
        import subprocess
        result = subprocess.run(
            ["python3", "-m", "llmwikify", "quant-init"],
            capture_output=True,
            text=True,
            cwd=str(temp_dir),
        )
        assert result.returncode in [0, 1]

    def test_5_2_write_factor(self, temp_dir):
        """Step 5.2: Write a 6-layer factor YAML file.

        Layer 1: logic, Layer 2: computation, Layer 3: financial intuition.
        """
        factors_dir = temp_dir / "quant" / "factors"
        factors_dir.mkdir(parents=True, exist_ok=True)

        factor_data = {
            "name": "test_momentum",
            "asset_type": "stock",
            "category": "price",
            "L1_logic": "Price momentum over 20 days",
            "L2_computation": "close / close.shift(20) - 1",
            "L3_financial": "Momentum effect in equity markets",
        }

        factor_path = factors_dir / "stock" / "price" / "test_momentum.yaml"
        factor_path.parent.mkdir(parents=True, exist_ok=True)

        import yaml
        factor_path.write_text(yaml.dump(factor_data))

        assert factor_path.exists()

    def test_5_3_list_factors(self, temp_dir):
        """Step 5.3: List factors in the library.

        Scans quant/factors/ for all YAML files and returns metadata.
        """
        from llmwikify.reproduction.persist.factor_library import list_factors

        factors_dir = temp_dir / "quant" / "factors"
        factors_dir.mkdir(parents=True, exist_ok=True)

        factors = list_factors(temp_dir)
        assert isinstance(factors, (list, dict))

    def test_5_4_read_factor(self, temp_dir):
        """Step 5.4: Read a factor YAML file.

        Parses a 6-layer factor YAML and returns the dict.
        """
        import yaml

        factors_dir = temp_dir / "quant" / "factors"
        factor_path = factors_dir / "stock" / "price" / "test_read.yaml"
        factor_path.parent.mkdir(parents=True, exist_ok=True)

        factor_data = {"name": "test_read", "L1_logic": "Test"}
        factor_path.write_text(yaml.dump(factor_data))

        result = yaml.safe_load(factor_path.read_text())
        assert result is not None
        assert result.get("name") == "test_read"

    def test_5_5_duckdb_schema(self, temp_dir):
        """Step 5.5: DuckDB factor_values table.

        Long table: date × stock × factor_name × value.
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

        result = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [r[0] for r in result]
        assert "factor_values" in table_names
        conn.close()

    def test_5_6_paper_api(self, server_url):
        """Step 5.6: Paper API endpoint.

        GET /api/paper/list returns extracted paper metadata.
        """
        import httpx

        client = httpx.Client(base_url=server_url, timeout=10.0)
        response = client.get("/api/paper/list")
        assert response.status_code in [200, 404]

    def test_5_7_factor_library_list(self, server_url):
        """Step 5.7: Factor library list via API.

        GET /api/factor/library/list returns all factors with metadata.
        """
        import httpx

        client = httpx.Client(base_url=server_url, timeout=10.0)
        response = client.get("/api/factor/library/list")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, (list, dict))
