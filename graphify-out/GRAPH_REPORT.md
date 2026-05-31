# Graph Report - /home/ll/llmwikify/src/llmwikify/web/webui-agent/src  (2026-05-26)

## Corpus Check
- Corpus is ~6,147 words - fits in a single context window. You may not need a graph.

## Summary
- 96 nodes · 222 edges · 6 communities
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Agent UI Components|Agent UI Components]]
- [[_COMMUNITY_Edit & Ingest Logs|Edit & Ingest Logs]]
- [[_COMMUNITY_Chat Messaging|Chat Messaging]]
- [[_COMMUNITY_Dream Log & Badges|Dream Log & Badges]]
- [[_COMMUNITY_API & Data Types|API & Data Types]]
- [[_COMMUNITY_Toast Notifications|Toast Notifications]]

## God Nodes (most connected - your core abstractions)
1. `useAgentWikiStore` - 19 edges
2. `Button()` - 10 edges
3. `api` - 9 edges
4. `Card()` - 9 edges
5. `Badge()` - 8 edges
6. `useToast()` - 7 edges
7. `EmptyState()` - 7 edges
8. `Confirmations()` - 4 edges
9. `DreamProposals()` - 4 edges
10. `AgentChat()` - 4 edges

## Surprising Connections (you probably didn't know these)
- `App()` --calls--> `useAgentWikiStore`  [EXTRACTED]
  App.tsx → stores/agentWikiStore.ts
- `DreamLog()` --calls--> `useAgentWikiStore`  [EXTRACTED]
  components/DreamLog.tsx → stores/agentWikiStore.ts
- `TaskMonitor()` --calls--> `useAgentWikiStore`  [EXTRACTED]
  components/TaskMonitor.tsx → stores/agentWikiStore.ts
- `IngestLog()` --calls--> `useAgentWikiStore`  [EXTRACTED]
  components/IngestLog.tsx → stores/agentWikiStore.ts
- `Confirmations()` --calls--> `useAgentWikiStore`  [EXTRACTED]
  components/Confirmations.tsx → stores/agentWikiStore.ts

## Communities (6 total, 0 thin omitted)

### Community 0 - "Agent UI Components"
Cohesion: 0.18
Nodes (15): AgentChat(), Confirmations(), DreamProposals(), EditHistory(), IngestLog(), useToast(), WikiSelector(), Confirmation (+7 more)

### Community 1 - "Edit & Ingest Logs"
Cohesion: 0.16
Nodes (12): EditEntry, EmptyState(), EmptyStateProps, TaskMonitor(), api, TaskInfo, AgentWikiState, WikiInfo (+4 more)

### Community 2 - "Chat Messaging"
Cohesion: 0.16
Nodes (11): Message, ToolCall, chatStream(), ChatStreamEvent, Input(), InputProps, MessageBubble(), MessageBubbleProps (+3 more)

### Community 3 - "Dream Log & Badges"
Cohesion: 0.15
Nodes (10): DreamLog(), DreamEdit, Badge(), BadgeProps, variantMap, statusBadgeVariant, statusColorMap, statusText (+2 more)

### Community 4 - "API & Data Types"
Cohesion: 0.17
Nodes (10): AgentMessage, GraphData, GraphEdge, GraphNode, IngestLogEntry, Notification, SearchResult, SinkStatus (+2 more)

### Community 5 - "Toast Notifications"
Cohesion: 0.25
Nodes (5): ToastContext, ToastContextValue, ToastItem, ToastProvider(), ToastType

## Knowledge Gaps
- **35 isolated node(s):** `WikiPage`, `SearchResult`, `WikiStatus`, `SinkStatus`, `AgentMessage` (+30 more)
  These have ≤1 connection - possible missing edges or undocumented components.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `useAgentWikiStore` connect `Agent UI Components` to `Edit & Ingest Logs`, `Chat Messaging`, `Dream Log & Badges`?**
  _High betweenness centrality (0.053) - this node is a cross-community bridge._
- **Why does `Badge()` connect `Dream Log & Badges` to `Agent UI Components`, `Edit & Ingest Logs`?**
  _High betweenness centrality (0.018) - this node is a cross-community bridge._
- **Why does `Button()` connect `Edit & Ingest Logs` to `Agent UI Components`, `Chat Messaging`, `Dream Log & Badges`?**
  _High betweenness centrality (0.017) - this node is a cross-community bridge._
- **What connects `WikiPage`, `SearchResult`, `WikiStatus` to the rest of the system?**
  _35 weakly-connected nodes found - possible documentation gaps or missing edges._