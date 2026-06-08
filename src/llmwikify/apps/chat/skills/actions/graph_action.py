"""graph_skill — knowledge graph operations.

Thin wrapper over ``Wiki._graph_action`` (the action dispatcher
inside ``apps/agent/tools/__init__.py::_graph_action``).

  Action: ``graph(action, concept, direction, source, target, ...)``
  Returns: ``dict`` (graph query/stats/path/write result)

One of the 14 base actions per
``v0.32-skill-restructure.md`` §3.1.
"""

from __future__ import annotations

from llmwikify.apps.chat.skills.actions._helpers import safe_call, wiki_from_ctx
from llmwikify.apps.chat.skills.base import (
    Skill,
    SkillAction,
    SkillContext,
    SkillResult,
)


async def _graph(args: dict, ctx: SkillContext) -> SkillResult:
    wiki = wiki_from_ctx(ctx)
    if wiki is None:
        return SkillResult.fail("No wiki in context")
    # The wiki.graph action was originally called via the
    # agent tool's _graph_action. For Phase 5, we use a
    # public dispatch: any "graph" callable on the wiki.
    graph_fn = getattr(wiki, "graph", None)
    if graph_fn is None:
        return SkillResult.fail("wiki has no graph method")
    return safe_call(graph_fn, args, error_prefix="graph failed")


class GraphSkill(Skill):
    """Action wrapper for knowledge graph operations."""

    name = "graph"
    description = "Knowledge graph operations (query / path / stats / write)"
    actions = {
        "graph": SkillAction(
            name="graph",
            description=(
                "Query or modify the wiki's knowledge graph. "
                "Sub-actions: query (find neighbors), path "
                "(find shortest path), stats (graph statistics), "
                "write (add relations)."
            ),
            handler=_graph,
            requires_confirmation="pre",
            action_type="write",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["query", "path", "stats", "write"],
                        "default": "query",
                    },
                    "concept": {"type": "string"},
                    "direction": {"type": "string", "enum": ["inbound", "outbound", "both"]},
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                    "max_length": {"type": "integer", "default": 5},
                    "relations": {"type": "array", "items": {"type": "object"}},
                },
                "required": [],
            },
        ),
    }


graph_skill = GraphSkill()


__all__ = ["GraphSkill", "graph_skill"]
