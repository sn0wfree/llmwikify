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

from .llm_code import build_llm_client, extract_json_from_response

logger = logging.getLogger(__name__)

# Backward-compatible aliases
_build_llm_client = build_llm_client
_extract_json_from_response = extract_json_from_response


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


SYSTEM_PROMPT_METADATA_V2 = """你是量化研究助手, 负责验证和补充 factor metadata.

给定:
  - formula_brief: 原始 alpha 公式
  - code: Python 实现
  - 已有元数据 (来自研报提取): l2, l3, l4 (可能为空)

任务:
1. 验证已有 l2/l3/l4 是否准确 (如有错误请修正)
2. 补充缺失字段
3. 新增 l6 (风险分析)

输出严格的 JSON (用 ```json ... ``` 包裹), 字段如下:

```json
{
  "verified": true,
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
- 如果已有元数据准确, 设 verified=true, 只补充缺失字段
- 如果发现错误, 修正并设 verified=false
- l6 必须新增 (Phase 1 不提取)
- calculation_steps 拆 2-5 步, 描述要具体
- hypotheses 生成 2-4 条, expected_ic_sign ∈ {正, 负, 不确定}
- financial_intuition 简洁, 不超 100 字
- failure_conditions 列出 2-3 种失效场景
- 全部中文输出 (除 JSON 字段名)
- 必须用 ```json``` 包裹输出"""


def extract_factor_metadata(
    llm: Any,
    formula_brief: str,
    code: str,
    existing_metadata: dict | None = None,
    temperature: float = 0.3,
    max_retries: int = 1,
) -> dict:
    """Single LLM call returns L2/L3/L4/L6 structured metadata.

    Args:
        llm: StreamableLLMClient instance.
        formula_brief: Original alpha formula text.
        code: Python implementation (polars).
        existing_metadata: Phase 1 output (l2/l3/l4) for verification.
        temperature: LLM sampling temperature.
        max_retries: Retry on JSON parse failure.

    Returns:
        Dict with keys: l2, l3, l4, l6 (each possibly empty dict on failure).
    """
    user_parts = [
        f"formula_brief:\n{formula_brief}\n",
        f"code:\n```python\n{code[:4000]}\n```",
    ]

    if existing_metadata:
        existing_json = json.dumps(existing_metadata, ensure_ascii=False, indent=2)
        user_parts.append(f"\n已有元数据 (来自研报提取):\n```json\n{existing_json}\n```")
        user_parts.append("\n请验证已有元数据是否准确，补充缺失字段，新增 l6。")
    else:
        user_parts.append("\n请输出 L2/L3/L4/L6 metadata 的 JSON.")

    user_prompt = "\n".join(user_parts)
    system_prompt = SYSTEM_PROMPT_METADATA_V2 if existing_metadata else SYSTEM_PROMPT_METADATA

    logger.info("[factor_extractor] extract_factor_metadata: formula_len=%d, code_len=%d, existing=%s",
               len(formula_brief), len(code), "yes" if existing_metadata else "no")

    last_error: str | None = None
    for attempt in range(max_retries + 1):
        try:
            response = llm.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
            )
            text = response if isinstance(response, str) else str(response)
            parsed = extract_json_from_response(text)
            if parsed is not None:
                logger.info("[factor_extractor] extract_factor_metadata: success, keys=%s", list(parsed.keys()))
                return parsed
            last_error = "JSON parse failed"
            logger.warning("[factor_extractor] attempt %d: %s", attempt + 1, last_error)
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("[factor_extractor] attempt %d LLM error: %s", attempt + 1, last_error)
        time.sleep(0.3)

    logger.error("[factor_extractor] all attempts failed: %s", last_error)
    return {"l2": {}, "l3": {}, "l4": {}, "l6": {}, "_error": last_error}


def _load_phase1_metadata(alpha_index: int, papers_dir: Path | None) -> dict | None:
    """Load Phase 1 (pass2.json) l2/l3/l4 metadata for a given alpha.

    Searches all track_b_pass2.json files under papers_dir and returns
    the first matching l2/l3/l4 dict, or None if not found.
    """
    if papers_dir is None:
        return None

    for pass2_path in papers_dir.rglob("track_b_pass2.json"):
        try:
            data = json.loads(pass2_path.read_text(encoding="utf-8"))
            details = data.get("pass2_details", [])
            for d in details:
                name = d.get("name", "")
                if name == f"Alpha#{alpha_index}" or d.get("index") == alpha_index:
                    result = {}
                    for key in ("l2", "l3", "l4"):
                        if key in d and isinstance(d[key], dict):
                            result[key] = {k: v for k, v in d[key].items() if v is not None}
                    return result if result else None
        except Exception:
            continue
    return None


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dicts; override values take precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _process_one(
    alpha_index: int,
    output_dir: Path,
    papers_dir: Path | None = None,
    max_workers: int = 1,
) -> dict:
    """Process one alpha: load JSON, extract metadata, write YAML l2-l6.

    Returns:
        {"alpha_index": int, "status": "success"|"failed", "error": str}
    """
    json_path = output_dir / f"single_factor_{alpha_index:03d}.json"
    if not json_path.exists():
        logger.warning("[factor_extractor] alpha-%03d: JSON not found", alpha_index)
        return {"alpha_index": alpha_index, "status": "failed", "error": "JSON not found"}

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        formula_brief = data.get("formula_brief", "")
        code = data.get("code", "")
        if not formula_brief or not code:
            logger.warning("[factor_extractor] alpha-%03d: empty formula_brief (%d) or code (%d)",
                         alpha_index, len(formula_brief), len(code))
            return {
                "alpha_index": alpha_index,
                "status": "failed",
                "error": f"empty formula_brief ({len(formula_brief)}) or code ({len(code)})",
            }

        existing_metadata = _load_phase1_metadata(alpha_index, papers_dir)
        logger.info("[factor_extractor] alpha-%03d: Phase1 metadata %s, code_len=%d",
                   alpha_index, "found" if existing_metadata else "none", len(code))

        llm = build_llm_client()
        t0 = time.monotonic()
        metadata = extract_factor_metadata(
            llm, formula_brief, code,
            existing_metadata=existing_metadata,
        )
        elapsed = time.monotonic() - t0

        if not metadata or metadata.get("_error"):
            logger.error("[factor_extractor] alpha-%03d: metadata extraction failed: %s",
                        alpha_index, metadata.get("_error", "empty metadata"))
            return {
                "alpha_index": alpha_index,
                "status": "failed",
                "error": metadata.get("_error", "empty metadata"),
                "elapsed_sec": round(elapsed, 2),
            }

        from llmwikify.reproduction.factor_library import (
            read_factor_yaml,
            write_factor_yaml,
        )
        slug = f"alpha_{alpha_index:03d}"
        existing = read_factor_yaml(slug)
        if existing is None:
            logger.error("[factor_extractor] alpha-%03d: YAML %s not found", alpha_index, slug)
            return {
                "alpha_index": alpha_index,
                "status": "failed",
                "error": f"YAML {slug} not found (Phase 1 must run first)",
            }
        existing.setdefault("factor", {})
        for layer_key in ("l2", "l3", "l4", "l6"):
            if layer_key in metadata and isinstance(metadata[layer_key], dict):
                existing_layer = existing["factor"].get(layer_key, {})
                merged = _deep_merge(existing_layer, metadata[layer_key])
                existing["factor"][layer_key] = merged
        action = write_factor_yaml(slug, existing)

        logger.info("[factor_extractor] alpha-%03d: success (%.1fs), verified=%s, l2_steps=%d, l4_hypotheses=%d",
                   alpha_index, elapsed, metadata.get("verified", False),
                   len(metadata.get("l2", {}).get("calculation_steps", [])),
                   len(metadata.get("l4", {}).get("hypotheses", [])))

        return {
            "alpha_index": alpha_index,
            "status": "success",
            "verified": metadata.get("verified", False),
            "action": action,
            "l2_steps": len(metadata.get("l2", {}).get("calculation_steps", [])),
            "l4_hypotheses": len(metadata.get("l4", {}).get("hypotheses", [])),
            "elapsed_sec": round(elapsed, 2),
        }
    except Exception as exc:
        logger.error("[factor_extractor] alpha-%03d: exception: %s", alpha_index, exc)
        return {
            "alpha_index": alpha_index,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }


def extract_batch(
    alpha_indices: list[int],
    output_dir: Path | None = None,
    papers_dir: Path | None = None,
    max_workers: int = 3,
    batch_size: int = 3,
) -> list[dict]:
    """Process alphas in small batches to avoid overwhelming the LLM API.

    Each batch submits at most ``batch_size`` concurrent requests,
    waits for all to complete, then moves to the next batch.
    """
    if output_dir is None:
        output_dir = Path("/home/ll/llmwikify/scripts/output")

    total = len(alpha_indices)
    print(f"  [extract_batch] {total} alphas, batch_size={batch_size}")

    results: list[dict] = []
    t_overall = time.monotonic()
    for batch_start in range(0, total, batch_size):
        batch = alpha_indices[batch_start:batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        total_batches = (total + batch_size - 1) // batch_size
        print(f"  [batch {batch_num}/{total_batches}] alphas {batch[0]:03d}-{batch[-1]:03d}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as pool:
            futures = {
                pool.submit(_process_one, idx, output_dir, papers_dir): idx
                for idx in batch
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
                elapsed = r.get("elapsed_sec", 0)
                print(f"    [{idx:03d}] {status} ({elapsed:.1f}s) {err}")

    results.sort(key=lambda x: x.get("alpha_index", 0))
    total_elapsed = time.monotonic() - t_overall
    success = sum(1 for r in results if r.get("status") == "success")
    print(f"  [extract_batch] {success}/{total} success in {total_elapsed:.1f}s ({total_elapsed / total:.1f}s avg)")
    return results


__all__ = [
    "extract_factor_metadata",
    "extract_batch",
    "_process_one",
    "_load_phase1_metadata",
    "_deep_merge",
    "SYSTEM_PROMPT_METADATA",
    "SYSTEM_PROMPT_METADATA_V2",
]
