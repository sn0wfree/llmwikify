---
title: LLM-Native Wiki
source: karpathy-llm-wiki.md
date: 2024-09-15
type: source
tags: [llm, wiki, knowledge-base]
---

# LLM-Native Wiki

A wiki that an LLM maintains, with persistent cross-references and
contradiction tracking. Differs from Notion/Obsidian in that **the LLM
is a first-class author** of the wiki pages, not just a search tool.

## Key idea

> The wiki is a persistent, compounding artifact. Cross-references are
> already there. Contradictions have already been flagged. The
> synthesis already reflects everything you've read.

## How it differs

- **Notion**: human-authored, LLM is a search/plugin.
- **Obsidian**: human-authored, LLM via external scripts.
- **llmwikify**: LLM is a primary author, prompted by `wiki.md` schema.
