"""Shared feedback templates for codegen self-repair loops.

Moved from react_engine.py to break circular import risk with unified framework.
"""
from __future__ import annotations


OBSERVE_FEEDBACK_TEMPLATE = """[ReAct OBSERVE] Your previous code failed at stage: {stage}

Error:
{error}

{context}

## FIX GUIDE

### If "truth value of an Expr is ambiguous":
You used Python `if/and/or` on a polars expression. This is NOT allowed.

BEFORE (broken):
```python
if rank(pl.col('a')) < rank(pl.col('b')):
    factor = -1
else:
    factor = 0
```

AFTER (fixed):
```python
factor = pl.when(rank(pl.col('a')) < rank(pl.col('b'))).then(-1).otherwise(0)
```

Also replace:
- `expr and expr` → `expr & expr`
- `expr or expr` → `expr | expr`
- `not expr` → `~expr`

### If "TimeoutError":
Your code has an infinite loop or too-slow computation.
- Use `with_columns()` to materialize intermediate results
- Avoid nested rolling operations without materialization

### If "NameError: name 'xxx' is not defined":
Check operator name. Available: rolling_*, ts_*, rank, scale, neutralize, etc.

### General rules:
- Use FUNCTION FORM: `rolling_std(pl.col('x'), window=20)` NOT `pl.col('x').rolling_std(...)`
- Use `.over('date')` for cross-section operators (rank, scale, etc.)
- Use `neutralize(f, group=pl.col('industry'))` for industry neutralization

Output ONLY the corrected code block, no prose."""
