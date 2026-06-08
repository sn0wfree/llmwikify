"""Shared base for the 8 detect_* actions.

Each detect action is a thin wrapper over a
``Wiki._detect_*()`` method. The wrappers are uniform:

  - Input: none (the action operates on the wiki as a whole)
  - Output: ``{"findings": list[dict]}`` — the underlying
    ``_detect_*()`` return value
  - Error handling: ``safe_call`` converts exceptions to
    ``SkillResult.fail(...)``

This base class provides the common plumbing so each
detect action file is 30-40 lines instead of 50+.

Per ``v0.32-skill-restructure.md`` §3.1, the 8 detect
actions are the 15th-22nd of the 23 base actions. They
are orchestrated by:
  - ``lint_skill`` (the wiki health check, item #5)
  - ``wiki_knowledge_gaps`` (a future wiki_query action)
"""

from __future__ import annotations

import logging

from llmwikify.apps.chat.skills.actions._helpers import safe_call, wiki_from_ctx
from llmwikify.apps.chat.skills.base import (
    Skill,
    SkillAction,
    SkillContext,
    SkillResult,
)

logger = logging.getLogger(__name__)


class DetectActionSkill(Skill):
    """Base for the 8 detect_* actions.

    Subclasses set:
      - ``name`` (e.g. "detect_knowledge_gaps")
      - ``description`` (one-line summary)
      - ``DETECT_METHOD`` (the wiki method to call, e.g. "_detect_knowledge_gaps")
      - ``DETECT_DESC`` (the LLM-facing description of this detect)
    """

    name: str = ""
    description: str = ""
    DETECT_METHOD: str = ""
    DETECT_DESC: str = ""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Auto-build the actions dict from the class attrs.
        if not cls.name or not cls.DETECT_METHOD:
            raise TypeError(
                f"{cls.__name__} must set 'name' and 'DETECT_METHOD'"
            )

        async def _handler(args: dict, ctx: SkillContext) -> SkillResult:
            wiki = wiki_from_ctx(ctx)
            if wiki is None:
                return SkillResult.fail("No wiki in context")
            method = getattr(wiki, cls.DETECT_METHOD, None)
            if method is None:
                return SkillResult.fail(
                    f"wiki has no {cls.DETECT_METHOD} method"
                )
            result = safe_call(method, error_prefix=f"{cls.name} failed")
            # Wrap the raw list into a dict for consistency with
            # the other actions' output shape.
            if result.status == "ok" and isinstance(result.data, dict):
                if "findings" not in result.data:
                    # safe_call already wrapped the list into
                    # {"result": [...]} — unwrap it.
                    inner = result.data.get("result")
                    if isinstance(inner, list):
                        result.data = {"findings": inner}
            return result

        cls.actions = {
            cls.DETECT_METHOD.lstrip("_"): SkillAction(
                name=cls.DETECT_METHOD.lstrip("_"),
                description=cls.DETECT_DESC,
                handler=_handler,
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            ),
        }


__all__ = ["DetectActionSkill"]
