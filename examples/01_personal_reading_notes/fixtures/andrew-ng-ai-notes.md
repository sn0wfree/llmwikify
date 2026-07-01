---
title: Bidirectional References
source: andrew-ng-ai-notes.md
date: 2024-10-01
type: source
tags: [obsidian, pkm, bidirectional]
---

# Bidirectional References

[[LLM-Native Wiki]] highlights cross-references as a first-class
concept. Obsidian and Roam popularized this in human-authored wikis.

## Resolution

Both forward and backward links matter:
- **Forward** (`outbound`): what does this page cite?
- **Backward** (`inbound`): who cites this page?

llmwikify stores both in `reference_index.json` and exposes
`wiki references <page> --detail`.
