"""LLM-driven factor metadata extraction (Phase 3, 2026-06-22).

Single LLM call extracts L2/L3/L4/L6 structured metadata from a
formula_brief + Python implementation. Mirrors the
``stage_c_e2e_smoke`` pattern (single LLM call per alpha, JSON in
markdown fence).

Output keys (matches WebUI FactorDetail.tsx contract):
  - l2.calculation_steps: [{step, description, formula}, ...]
  - l2.edge_case_handling, missing_value_handling, data_alignment, complexity
  - l3.financial_intuition, market_behavior, theoretical_basis,
    historical_effectiveness, related_factors
  - l4.hypotheses: [{id, name, description, expected_ic_sign, priority}, ...]
  - l4.meaning_summary, key_insights, uncertainty
  - l6.industry_concentration, crowding_level, failure_conditions, risk_notes

Concurrent batch:
  - 3-way parallel (api.minimaxi.com throttle limit; 6 triggers throttle)
  - sleep 0.3s between each LLM call within a worker
"""
from __future__ import annotations

import concurrent.futures
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


SYSTEM_PROMPT_METADATA = """你是量化研究助手, 负责从 alpha 公式 + Python 实现中提取 6-layer factor metadata.

给定:
  - formula_brief: 原始 alpha 公式 (来自 101 alphas paper)
  - code: LLM 生成的 polars Python 实现

输出严格的 JSON (用 ```json ... ``` 包裹), 字段如下:

```json
{
  "l2": {
    "calculation_steps": [
      {"step": 1, "description": "...", "formula": "..."},
      {"step": 2, "description": "...", "formula": "..."}
    ],
    "edge_case_handling": "...",
    "missing_value_handling": "...",
    "data_alignment": "T+1",
    "complexity": "O(T × N)"
  },
  "l3": {
    "financial_intuition": "1-2 句解释因子捕捉的市场现象",
    "market_behavior": "...",
    "theoretical_basis": "...",
    "historical_effectiveness": "...",
    "related_factors": "..."
  },
  "l4": {
    "hypotheses": [
      {
        "id": "H1",
        "name": "...",
        "description": "...",
        "expected_ic_sign": "正",
        "source": "...",
        "priority": "主假设"
      }
    ],
    "meaning_summary": "...",
    "key_insights": ["...", "..."],
    "uncertainty": "..."
  },
  "l6": {
    "industry_concentration": "...",
    "crowding_level": "...",
    "failure_conditions": "...",
    "risk_notes": "..."
  }
}
```

要求:
- calculation_steps 拆 2-5 步, 描述要具体
- hypotheses 生成 2-4 条, expected_ic_sign ∈ {正, 负, 不确定}
- financial_intuition 简洁, 不超 100 字
- failure_conditions 列出 2-3 种失效场景
- 全部中文输出 (除 JSON 字段名)
- 必须用 ```json``` 包裹输出"""


def _extract_json_from_response(text: str) -> dict | None:
    """Parse JSON from ```json ... ``` fenced block in LLM response.

    Tolerant: if no fence, try to find JSON object in text.
    """
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError as exc:
            logger.warning("[factor_extractor] fenced JSON parse failed: %s", exc)

    obj_match = re.search(r"\{[\s\S]*\}", text)
    if obj_match:
        try:
            return json.loads(obj_match.group(0))
        except json.JSONDecodeError as exc:
            logger.warning("[factor_extractor] raw JSON parse failed: %s", exc)

    return None


def extract_factor_metadata(
    llm: Any,
    formula_brief: str,
    code: str,
    temperature: float = 0.3,
    max_retries: int = 1,
) -> dict:
    """Single LLM call returns L2/L3/L4/L6 structured metadata.

    Args:
        llm: StreamableLLMClient instance.
        formula_brief: Original alpha formula text.
        code: Python implementation (polars).
        temperature: LLM sampling temperature.
        max_retries: Retry on JSON parse failure.

    Returns:
        Dict with keys: l2, l3, l4, l6 (each possibly empty dict on failure).
    """
    user_prompt = (
        f"formula_brief:\n{formula_brief}\n\n"
        f"code:\n```python\n{code[:2000]}\n```\n\n"
        "请输出 L2/L3/L4/L6 metadata 的 JSON."
    )

    last_error: str | None = None
    for attempt in range(max_retries + 1):
        try:
            response = llm.chat(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT_METADATA},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
            )
            text = response if isinstance(response, str) else str(response)
            parsed = _extract_json_from_response(text)
            if parsed is not None:
                return parsed
            last_error = "JSON parse failed"
            logger.warning("[factor_extractor] attempt %d: %s", attempt + 1, last_error)
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("[factor_extractor] attempt %d LLM error: %s", attempt + 1, last_error)
        time.sleep(0.3)

    logger.error("[factor_extractor] all attempts failed: %s", last_error)
    return {"l2": {}, "l3": {}, "l4": {}, "l6": {}, "_error": last_error}


def _build_llm_client() -> Any:
    """Build StreamableLLMClient from ~/.llmwikify/llmwikify.json."""
    config = json.loads(Path("~/.llmwikify/llmwikify.json").expanduser().read_text())
    llm_cfg = config["llm"]
    from llmwikify.foundation.llm.streamable import StreamableLLMClient
    return StreamableLLMClient(
        provider=llm_cfg.get("provider", "openai"),
        api_key=llm_cfg["api_key"],
        base_url=llm_cfg["base_url"],
        model=llm_cfg["model"],
        request_timeout_seconds=float(llm_cfg.get("timeout", 600)),
    )


def _process_one(
    alpha_index: int,
    output_dir: Path,
    max_workers: int = 1,
) -> dict:
    """Process one alpha: load JSON, extract metadata, write YAML l2-l6.

    Returns:
        {"alpha_index": int, "status": "success"|"failed", "error": str}
    """
    json_path = output_dir / f"single_factor_{alpha_index:03d}.json"
    if not json_path.exists():
        return {"alpha_index": alpha_index, "status": "failed", "error": "JSON not found"}

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        formula_brief = data.get("formula_brief", "")
        code = data.get("code", "")
        if not formula_brief or not code:
            return {
                "alpha_index": alpha_index,
                "status": "failed",
                "error": f"empty formula_brief ({len(formula_brief)}) or code ({len(code)})",
            }

        llm = _build_llm_client()
        t0 = time.monotonic()
        metadata = extract_factor_metadata(llm, formula_brief, code)
        elapsed = time.monotonic() - t0

        if not metadata or metadata.get("_error"):
            return {
                "alpha_index": alpha_index,
                "status": "failed",
                "error": metadata.get("_error", "empty metadata"),
                "elapsed_sec": round(elapsed, 2),
            }

        # Write l2-l6 back to YAML
        from llmwikify.reproduction.factor_library import (
            read_factor_yaml,
            write_factor_yaml,
        )
        slug = f"alpha_{alpha_index:03d}"
        existing = read_factor_yaml(slug)
        if existing is None:
            return {
                "alpha_index": alpha_index,
                "status": "failed",
                "error": f"YAML {slug} not found (Phase 1 must run first)",
            }
        existing.setdefault("factor", {})
        for layer_key in ("l2", "l3", "l4", "l6"):
            if layer_key in metadata and isinstance(metadata[layer_key], dict):
                existing["factor"][layer_key] = metadata[layer_key]
        action = write_factor_yaml(slug, existing)

        return {
            "alpha_index": alpha_index,
            "status": "success",
            "action": action,
            "l2_steps": len(metadata.get("l2", {}).get("calculation_steps", [])),
            "l4_hypotheses": len(metadata.get("l4", {}).get("hypotheses", [])),
            "elapsed_sec": round(elapsed, 2),
        }
    except Exception as exc:
        return {
            "alpha_index": alpha_index,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }


def extract_batch(
    alpha_indices: list[int],
    output_dir: Path | None = None,
    max_workers: int = 3,
) -> list[dict]:
    """Process multiple alphas with 3-way concurrency.

    Mirrors stage_c_e2e_smoke throttle pattern (3 concurrent, sleep 0.3s).
    """
    if output_dir is None:
        output_dir = Path("/home/ll/llmwikify/scripts/output")

    results: list[dict] = []
    t_overall = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_process_one, idx, output_dir): idx
            for idx in alpha_indices
        }
        for fut in concurrent.futures.as_completed(futures):
            idx = futures[fut]
            try:
                r = fut.result()
            except Exception as exc:
                r = {"alpha_index": idx, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}
            results.append(r)
            status = r.get("status", "?")
            err = r.get("error", "")[:80]
            print(f"  [{idx:03d}] {status} ({r.get('elapsed_sec', '?'):.1f}s) {err}")

    results.sort(key=lambda x: x.get("alpha_index", 0))
    total = time.monotonic() - t_overall
    success = sum(1 for r in results if r.get("status") == "success")
    print(f"\n[extract_batch] {success}/{len(results)} success in {total:.1f}s")
    return results


__all__ = [
    "extract_factor_metadata",
    "extract_batch",
    "_extract_json_from_response",
    "_process_one",
    "SYSTEM_PROMPT_METADATA",
]
