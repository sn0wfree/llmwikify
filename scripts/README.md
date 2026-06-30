# Scripts

Standalone scripts for the llmwikify project.

> **Note:** These scripts are utilities, not part of the runtime. They run from the project root
> and add `src/` to `sys.path` so they can `import llmwikify.*`.

---

## Available Scripts

## Available Scripts

| Script | Purpose | Needs LLM? |
|---|---|---|
| `check_architecture.py` | Verify 4-layer architecture contracts | No |
| `check_prompt_principles.py` | Validate prompt design principles | No |
| `eval_prompts.py` | Offline prompt template evaluation | No |
| `smoke_v036.py` | v0.36 AgentChat hardening — real-LLM smoke | **Yes** |
| `smoke_v037.py` | v0.37 Triple ReAct Loop — real-LLM smoke | **Yes** |
| `migrate_db_v1_to_v2.py` | DB schema migration helper | No |
| `migrate_autoresearch_v3_to_v4.py` | AutoResearch migration helper | No |
| `migrate_factors.py` | 迁移因子到新目录结构 | No |
| `migrate_wiki_paths.py` | 迁移 Wiki 目录结构（旧 → 新 layout） | No |
| `repair_corrupted_ppt_task.py` | PPT task repair | No |
| `fix_swot_slide.py` | SWOT slide fix | No |
| `downgrade_to_v11513.sh` | Downgrade opencode to v1.15.13 (fix SPA 500 bug) | No |
| `install_opencode_fast.sh` | OpenCode 安装（加速 + mirror + SHA256 校验） | No |
| `install_opencode_manual.sh` | OpenCode 安装（本地 binary） | No |

### Quant reproduction (paper → factor → backtest)

| Script | Purpose | Needs LLM? |
|---|---|---|
| `run_paper.py` | 通用论文复现入口（modular framework） | **Yes** |
| `run_101_alphas.py` | 101 alphas 批量跑（v1 入口） | **Yes** |
| `run_101_alphas_v2.py` | 101 alphas 批量跑（v2 recipe-based 重构） | **Yes** |
| `aggregate_alpha_results.py` | 聚合 101 alphas E2E 结果为 summary | No |
| `analyze_alpha_results.py` | 分析 101 alphas 结果并生成报告 | No |
| `compare_old_vs_new.py` | 对比 react_engine vs unified codegen 结果 | No |
| `merge_alpha_data.py` | 合并 alpha_*.yaml L5 data → 101_alphas family | No |
| `test_one_factor_llm_code.py` | 单因子 LLM code 路径 + QuantNodes e2e | **Yes** |
| `fix_definition_from_pass2.py` | 用 pass2.json 的 NL 描述覆盖 l1.definition | No |

### Cross-validation (factor_backtest vs 外部库)

| Script | Purpose | Needs LLM? |
|---|---|---|
| `cross_validate_factor.py` | 严格对齐 server 算法分步交叉验证 | No |
| `validate_alphalens.py` | factor_backtest vs Alphalens 行业标准库 | No |
| `validate_backtrader.py` | momentum long-short 策略 vs Backtrader | No |
| `validate_qn_nodes.py` | 聚焦分组逻辑 vs QuantNodes | No |
| `convert_long_to_h5.py` | HS300 长格式 CSV → QuantNodes 宽格式 H5 | No |
| `deep_compare_alphalens.py` | factor_backtest vs Alphalens 位级对比 | No |

### Demo / Debug

| Script | Purpose | Needs LLM? |
|---|---|---|
| `demo_react_self_repair.py` | ReAct self-repair demo（LLM typo 自动修复） | **Yes** |
| `stage_c_debug_llm.py` | 阶段 C.2 — 调试 LLM 原始输出 | **Yes** |
| `stage_c_e2e_smoke.py` | 阶段 C — 真实 LLM 端到端 1-3 个 alpha 验证 | **Yes** |

---

## Smoke Scripts (v0.36 / v0.37)

Real-LLM smoke tests for release validation. They are **out-of-band** of the regular pytest
suite because they require:

- A working LLM provider (OpenAI, Anthropic, or local Ollama)
- Network access to the provider's API
- Approximately 2–5 minutes of wall time per script

### Usage

```bash
# Set provider credentials
export OPENAI_API_KEY=sk-...
# or
export ANTHROPIC_API_KEY=sk-ant-...

# Run smoke
python scripts/smoke_v036.py
python scripts/smoke_v037.py
```

### What they do

Each script runs a series of scenarios against a freshly started AgentChat stack. Each scenario:

1. Starts a session
2. Sends a message that exercises a specific v0.36/v0.37 capability
3. Asserts on the SSE stream events
4. Cleans up (closes session, deletes DB rows)

Results are printed as a table and exit code 0 indicates all scenarios passed.

### What they DO NOT do

- Replace unit tests — they are *additional* coverage
- Replace manual UX testing — they verify behavior, not feel
- Run in CI by default — they are release-time only (see `.github/workflows/` if added later)

### When to run

- Before tagging a release (`v0.36.0`, `v0.37.0`, ...)
- After any change to:
  - `apps/chat/agent/*` (ChatService, ChatReActBridge)
  - `apps/chat/base.py` (aask_with_tools)
  - `apps/chat/engine.py` (ResearchEngine)
  - `kernel/llm/*` (LLM provider)
  - `interfaces/server/middleware.py` (rate limit)

### Skipping gracefully

If no API key is found, the script prints a warning and exits with code 0 (so CI without
keys does not break). Set `SMOKE_REQUIRE_KEY=1` to require a key.

---

## Adding a new smoke scenario

For each new release, scenarios should follow this template:

```python
async def s_<name>(ctx: SmokeContext) -> SmokeResult:
    """Short one-line description."""
    # 1. Setup (session, messages)
    # 2. Send / interact
    # 3. Assert on stream events
    # 4. Return result
    return SmokeResult(passed=True, details="...")
```

Register in `SMOKE_SCENARIOS = [...]` at the bottom of the script.

---

## See also

- `docs/designs/v0.36-agentchat-hardening.md` — Phase 6 + Phase 7 (smoke) spec
- `docs/designs/v0.37-react-loop.md` — v0.37 smoke spec
- `docs/releases/v0.36.0.md` — Smoke results (when present)
- `docs/releases/v0.37.0.md` — Smoke results (when present)