"""UnifiedWorkflow: 论文→因子 完整流水线.

流程:
  Stage 1: 论文理解 (Flow B) — 多阶段 LLM 提取
  Stage 2: 代码生成 (Flow C) — ReAct 自修复
  Stage 3: 持久化 — 写 6 层 YAML
  Stage 4: 回测 (Flow C) — QuantNodes PipelineRunner

用法:
  config = WorkflowConfig(paper_id="test", source_type="pdf", source_ref="paper.pdf")
  workflow = UnifiedWorkflow(config)
  result = workflow.run()
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import polars as pl

logger = logging.getLogger(__name__)


# ─── 数据结构 ─────────────────────────────────────────────────


@dataclass
class WorkflowConfig:
    """流水线配置."""

    paper_id: str
    source_type: str = "pdf"          # pdf / url / raw
    source_ref: str = ""
    paper_content: str = ""
    # 回测参数
    symbol: str = "000300.SH"
    start_date: str = "2023-01-01"
    end_date: str = "2025-12-31"
    # LLM
    llm_client: Any = None
    # 控制
    use_react: bool = True
    skip_codegen: bool = False
    skip_backtest: bool = False


@dataclass
class WorkflowResult:
    """流水线结果."""

    paper_id: str
    success: bool = False
    # Stage 1
    n_signals: int = 0
    pass2_details: list[dict] = field(default_factory=list)
    # Stage 2
    n_coded: int = 0
    code_results: list[dict] = field(default_factory=list)
    # Stage 3
    written_factors: list[str] = field(default_factory=list)
    # Stage 4
    backtest_results: list[dict] = field(default_factory=list)
    # 元数据
    total_latency_ms: int = 0
    llm_calls: int = 0
    error: str | None = None


# ─── 适配器 ───────────────────────────────────────────────────


def _track_b_to_factor(detail: dict, paper_id: str) -> dict:
    """SignalDetail.to_dict() → write_factor_yaml 兼容格式."""
    from ..common.utils import generate_slug

    slug = generate_slug(detail.get("name", "unknown"))
    return {
        "name": slug,
        "factor": {
            "name": slug,
            "name_cn": (detail.get("description") or detail.get("name", ""))[:50],
            "asset_type": "stock",
            "category": "alpha",
            "subcategory": "paper_derived",
            "version": 1,
            "source_paper": paper_id,
            "status": "draft",
            "l1": detail.get("l1", {}),
            "l2": detail.get("l2", {}),
            "l3": detail.get("l3", {}),
            "l4": detail.get("l4", {}),
        },
    }


# ─── 核心类 ───────────────────────────────────────────────────


class UnifiedWorkflow:
    """论文→因子 完整流水线: 提取(B) → 代码生成(C) → 持久化 → 回测(C)."""

    def __init__(self, config: WorkflowConfig) -> None:
        self.config = config
        self.result = WorkflowResult(paper_id=config.paper_id)
        self._df_pl: pl.DataFrame | None = None

    def run(self) -> WorkflowResult:
        """执行完整流水线."""
        t0 = time.monotonic()
        try:
            self._stage1_extraction()
            if not self.config.skip_codegen:
                self._stage2_codegen()
            self._stage3_persist()
            if not self.config.skip_backtest and self.result.code_results:
                self._stage4_backtest()
            self.result.success = True
        except Exception as exc:
            self.result.error = str(exc)
            logger.error("workflow failed for %s: %s", self.config.paper_id, exc)
        self.result.total_latency_ms = int((time.monotonic() - t0) * 1000)
        return self.result

    def load_checkpoint(self, path: str) -> None:
        """从 track_b_checkpoint.json 加载, 跳过 Stage 1."""
        ckpt = Path(path)
        if not ckpt.exists():
            raise FileNotFoundError(f"checkpoint not found: {ckpt}")
        data = json.loads(ckpt.read_text(encoding="utf-8"))
        details = data.get("pass2_details", [])
        self.result.pass2_details = details
        self.result.n_signals = len(details)
        logger.info(
            "loaded checkpoint: %d signals from %s", len(details), ckpt
        )

    # ─── 内部工具 ─────────────────────────────────────────

    def _fetch_content(self) -> str:
        """读取 PDF/URL/raw 文件内容."""
        if self.config.paper_content:
            return self.config.paper_content

        from ..paper_understanding.extract_paper import _fetch_content

        return _fetch_content(
            source_ref=self.config.source_ref,
            source_type=self.config.source_type,
            paper_id=self.config.paper_id,
        )

    def _load_market_data(self) -> pl.DataFrame:
        """加载行情数据为 Polars DataFrame."""
        if self._df_pl is not None:
            return self._df_pl

        from ..data_source.router import DataRouter

        router = DataRouter(use_cache=True)
        df_pd, source = router.get(
            self.config.symbol, self.config.start_date, self.config.end_date
        )
        if df_pd is None or df_pd.empty:
            raise RuntimeError(
                f"no market data for {self.config.symbol} "
                f"({self.config.start_date} ~ {self.config.end_date})"
            )
        logger.info(
            "loaded market data: %s rows, source=%s", len(df_pd), source
        )
        self._df_pl = pl.from_pandas(df_pd)
        return self._df_pl

    def _get_llm_client(self) -> Any:
        """获取或构建 LLM 客户端."""
        if self.config.llm_client is not None:
            return self.config.llm_client
        from ..common.llm_factory import build_default_client
        return build_default_client()

    # ─── Stage 1: 论文理解 (Flow B) ──────────────────────

    def _stage1_extraction(self) -> None:
        """Flow B: 多阶段 LLM 提取."""
        logger.info("[workflow] stage1: extraction started for %s", self.config.paper_id)

        content = self._fetch_content()
        if not content:
            raise RuntimeError(f"no content for {self.config.paper_id}")

        llm = self._get_llm_client()

        # 章节检测
        from ..paper_understanding.llm_extraction.section_detector import (
            detect_sections,
        )

        sec_result = detect_sections(
            paper_id=self.config.paper_id,
            parsed_text=content,
            llm_client=llm,
        )
        sections = sec_result.sections if sec_result.success else None
        logger.info(
            "[workflow] stage1: sections detected=%s",
            len(sections) if sections else 0,
        )

        # 规划
        from ..paper_understanding.llm_extraction.planner import plan_paper

        plan = plan_paper(
            paper_id=self.config.paper_id,
            title=self.config.paper_id,
            parsed_text=content,
            sections=sections,
            llm_client=llm,
        )
        logger.info(
            "[workflow] stage1: plan schema=%s n_signals=%d conf=%.2f",
            plan.schema_choice,
            plan.n_signals_estimate,
            plan.confidence,
        )

        # Track B 提取
        from ..paper_understanding.llm_extraction.track_b import run_track_b

        track_b = run_track_b(
            paper_id=self.config.paper_id,
            parsed_text=content,
            plan=plan,
            llm_client=llm,
            run_pass2=True,
        )

        self.result.pass2_details = [d.to_dict() for d in track_b.pass2_details]
        self.result.n_signals = len(track_b.pass2_details)
        self.result.llm_calls += track_b.llm_calls
        logger.info(
            "[workflow] stage1 done: %d signals, %d pass2 complete",
            self.result.n_signals,
            track_b.n_pass2_complete,
        )

    # ─── Stage 2: 代码生成 (Flow C) ──────────────────────

    def _stage2_codegen(self) -> None:
        """Flow C: ReAct 代码生成."""
        logger.info("[workflow] stage2: codegen started")

        df_pl = self._load_market_data()
        llm = self._get_llm_client()

        from ..codegen.llm_code import SYSTEM_PROMPT_CODE, execute_code

        coded = []
        for detail in self.result.pass2_details:
            if not detail.get("success") or not detail.get("l1"):
                continue

            name = detail.get("name", "unknown")
            formula_brief = detail.get("formula_brief", "")
            if not formula_brief:
                # 尝试从 l1 获取
                formula_brief = detail.get("l1", {}).get("formula", "")

            if not formula_brief:
                logger.warning("[workflow] stage2: skipping %s (no formula_brief)", name)
                continue

            try:
                if self.config.use_react:
                    from ..codegen.react_engine import compile_to_code_react

                    react_result = compile_to_code_react(
                        factor_name=name,
                        formula_brief=formula_brief,
                        system_prompt=SYSTEM_PROMPT_CODE,
                        df=df_pl,
                        llm=llm,
                        max_repair_rounds=3,
                        temperature=0.3,
                    )
                    if react_result.is_valid:
                        # 重新执行获取 Series
                        series = execute_code(react_result.code, df_pl)
                        coded.append({
                            "name": name,
                            "code": react_result.code,
                            "formula_brief": formula_brief,
                        })
                        logger.info("[workflow] stage2: %s code OK (%d chars)", name, len(react_result.code))
                    else:
                        logger.warning("[workflow] stage2: %s codegen failed: %s", name, react_result.error_message)
                else:
                    # 1-shot fallback
                    from ..codegen.llm_code import extract_python, validate_syntax, validate_safety

                    user_prompt = (
                        f"Factor: {name}\nFormula: {formula_brief}\n\n"
                        "Write a Python function `compute_factor(df: pl.DataFrame) -> pl.Series`.\n"
                        "Output ONLY the code block."
                    )
                    messages = [
                        {"role": "system", "content": SYSTEM_PROMPT_CODE},
                        {"role": "user", "content": user_prompt},
                    ]
                    content = llm.chat(messages=messages, temperature=0.3)
                    code = extract_python(content)
                    if code:
                        syntax_ok, _ = validate_syntax(code)
                        safe_ok, _ = validate_safety(code)
                        if syntax_ok and safe_ok:
                            series = execute_code(code, df_pl)
                            coded.append({
                                "name": name,
                                "code": code,
                                "formula_brief": formula_brief,
                            })
                            logger.info("[workflow] stage2: %s code OK (1-shot)", name)
            except Exception as exc:
                logger.warning("[workflow] stage2: %s failed: %s", name, exc)

        self.result.code_results = coded
        self.result.n_coded = len(coded)
        logger.info("[workflow] stage2 done: %d coded", self.result.n_coded)

    # ─── Stage 3: 持久化 ──────────────────────────────────

    def _stage3_persist(self) -> None:
        """写 YAML 因子定义."""
        logger.info("[workflow] stage3: persist started")

        from ..persist.factor_library import write_factor_yaml

        written = []
        for detail in self.result.pass2_details:
            if not detail.get("success"):
                continue

            factor_data = _track_b_to_factor(detail, self.config.paper_id)

            # 注入代码 (如果有)
            code_entry = next(
                (c for c in self.result.code_results if c["name"] == detail.get("name")),
                None,
            )
            if code_entry:
                factor_data["factor"]["l1"]["code"] = code_entry["code"]
                factor_data["factor"]["formula_brief"] = code_entry["formula_brief"]

            try:
                write_factor_yaml(factor_data["name"], factor_data)
                written.append(factor_data["name"])
            except Exception as exc:
                logger.warning(
                    "[workflow] stage3: failed to write %s: %s",
                    factor_data["name"],
                    exc,
                )

        self.result.written_factors = written
        logger.info("[workflow] stage3 done: %d factors written", len(written))

    # ─── Stage 4: 回测 (Flow C) ──────────────────────────

    def _stage4_backtest(self) -> None:
        """Flow C: QuantNodes PipelineRunner 回测."""
        logger.info("[workflow] stage4: backtest started")

        df_pl = self._load_market_data()

        from ..codegen.llm_code import execute_code
        from ..pipeline.backtest_config import build_qn_config
        from ..pipeline.backtest_extract import extract_full_backtest_from_ctx
        from ..pipeline.data_loader import wide_from_long, write_factor_h5
        from ..pipeline.persist import persist_code_to_yaml, save_backtest_to_db

        PROJECT_ROOT = Path("/home/ll/llmwikify")
        output_dir = PROJECT_ROOT / "scripts" / "output"

        backtest_results = []
        for idx, code_entry in enumerate(self.result.code_results):
            name = code_entry["name"]
            code = code_entry["code"]
            formula_brief = code_entry["formula_brief"]

            try:
                # 执行代码获取 factor series
                series = execute_code(code, df_pl)

                # 转换为宽表并写 H5
                wide = wide_from_long(df_pl, series)
                h5_path = write_factor_h5(wide, name, output_dir)

                # 构建 QN 配置并运行
                qn_config = build_qn_config(name, h5_path, code)
                from QuantNodes.research.factor_test.pipeline_runner import (
                    PipelineRunner,
                )

                ctx = PipelineRunner.from_dict(qn_config).run()

                # 提取回测指标
                backtest = extract_full_backtest_from_ctx(ctx)

                # 持久化
                persist_code_to_yaml(
                    factor_name=name,
                    code=code,
                    formula_brief=formula_brief,
                    backtest=backtest,
                    h5_path=str(h5_path),
                    code_chars=len(code),
                )
                save_backtest_to_db(
                    slug=name.replace("-", "_"),
                    alpha_index=idx,
                    backtest=backtest,
                    start_date=self.config.start_date.replace("-", ""),
                    end_date=self.config.end_date.replace("-", ""),
                )

                backtest_results.append({"name": name, **backtest})
                logger.info(
                    "[workflow] stage4: %s backtest OK icir=%s",
                    name,
                    backtest.get("icir"),
                )
            except Exception as exc:
                logger.warning("[workflow] stage4: %s backtest failed: %s", name, exc)
                backtest_results.append({"name": name, "error": str(exc)})

        self.result.backtest_results = backtest_results
        logger.info(
            "[workflow] stage4 done: %d backtests",
            len(backtest_results),
        )
