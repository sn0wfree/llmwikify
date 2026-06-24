"""PromptRenderer: Jinja2 模板渲染."""
from __future__ import annotations

from typing import Any

from jinja2 import Template


def render_template(template_str: str, **kwargs: Any) -> str:
    """用 Jinja2 渲染模板字符串."""
    tmpl = Template(template_str)
    return tmpl.render(**kwargs)
