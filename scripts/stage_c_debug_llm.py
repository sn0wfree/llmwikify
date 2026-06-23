"""阶段 C.2: 调试 LLM 原始输出。

调一次 FactorCompiler 但禁用 extract 看 LLM 实际输出。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)
os.environ.pop("FACTOR_COMPILER_MOCK", None)

from llmwikify.reproduction.ast_compiler import CompileError, compile_ast
from llmwikify.reproduction.ast_extractor import extract_ast
from llmwikify.reproduction.factor_compiler import (
    SYSTEM_PROMPT,
    FactorCompiler,
)


def main() -> None:
    track_b_path = ROOT / "quant" / "papers" / "101_alphas_minimal" / "track_b_checkpoint.json"
    with track_b_path.open(encoding="utf-8") as f:
        track_b = json.load(f)
    sig = track_b["pass1_signals"][0]
    print(f"Alpha#1 formula: {sig['formula_brief']}\n")

    compiler = FactorCompiler()
    factor_data = {
        "name": "alpha_001",
        "asset_type": "stock",
        "category": "formulaic",
        "source_paper": "101_alphas_minimal",
        "l1": {
            "definition": sig["formula_brief"][:200],
            "formula": sig["formula_brief"],
            "input_columns": ["open", "high", "low", "close", "volume", "returns", "vwap"],
            "default_params": {},
        },
        "l2": {"calculation_steps": [{"step": 1, "description": sig["formula_brief"][:200]}]},
        "l3": {},
        "l4": {},
        "l5": {"ast": None, "ast_compile_status": "pending"},
    }
    user_prompt = compiler._build_user_prompt(factor_data)
    print("=== USER PROMPT ===")
    print(user_prompt[:800])
    print("\n=== SYSTEM_PROMPT (first 500 chars) ===")
    print(SYSTEM_PROMPT[:500])

    # Call LLM directly (1 sample)
    print("\n=== Calling LLM... ===")
    response = compiler.llm.chat(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.5,
        max_tokens=1500,
    )
    content = response if isinstance(response, str) else (
        response.content if hasattr(response, "content") else str(response)
    )
    print("=== RAW LLM OUTPUT (first 1500 chars) ===")
    print(content[:1500])

    print("\n=== EXTRACT AST ===")
    ast = extract_ast(content)
    print(f"extracted: {ast}")

    print("\n=== COMPILE AST ===")
    if ast:
        try:
            expr = compile_ast(ast)
            print(f"compiled: {expr}")
        except CompileError as exc:
            print(f"compile error: {exc.kind}: {exc.message}")


if __name__ == "__main__":
    main()
