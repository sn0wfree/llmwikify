"""kernel/codegen/ — 通用代码文本工具（非因子编译）。

历史: 从 kernel/quant/codegen/ 改名。曾包含 polars/QuantNodes 因子
执行路径；本项目不再做因子编译，执行相关代码已删除（2026-11-10）。

当前仅保留:
  - code_tools.py: extract_python / validate_syntax（纯文本 + ast）
  - json_extract.py: extract_json_from_response(text) → dict | None
"""

from __future__ import annotations

from .code_tools import extract_python, validate_syntax
from .json_extract import extract_json_from_response

__all__ = [
    "extract_python",
    "validate_syntax",
    "extract_json_from_response",
]
