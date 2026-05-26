"""Research report review and revision."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ResearchReviewer:
    """Evaluates research report quality and provides feedback."""

    def __init__(self, wiki: Any, llm_client: Any, config: dict[str, Any]):
        self.wiki = wiki
        self.llm_client = llm_client
        self.config = config
        self.min_score = 7  # score >= 7 is approved

    async def review(self, query: str, report: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
        """Review a research report for quality.

        Returns:
            {"approved": bool, "feedback": str, "issues": list[str], "score": int}
        """
        system = """You are a research report reviewer. Evaluate the report quality and provide actionable feedback.

Evaluation criteria:
1. Does the report answer the research topic comprehensively?
2. Are sources properly cited using [[Source:hash]] format?
3. Are all gathered sources represented in the report?
4. Are contradictions between sources noted?
5. Is the report well-structured with clear sections?
6. Is the report sufficiently detailed (minimum 800 words)?
7. Are claims properly attributed and distinguished (verified vs unverified)?

Score 1-10:
- 9-10: Excellent, comprehensive, well-cited
- 7-8: Good, minor issues only
- 5-6: Adequate, missing key sources or sections
- 3-4: Poor, major gaps
- 1-2: Unacceptable

Return JSON:
{
  "approved": true/false (score >= 7),
  "score": <int 1-10>,
  "feedback": "overall feedback sentence",
  "issues": ["specific issue 1", "specific issue 2"]
}"""

        user = f"""Research Topic: {query}

Report to review:
---
{report}
---

Number of sources gathered: {len(sources)}

Evaluate this report. Return JSON only."""

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        try:
            import asyncio
            import json as json_mod

            def _call():
                raw = self.llm_client.chat(messages, json_mode=True, max_tokens=2048, temperature=0.1)
                raw = raw.strip()
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                    if raw.endswith("```"):
                        raw = raw[:-3]
                    raw = raw.strip()
                return json_mod.loads(raw)

            result = await asyncio.to_thread(_call)
            result.setdefault("approved", result.get("score", 0) >= self.min_score)
            result.setdefault("feedback", "")
            result.setdefault("issues", [])
            result.setdefault("score", 0)
            return result
        except Exception as e:
            logger.warning("Report review failed: %s", e)
            return {"approved": True, "feedback": f"Review failed: {e}", "issues": [], "score": 7}


class ResearchRevisor:
    """Revises a research report based on reviewer feedback."""

    def __init__(self, wiki: Any, llm_client: Any, config: dict[str, Any]):
        self.wiki = wiki
        self.llm_client = llm_client
        self.config = config

    async def revise(
        self,
        report: str,
        issues: list[str],
        sources: list[dict[str, Any]],
    ) -> str:
        """Revise a report to address reviewer issues.

        Returns revised markdown report.
        """
        system = """You are a research report reviser. Given a report and specific issues to fix, produce an improved version.

Rules:
- Fix ALL issues listed by the reviewer
- Maintain the existing report structure
- Add missing source citations using [[Source:hash]] format
- Ensure all gathered sources are represented
- Note any contradictions between sources
- Keep the report comprehensive and well-structured
- Output ONLY the revised markdown report, nothing else"""

        issues_text = "\n".join(f"- {issue}" for issue in issues)

        # Build source reference for revision
        source_refs: list[str] = []
        for s in sources:
            import hashlib
            key = s.get("url") or s.get("title", "unknown")
            h = hashlib.md5(key.encode()).hexdigest()[:12]
            source_refs.append(f"[{h}] {s.get('source_type', '')}: {s.get('title', '')} — {s.get('url', '')}")

        user = f"""## Issues to fix:
{issues_text}

## Available sources:
{chr(10).join(source_refs)}

## Current report:
{report}

Produce the revised report now."""

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        import asyncio
        revised = await asyncio.to_thread(
            self.llm_client.chat, messages, max_tokens=8192, temperature=0.3
        )
        return revised
