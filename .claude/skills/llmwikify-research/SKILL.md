---
description: Multi-agent deep research for the llmwikify knowledge base. Plans, fans out parallel subagents, adversarially verifies findings, then writes a cited report into the wiki. Use when the user wants a thorough, multi-source answer that should persist in the wiki.
---

# llmwikify deep research

This skill delegates the user's research question to a dynamic workflow that
runs in the background. It is the right choice when:

- The question is broad enough to need more than one source
- The answer should be **saved to the wiki**, not just printed
- A wrong or unsupported claim would be costly
- The user explicitly asks for a "deep", "thorough", or "multi-source" answer

It is the wrong choice when:

- The answer is a single fact (use the regular `web_search` tool)
- The user wants a quick chat-style response with no persistence
- The wiki is empty (the synthesizer needs prior context to work well)

## How to invoke

The workflow is saved at `.claude/workflows/llmwikify-research.js`. Invoke it
with the `ultracode` keyword, or use the trigger command `/llmwikify-research`:

```
ultracode: research what changed in Rust async runtimes between 1.70 and 1.80
```

or

```
/llmwikify-research what changed in Rust async runtimes between 1.70 and 1.80
```

The orchestrator will:

1. Plan 3-5 phases with a planner subagent (Opus)
2. Run one Sonnet subagent per phase, in parallel, each in an isolated worktree
3. Adversarially review every claim with a skeptical Sonnet subagent
4. Synthesize the surviving findings into `research/<slug>.md` with an Opus writer

While the workflow runs, the session stays free. Watch progress in
`/workflows` or in the task panel below the input box. The final report
lands in the session as a normal message.

## What to tell the user before invoking

- The workflow is multi-agent and may run for several minutes. Costs scale with
  number of phases and breadth of sources; for a 4-phase run expect roughly
  4-8x the tokens of a single-shot research answer.
- The first time per project, Claude Code asks for approval. Suggest
  "Yes, and don't ask again" if the user plans to invoke it more than once.
- If the user wants a narrower / cheaper run, ask them to add "limit to N phases"
  or "use at most M sources per phase" to the question.

## After the run

- Read the synthesized page at `research/<slug>.md` before declaring success
- If the report flagged unmet criteria, surface them to the user as follow-ups
- If the user wants to extend, they can ask "also research <follow-up>" and
  invoke again; the planner will see the existing page and plan around it
