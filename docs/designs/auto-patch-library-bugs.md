# Auto-Patching Library Bugs: Experience Report

## Problem

`neutralize(f, group=pl.col('industry'))` crashed with `TypeError: truth value of an Expr is ambiguous`.

Root cause: QuantNodes `neutralize()` wrote `if group:` internally, which performs Python bool evaluation on the passed polars Expr, triggering the well-known Polars error.

```python
# section_ops.py:79
def neutralize(f, group=None, **kwargs):
    e = _ensure_expr(f)
    if group:          # <-- BOOM when group is pl.Expr
        g = _ensure_expr(group)
        ...
```

Impact: 15 of 101 alphas failed identically (99 -> 84 success rate in the current pipeline). All 15 used `IndNeutralize(vwap/close/volume, IndClass.industry/sector)` which the LLM translated to `neutralize(f, group=pl.col('industry'))`.

## Diagnosis Process (reproducible by LLM)

1. `execute_code()` raises `DangerousCodeError`
2. Full traceback shows first frame at `section_ops.py:79` in `neutralize`, not in user code
3. `inspect.getsource(neutralize)` reveals `if group:`
4. Fix is trivial: `if group is not None:` (same semantics, no bool coercion on Expr)
5. Same pattern found in `weightStandardize` (`if weight:`)
6. The SYSTEM_PROMPT was also instructing the LLM to use `neutralize(f, group=pl.col('industry'))`, which was both wrong (crashes) and unnecessary (QuantNodes has `IndNeutralize` for this)

## Applied Fixes

### QuantNodes (`section_ops.py:79`)
```
- if group:
+ if group is not None:
```

### QuantNodes (`section_ops.py:257`)
```
- if weight:
+ if weight is not None:
```

### Prompt (`llm_code.py:92`)
Removed `-> neutralize(f, group=pl.col('industry')): industry neutralization` from SYSTEM_PROMPT, replaced with safer `neutralize(f): cross-section neutralization (subtract mean)`.

## Result

- Before: 84/101 success
- After: 99/101 success (2 remaining: TimeoutError on alpha-057, 100 — unrelated)

## Auto-Fix Loop Design

The agent's diagnosis process can be automated so that future library bugs are caught and patched without human/agent intervention:

```
execute_code() raises DangerousCodeError
    |
    v
1. DETECT: Does traceback first frame point to QuantNodes/3rd-party code?
    |-- No  -> normal ReAct (LLM fixes user code)
    |-- Yes -> enter auto-fix sub-flow
    |
    v
2. LLM DIAGNOSE: Feed LLM with:
    - Error message + full traceback
    - Source of the failing function (inspect.getsource)
    - Task: "Find the library bug in this function and emit a monkey-patch"
    |
    v
3. APPLY: exec() the monkey-patch into the current namespace
    |
    v
4. VERIFY: Re-execute the original user code
    |-- Pass -> cache patch (process-local), return normally
    |-- Fail -> fall back to normal ReAct flow
```

### Key design decisions

- **Do not modify QuantNodes source on disk** — patch is in-memory only (per-process namespace), discarded on restart. This avoids accidental destructive edits and keeps the fix ephemeral.
- **Same LLM does the diagnosis** — it already has the context (SYSTEM_PROMPT, code, error), just needs `inspect.getsource` of the failing function.
- **Cache per process** — `namespace._patches` dict, avoid re-diagnosing the same function twice.
- **No Prompt modification needed** — the patch fixes the library transparently; LLM doesn't need to know.

## Lessons Learned

1. **"Execution error" does not always mean user code error.** The traceback reliably distinguishes the two: if the first non-framework frame is in QuantNodes internals, it's a library bug.
2. **`if expr:` on polars Expr is a recurring pattern** — `neutralize`, `weightStandardize`, and likely other QuantNodes functions have this issue. A general `if X is not None:` fix covers most cases.
3. **Prompt and library are coupled** — the SYSTEM_PROMPT told LLM to use a broken API (`neutralize(f, group=pl.col('industry'))`). Fixing the library alone would reduce crashes but not eliminate them (LLM might still try other Expr-group patterns). Fixing both is necessary.
4. **QuantNodes has the right function already** — `IndNeutralize(f, ind_class='industry')` does exactly what the alpha-101 formula needs, without the `if group:` issue. The LLM just needed to know about it.
