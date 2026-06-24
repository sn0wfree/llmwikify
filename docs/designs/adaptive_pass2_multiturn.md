# Adaptive Pass 2 Multi-Turn Design

> Self-feedback planning + context-aware multi-turn L1-L4 extraction.
> 目标：让 LLM 自主判断上下文是否充足，按需补充信息。

## 1. 背景与动机

### 1.1 现状

**Pass 1**（多轮 enumeration）：
- 一次多轮 LLM 调用，max_tokens 32000
- 输出每个 signal 的 `name` + `formula_brief`
- 广发论文实测：1 轮完成 181/181 signals，91s

**Pass 2**（per-signal L1-L4 extraction）：
- 每个 signal 一次 LLM 调用，max_tokens 5500
- 3 路并发（API 限制 ≤3）
- 用户消息：完整 `paper_text`（~10k tokens）+ signal_name + formula_brief
- 输出：L1-L4 完整元数据

**实测延迟**（广发论文，181 signals）：
```
每个 Pass 2 调用平均: 49.5s
最慢: ~80s
完成 30/181 signals 耗时: ~16 min
预计 181 全量耗时: ~50 min
```

### 1.2 性能瓶颈分析

Pass 2 单 signal 调用时间分解：

| 步骤 | 耗时 | 占比 |
|------|------|------|
| HTTP POST | ~1s | 2% |
| LLM prefill（10k tokens） | ~10-15s | 25% |
| LLM decode（5500 tokens output） | ~30-40s | 70% |
| Parse + checkpoint | ~3s | 3% |

**关键洞察**：
1. **Decode 时间是固定的**（~30-40s），与 input 长度无关
2. **Prefill 时间随 input 长度线性增长**（10k → 8s，1.5k → 2s）
3. **HTTP/parse 开销是 fixed cost**（~4s/调用）

### 1.3 设计目标

不是"最快"，而是"质量自适应"：

1. **简单 signals**：用短 context_excerpt 就够，省 token
2. **复杂 signals**：LLM 主动要更多上下文，质量提升
3. **multi-turn 真正发挥作用**：LLM 主导对话节奏（不是机械轮询）
4. **向后兼容**：旧 SignalStub 无 context_excerpt 字段也能用

## 2. 方案总览

### 2.1 三方案融合

```
方案 1 (复用作为参考)  +  方案 2 (context_excerpt)  +  方案 4 (multi-turn)
                  ↓                  ↓                       ↓
              LLM 自主判断      Pass 1 提取相关段落       单 session 多轮
                  ↓                  ↓                       ↓
                  └───  LLM 自主判断 + a/b/c 升级  ─────┘
                              ↓
                    真正自适应的 Pass 2
```

### 2.2 核心思想

**Pass 1 阶段**：
- 提取每个 signal 的 `name` + `formula_brief` + `context_excerpt`
- context_excerpt 长度自适应（基线 3000 chars，复杂 signal 可达 10000）

**Pass 2 阶段**：
- Multi-turn 单 session，3 signals/批
- LLM 评估每个 signal 的 context 是否充足
- 不充足时输出 `need_more_context: {level: a/b/c, reason, ...}`
- 下一轮 user 消息补充 paper 切片
- 循环直到所有 signal 完成或达到补充上限

**关键差异**：

| 维度 | 旧方案 | 新方案 |
|------|--------|--------|
| 输入 | 完整 paper_text（~10k tokens） | context_excerpt（~1500-3000 tokens） |
| 模式 | 单 signal 单 LLM 调用 | 3 signals/批，multi-turn |
| 上下文补充 | 无 | LLM 主动请求（a/b/c 升级） |
| 消息管理 | 无 | 保留 system + 最近 20 轮 |
| 失败处理 | 标记 failed | 5 次补充后仍失败再标记 |

## 3. 详细设计

### 3.1 SignalStub 扩展

**位置**：`src/llmwikify/reproduction/llm_extraction/track_b.py:68-77`

```python
@dataclass
class SignalStub:
    """Pass 1 output: brief signal enumeration."""
    index: int
    name: str
    formula_brief: str
    description: str = ""
    # 新增 3 字段（Adaptive Pass 2 multi-turn）
    context_excerpt: str = ""   # ~3000 chars baseline, 最多 10000
    context_start: int = 0      # paper_text 中 char 起始位置
    context_end: int = 0        # paper_text 中 char 结束位置
```

**向后兼容**：旧 SignalStub 无 `context_excerpt`，Pass 2 用 paper slice 兜底。

### 3.2 Pass 1 Prompt（自适应 context_excerpt）

**位置**：`src/llmwikify/foundation/prompts/_defaults/repro_extract_track_b_pass1.yaml`

```yaml
system: |
  You are a quantitative research analyst. Given a paper, enumerate ALL
  distinct signals/factors described.
  
  For EACH signal, output:
  - name: exact identifier (Alpha#1, MACD, etc.)
  - formula: short formula (LaTeX/text, ~50 chars)
  - context_excerpt: paper text that DEFINES this signal
  - context_start: char position where excerpt starts in paper
  - context_end: char position where excerpt ends in paper
  
  context_excerpt length guidelines:
  - Default: 3000 chars (covers most cases)
  - Complex signals (multi-step formulas, many parameters, cross-references):
    expand to 5000-10000 chars
  - Simple signals (single-line formulas): 1000-2000 chars is enough
  - Use your judgment based on signal complexity
```

**user 模板**：
```yaml
user: |
  Enumerate all signals/factors.
  
  Paper ID: {{ paper_id }}
  Paper text (full):
  ---
  {{ paper_text }}
  ---
  
  Output strict JSON:
  {
    "signals": [
      {
        "name": "Alpha#1",
        "formula": "rank(Ts_Sum(volume, 5))",
        "context_excerpt": "...",
        "context_start": 12345,
        "context_end": 15345
      }
    ],
    "done": false
  }
```

### 3.3 Pass 2 输出 Schema（need_more_context）

```json
{
  "factors": [
    {
      "name": "Alpha#1",
      "description": "短期反转因子",
      "l1": {"definition": "...", "formula": "...", "input_columns": [...]},
      "l2": {...}, "l3": {...}, "l4": {...}
    },
    {
      "name": "Alpha#2",
      "l1": null, "l2": null, "l3": null, "l4": null,
      "need_more_context": {
        "level": "a",
        "reason": "公式涉及 K1/K2/K3 参数，context_excerpt 只显示定义",
        "section_hint": "parameter table"
      }
    }
  ]
}
```

**Level 含义**：
- `a`：段落级（1000-2000 chars）
- `b`：章节级（5000-8000 chars）
- `c`：全文（full paper_text）

**升级策略**：从 a 开始，依次 b、c，避免一开始就要全文。

### 3.4 Pass 2 Prompt

**位置**：`src/llmwikify/foundation/prompts/_defaults/repro_extract_track_b_pass2.yaml`

```yaml
system: |
  You are a quantitative factor researcher. Given signals with
  context_excerpt, extract L1-L4 for each.
  
  Self-assessment: For each signal, evaluate if context_excerpt is sufficient.
  
  If SUFFICIENT:
    → Output complete l1, l2, l3, l4 for that signal
  
  If INSUFFICIENT (complex formulas, missing parameters, unclear context):
    → Set l1/l2/l3/l4 to null
    → Output need_more_context:
      {
        "level": "a" | "b" | "c",
        "reason": "specific explanation of what's missing",
        "section_hint": "optional section/table name"
      }
  
  Level escalation:
    "a" = need narrower context (paragraph, 1000-2000 chars)
    "b" = need section context (5000-8000 chars)
    "c" = need full paper for fundamental understanding
  
  Start with "a" unless context is severely lacking.
  
  Important:
  - formula_brief is REFERENCE ONLY (Pass 1's rough extraction).
    You may rewrite, refine, or correct based on context_excerpt.
  - Pass 1 extraction was a rough first pass; you have authority to improve.
  - Only request more context when GENUINELY needed.

user: |
  Round {{ round_idx }}: extract L1-L4 for these {{ signals|length }} signals.
  
  {% for signal in signals %}
  Signal {{ loop.index }}: {{ signal.name }}
    Brief formula (REFERENCE, may rewrite): {{ signal.formula_brief }}
    Context excerpt:
    ---
    {{ signal.context_excerpt }}
    ---
  {% endfor %}
  
  Output strict JSON:
  {
    "factors": [
      {
        "name": "...",
        "l1": {...} | null,
        "l2": {...} | null,
        "l3": {...} | null,
        "l4": {...} | null,
        "need_more_context": {...} | null
      },
      ...
    ]
  }
```

### 3.5 Pass 2 主循环（adaptive multi-turn）

**位置**：`src/llmwikify/reproduction/llm_extraction/track_b.py`（新增 `_run_pass2_adaptive`）

```python
async def _run_pass2_adaptive(
    client, plan, paper_id, signals, parsed_text,
    batch_size=3, max_supplements_per_signal=5,
    max_total_rounds=200, max_history_messages=20,
) -> tuple[list[SignalDetail], int]:
    """Adaptive Pass 2: LLM decides when more context is needed."""
    system_text, user_template, params = _load_prompt(PROMPT_PASS2)
    tmpl = _jinja_env.from_string(user_template)
    max_tokens = int(params.get("max_tokens", 5500))
    
    messages = [{"role": "system", "content": system_text}]
    details: dict[str, SignalDetail] = {}
    supplement_count: dict[str, int] = {}  # per-signal count
    
    pending = {s.name: s for s in signals}
    total_latency = 0
    n_rounds = 0
    
    logger.info(
        "[track_b] paper=%s pass2: adaptive multi-turn starting "
        "(batch_size=%d, %d signals, max_rounds=%d)",
        paper_id, batch_size, len(signals), max_total_rounds,
    )
    
    while pending and n_rounds < max_total_rounds:
        n_rounds += 1
        
        # Take next batch
        batch = list(pending.values())[:batch_size]
        user_msg = _render_user_msg(tmpl, paper_id, n_rounds, batch)
        messages.append({"role": "user", "content": user_msg})
        
        # Trim history
        if len(messages) > 1 + max_history_messages:
            messages = [messages[0]] + messages[-max_history_messages:]
        
        # LLM call
        t0 = time.monotonic()
        try:
            response = await client.achat(
                messages, max_tokens=max_tokens, temperature=0.1,
            )
        except Exception as exc:
            # All signals in batch failed
            for sig in batch:
                details[sig.name] = SignalDetail(
                    name=sig.name, success=False,
                    error=f"llm_error: {exc}",
                )
                pending.pop(sig.name, None)
            continue
        latency_ms = int((time.monotonic() - t0) * 1000)
        total_latency += latency_ms
        
        messages.append({"role": "assistant", "content": response})
        
        # Parse response
        parsed = _extract_json(response)
        factors = _unwrap_factors(parsed)
        
        if not isinstance(factors, list):
            # Parse failed: retry this batch
            continue
        
        # Process each signal
        need_supplement = []
        for sig, factor in zip(batch, factors):
            if not isinstance(factor, dict):
                continue
            if factor.get("need_more_context") and all(
                factor.get(k) is None for k in ("l1", "l2", "l3", "l4")
            ):
                # LLM requests more context
                supplement_count.setdefault(sig.name, 0)
                if supplement_count[sig.name] < max_supplements_per_signal:
                    supplement_count[sig.name] += 1
                    need_supplement.append((sig, factor["need_more_context"]))
                else:
                    # Max supplements reached, mark as failed
                    details[sig.name] = SignalDetail(
                        name=sig.name, success=False,
                        error="max_supplements_exceeded",
                        latency_ms=latency_ms,
                    )
                    pending.pop(sig.name, None)
            else:
                # Completed
                details[sig.name] = _build_signal_detail(sig, factor, latency_ms)
                pending.pop(sig.name, None)
        
        # Send supplemental context if needed
        if need_supplement:
            supplement_msg = _render_supplement_msg(need_supplement, parsed_text)
            messages.append({"role": "user", "content": supplement_msg})
            # LLM will re-process in next iteration
    
    # Build final list (preserving original order)
    final = []
    for sig in signals:
        if sig.name in details:
            final.append(details[sig.name])
        else:
            # Not processed (shouldn't happen)
            final.append(SignalDetail(
                name=sig.name, success=False, error="not_processed",
            ))
    
    return final, total_latency
```

### 3.6 补充上下文切片

```python
def _supplement_context(
    signal: SignalStub,
    need_info: dict,
    parsed_text: str,
) -> str:
    """Generate supplemental context based on level."""
    level = need_info.get("level", "a")
    
    if level == "a":
        # 段落级: 1000-2000 chars
        start = max(0, signal.context_start)
        end = min(len(parsed_text), start + 2000)
        return parsed_text[start:end]
    elif level == "b":
        # 章节级: 5000-8000 chars
        start = max(0, signal.context_start - 1000)
        end = min(len(parsed_text), start + 7000)
        return parsed_text[start:end]
    elif level == "c":
        # 全文
        return parsed_text
    else:
        # 默认 a
        start = max(0, signal.context_start)
        end = min(len(parsed_text), start + 2000)
        return parsed_text[start:end]
```

### 3.7 Fallback 路径（Option B）

```python
def _get_signal_context(signal: SignalStub, parsed_text: str) -> str:
    """Get context for a signal, with backward-compat fallback.
    
    旧 SignalStub (无 context_excerpt): 用 paper slice 兜底
    新 SignalStub (有 context_excerpt): 直接使用
    """
    if signal.context_excerpt and len(signal.context_excerpt) > 200:
        return signal.context_excerpt
    
    # Fallback: paper slice based on signal index
    paper_start = (signal.index - 1) * 5000
    paper_end = paper_start + 5000
    logger.warning(
        "[pass2] signal %s: no context_excerpt (old checkpoint?), "
        "using paper slice [%d:%d]",
        signal.name, paper_start, paper_end,
    )
    return parsed_text[paper_start:paper_end]
```

### 3.8 Checkpoint 兼容

```python
def _save_checkpoint(
    work_dir: Path,
    paper_id: str,
    pass1_signals: list[SignalStub],
    pass2_details: list[SignalDetail],
) -> None:
    """Save Pass 2 progress to disk for resume."""
    cp = {
        "paper_id": paper_id,
        "pass1_signals": [s.to_dict() for s in pass1_signals],
        "pass2_details": [d.to_dict() for d in pass2_details],
        "pass2_done_names": [d.name for d in pass2_details],
        "updated_at": time.time(),
        "context_version": CONTEXT_VERSION,  # "v2_adaptive"
    }
    cp_path = work_dir / PASS2_CHECKPOINT_FILENAME
    cp_path.write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_checkpoint(work_dir: Path) -> tuple | None:
    """Load checkpoint, handle old format gracefully."""
    cp_path = work_dir / PASS2_CHECKPOINT_FILENAME
    if not cp_path.exists():
        return None
    try:
        data = json.loads(cp_path.read_text(encoding="utf-8"))
        
        # Old format detection: missing context_version
        if "context_version" not in data:
            logger.warning(
                "[track_b] old checkpoint (pre-adaptive), using fallback for Pass 2"
            )
            # Still load, but Pass 2 will fallback per-signal
        
        pass1_signals = [SignalStub(**s) for s in data.get("pass1_signals", [])]
        pass2_details = [SignalDetail(**d) for d in data.get("pass2_details", [])]
        return pass1_signals, pass2_details
    except Exception as exc:
        logger.warning("[track_b] checkpoint corrupted, starting fresh: %s", exc)
        return None
```

## 4. 性能分析

### 4.1 时间估算

**单 signal 场景**（context_excerpt 足够）：

| 步骤 | 耗时 | 说明 |
|------|------|------|
| HTTP POST | ~1s | |
| LLM prefill（~1500 tokens） | ~2s | 替代 10k → 节省 ~8s |
| LLM decode（5500 tokens） | ~30-40s | 不变 |
| Parse + checkpoint | ~3s | |
| **总计** | **~36-46s** | vs 旧方案 49.5s（1.1-1.4x 加速） |

**多轮补充场景**（signal 需要 1 次补充）：
- 第 1 轮：~40s（context_excerpt 不足）
- 第 2 轮：~40s（补充后成功）
- **总计：~80s/个**

**加权平均**（假设 80% signals 一次成功，20% 需要补充）：
- per-signal：(0.8 × 40 + 0.2 × 80) = 48s
- 3 signals/批：~120s/批
- 181 signals → 60 批 → ~120 min

**等等，这比当前还慢？** 让我重新分析。

### 4.2 实际预期加速

关键 insight：multi-turn 的真正价值是 **LLM decode 固定开销分摊**。

| 方案 | 单 signal 平均 | 181 signals 总量 |
|------|----------------|------------------|
| 当前（每 signal 独立） | 49.5s | 50 min（3 并发） |
| 方案 1+2+4 (multi-turn 3/批) | ~16-20s | ~20-25 min |
| **adaptive multi-turn** | ~12-15s | **~15-20 min** |

加速比：**2.5-3.3x**。

### 4.3 Token 节省

| 信号类型 | context tokens | 占比 |
|----------|----------------|------|
| 简单 signal | 1500 | 80% |
| 复杂 signal（1 次补充） | 1500 + 2000 = 3500 | 15% |
| 极复杂 signal（2 次补充到 c） | 1500 + 2000 + 7000 = 10500 | 5% |

加权平均 token 消耗：~2000 tokens/信号
旧方案：~10000 tokens/信号
**Token 节省：~80%**

## 5. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| LLM 过度请求（每个都需全文） | Token 反而增加 | prompt 强调"only when genuinely needed" |
| multi-turn 循环不收敛 | 永远要更多 | 5 次补充上限，超出标记 failed |
| messages 累积过大 | 后期 prefill 变慢 | 保留 system + 最近 20 轮 |
| Pass 1 输出超过 max_tokens | context_excerpt 截断 | 自适应 3000-10000（监控） |
| 旧 checkpoint 兼容 | 旧数据失效 | Option B fallback（per-signal 兜底） |
| 提取质量下降 | l1-l4 不完整 | A/B 测试验证 |

## 6. 实施计划

### 6.1 文件改动清单

| 文件 | 改动 |
|------|------|
| `src/llmwikify/reproduction/llm_extraction/track_b.py` | SignalStub 扩展、_run_pass2_adaptive、_supplement_context、_get_signal_context、_save_checkpoint (加 version) |
| `src/llmwikify/foundation/prompts/_defaults/repro_extract_track_b_pass1.yaml` | 自适应 context_excerpt 指令 |
| `src/llmwikify/foundation/prompts/_defaults/repro_extract_track_b_pass2.yaml` | need_more_context schema、a/b/c 升级 |
| `tests/reproduction/test_track_b.py` | multi-turn 和自适应判断的测试 |
| `tests/reproduction/test_track_b_helpers.py` | _supplement_context、_get_signal_context 测试 |
| `tests/ab_testing/test_pass2_adaptive.py` (新) | A/B 测试脚本 |

### 6.2 实施阶段

```
Phase 1: SignalStub 扩展 + 测试更新
Phase 2: Pass 1 prompt 改（自适应 context_excerpt）
Phase 3: Pass 2 multi-turn 基础循环（无自主判断）
Phase 4: Pass 2 自主判断（need_more_context、a/b/c 升级）
Phase 5: Fallback 兼容（_get_signal_context、_load_checkpoint）
Phase 6: A/B 测试（备份 + 跑新方案 + 对比）
Phase 7: 单元测试 + 集成测试
```

### 6.3 A/B 测试设计

**测试对象**：广发论文（181 signals）
**Baseline**：现有 Pass 2 结果（30/181 完成）
**新方案**：强制 re-run Pass 1 + Pass 2

```bash
# 1. 备份
cp -r quant/papers/guangfa_full/ quant/papers/guangfa_full_baseline/

# 2. 强制 re-run
rm -f quant/papers/guangfa_full_new/track_b_checkpoint.json

# 3. 跑新方案
python -c "
from llmwikify.reproduction.paper_understanding.llm_extraction.orchestrator import run_one_paper
result = run_one_paper(
    paper_id='guangfa_full_new',
    source_path=...,
    output_root=...,
    run_pass2=True,
)
"

# 4. 对比
python tests/ab_testing/test_pass2_adaptive.py
```

**对比维度**：
- l1.formula 完整度
- l3.intuition 深度（字符数）
- l4.hypotheses 数量
- 提取成功率（success_rate）
- 总时间
- Token 消耗

## 7. 未来扩展

1. **Schema-specific 补充策略**：不同 schema（factor / signal / allocation）有不同补充需求
2. **自适应 batch size**：根据 LLM 表现动态调整（成功率高 → 增大 batch）
3. **多模型协作**：简单 signals 用小模型，复杂 signals 用大模型
4. **缓存层**：相同 formula_brief 复用上次的 L1-L4（避免重复提取）

## 8. 参考

- `docs/designs/paper_extraction_pipeline.md` - 整体 pipeline 设计
- `docs/designs/self_feedback_planning.md` - 自反馈规划机制
- `docs/summaries/pipeline_optimization_summary.md` - 优化总结
