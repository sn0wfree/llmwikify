# llmwikify CLI Reference

Complete reference for all 19 llmwikify commands.
Run from the wiki root directory (where `wiki.md` exists).

---

## init

Initialize wiki directory structure.

```bash
llmwikify init [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--agent <type>` | Generate agent config: `opencode`, `claude`, `codex`, `generic` |
| `--overwrite` | Recreate index.md and log.md if they exist |
| `--force` | Overwrite existing files without prompting |
| `--merge` | Merge new schema sections into existing wiki.md |

**Output:**
```
✅ Wiki initialized at /path/to/project

  Created: raw/, wiki/, wiki.md, opencode.json, .gitignore

  Source analysis:
    1379 files in 7 categories
    Top: gold (613), copper (288), lithium (246), ...

  Next steps:
    1. Review wiki.md for page conventions
    2. Run: opencode
    3. Tell the agent: 'Start ingesting news from raw/'
```

---

## ingest

Ingest a single source file.

```bash
llmwikify ingest <file> [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--self-create, -s` | CLI uses LLM API to analyze content and create wiki pages |
| `--dry-run, -n` | Show extraction summary without creating pages |

**Basic output:**
```
Ingested: Article Title (markdown)
Content length: 4,533 chars
Saved to raw: article.md

No pages created automatically.
Use --self-create for LLM-assisted page creation.
```

**Smart mode output:**
```
LLM Plan (5 operations):
  1. write_page: wiki/sources/article.md
  2. write_page: wiki/entities/Company Name.md
  3. write_page: wiki/concepts/Topic.md
  4. log: ingest | Article Title
  5. write_graph_relations

Executing...
  [ok] write_page: wiki/sources/article.md
  [ok] write_page: wiki/entities/Company Name.md
  ...

Extracting 3 relations...
  Relations added: 3

Completed: 5 operations
```

---

## write_page

Create or update a wiki page.

```bash
llmwikify write_page "Page Name" [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--file, -f <path>` | Read content from file |
| `--content, -c <text>` | Content as string |

**Output:**
```
✅ Wiki page written: wiki/Page Name.md
```

---

## read_page

Read a wiki page.

```bash
llmwikify read_page "Page Name"
```

**Output:** Full markdown content of the page to stdout.

```
# Page Name

Content here...

[[Related Page]]
```

---

## search

Full-text search using SQLite FTS5.

```bash
llmwikify search "<query>" [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--limit, -l <N>` | Max results (default: 10) |

**Output:**
```
Search results for: gold mining

1. Gold Industry
   Score: 0.95
   Ghana is a leading **gold mining** country...

2. Mining Regulations
   Score: 0.72
   New **mining** permits take 2+ years...
```

No results:
```
No results found for: nonexistent query
```

---

## lint

Health check for the wiki.

```bash
llmwikify lint [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--format <f>` | `full` (default), `brief`, `recommendations` |
| `--generate-investigations, -g` | Use LLM to generate investigation suggestions |

**Full format output:**
```
=== Wiki Health Check ===
Total pages: 42
Issues found: 3

By type:
  broken_link: 2
  orphan_page: 1

First 20 issues:
  ❌ [broken_link] Page A → [[Nonexistent]]
  ❌ [broken_link] Page B → [[Missing Page]]
  ❌ [orphan_page] Page C
```

**Brief format (quick suggestions):**
```
=== Wiki Suggestions ===

🔴 [HIGH] Broken link in Page A → [[Nonexistent]]
🟡 [MEDIUM] Orphan page: [[Page C]]

Summary: 2 suggestion(s)
```

**Recommendations format (missing/orphan pages):**
```
=== Wiki Recommendations ===

🔴 Missing Pages (2)

   • [[Ghana Gold Policy]]
   • [[Mining Tax Reform]]

🟠 Orphan Pages (1)

   • [[Daily Summary 2026-04-01]]
```

---

## status

Show wiki status summary.

```bash
llmwikify status
```

**Output:**
```
=== Wiki Status ===
📁 Root: /path/to/project
📄 Pages: 42
📦 Sources: 1379
🔍 Indexed: 42
🔗 Links: 156
```

---

## log

Append a log entry to `wiki/log.md`.

```bash
llmwikify log <operation> <description>
```

**Output:**
```
✅ Log entry appended: operation | description
```

---

## build-index

Build or export reference index.

```bash
llmwikify build-index [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--no-export` | Skip JSON export |
| `--output, -o <path>` | Custom JSON output path |
| `--export-only` | Export without rebuilding |

**Output:**
```
=== Building Reference Index ===
Scanning: /path/to/project/wiki

=== Index Built ===
Total pages: 42
Total links: 156
⏱️  Elapsed: 0.12s
📈 Speed: 350 files/sec
```

---

## references

Show page references (inbound/outbound wikilinks).

```bash
llmwikify references "Page Name" [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--detail, -d` | Show full context snippets |
| `--inbound, -i` | Inbound links only |
| `--outbound, -o` | Outbound links only |
| `--stats, -s` | Show reference statistics |
| `--broken, -b` | Show broken references |
| `--top, -t <N>` | Top N for stats (default: 10) |

**Normal output:**
```
=== References: Page Name ===

📥 Inbound (3)
  1. Page A → #Section
  2. Page B →
  3. Page C → #Other

📤 Outbound (2)
  1. Related Page
  2. Another Page [as "Custom Display"]

---
💡 Use --detail for full context
```

**Stats output:**
```
=== Reference Statistics ===

📈 Most Linked-To Pages (Top 10):
  Gold Industry: 15 inbound
  Kinross Gold: 8 inbound
  ...

📊 Most Active Pages (Top 10):
  Overview: 12 outbound
  Gold Industry: 8 outbound
  ...

🟠 Orphan Pages (2):
  Old Summary
  Draft Analysis
```

**Broken output:**
```
=== Broken References ===

  ❌ Page A → [[Nonexistent]]
  ❌ Page B → [[Missing Page]]

Total: 2 broken link(s)
```

---

## batch

Batch ingest multiple sources.

```bash
llmwikify batch <directory-or-glob> [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--limit, -l <N>` | Limit number of sources |
| `--self-create, -s` | CLI uses LLM API to process content |

**Output:**
```
=== Batch Ingest ===
Found 10 source(s)

[1/10] Processing: article1.md
  ✅ Article One
[2/10] Processing: article2.md
  ✅ Article Two
...

=== Batch Complete ===
Success: 10, Failed: 0
```

---

## sink-status

Show query sink buffer status.

```bash
llmwikify sink-status
```

**Output:**
```
=== Query Sink Status ===

  ⏳ Query: Gold price outlook: 3 entries (pending)
  ✅ Query: Ghana mining policy: 5 entries (reviewed)
```

---

## synthesize

Save a query answer as a wiki page.

```bash
llmwikify synthesize "<query>" [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--answer, -a <text>` | Answer content (or read from stdin) |
| `--page-name, -n <name>` | Custom page name |
| `--sources, -s <pages>` | Source pages to link |
| `--merge <strategy>` | `sink` (default), `merge`, `replace` |

**Example with stdin:**
```bash
echo "Gold prices rose 15% in Q1 2026." | llmwikify synthesize "What happened to gold prices?"
```

**Output:**
```
✅ Synthesized: Query: What happened to gold prices?
```

---

## watch

Watch `raw/` directory for new files.

```bash
llmwikify watch [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--auto-ingest` | Automatically ingest new files |
| `--self-create, -s` | CLI uses LLM API to process files (requires --auto-ingest) |
| `--debounce <seconds>` | Debounce time (default: 2.0) |
| `--dry-run, -n` | Print events without ingesting |
| `--git-hook` | Install git post-commit hook |
| `--uninstall-hook` | Uninstall git post-commit hook |

**Output (notify mode):**
```
=== File Watcher ===
Watching: /path/to/raw
Auto-ingest: No (notify only)
Smart mode: No
Debounce: 2.0s
Dry run: No

Press Ctrl+C to stop.

📄 [created] new-article.md
```

**Output (auto-ingest mode):**
```
=== File Watcher ===
Watching: /path/to/raw
Auto-ingest: Yes
...

📄 [created] new-article.md
  ✅ Ingested: New Article (markdown)
```

---

## graph-query

Query the knowledge graph.

```bash
llmwikify graph-query <subcommand> [args]
```

Subcommands: `neighbors`, `path`, `stats`, `context`

### neighbors

```bash
llmwikify graph-query neighbors "Ghana"
```

**Output:**
```
=== Graph Query: neighbors(Ghana) ===

Concept: Ghana
Neighbors (3):

  → [supports] Gold Royalty Regime (confidence: EXTRACTED)
  ← [related_to] Africa (confidence: INFERRED)
  → [implements] Mining Tax Reform (confidence: EXTRACTED)
```

### path

```bash
llmwikify graph-query path "Ghana" "Gold Royalty"
```

**Output:**
```
=== Graph Query: path(Ghana → Gold Royalty) ===

Path found (length: 2):

  Ghana --implements--> Mining Policy --affects--> Gold Royalty
```

### stats

```bash
llmwikify graph-query stats
```

**Output:**
```
=== Graph Stats ===

Nodes: 45
Edges: 123
Degree distribution:
  Min: 1, Max: 12, Avg: 2.7
```

### context

```bash
llmwikify graph-query context <relation-id>
```

**Output:**
```
=== Graph Context: Relation #42 ===

Source: Ghana
Target: Gold Royalty Regime
Relation: supports
Confidence: EXTRACTED
Source file: raw/gold/ghana-royalty.md
Wiki pages: Gold Royalty Regime
Context: "Ghana plans to replace flat royalty with sliding scale..."
```

---

## export-graph

Export knowledge graph visualization.

```bash
llmwikify export-graph [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--format <f>` | `html` (default), `svg`, `graphml` |
| `--output, -o <path>` | Output file path |
| `--min-degree <N>` | Filter nodes below this degree |
| `--confidence <level>` | Minimum confidence: `EXTRACTED`, `INFERRED`, `AMBIGUOUS` |

**Output:**
```
=== Exporting Graph ===
Format: html
Output: graph.html
Nodes: 45, Edges: 123
Done! Open graph.html in your browser.
```

---

## community-detect

Detect knowledge communities via graph clustering.

```bash
llmwikify community-detect [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--algorithm <a>` | `leiden` (default), `louvain` |
| `--resolution <r>` | Resolution parameter (default: 1.0) |
| `--json` | Output as JSON |
| `--dry-run, -n` | Print stats only |

**Output:**
```
=== Community Detection ===
Algorithm: leiden
Resolution: 1.0

Found 4 communities:

Community 0 (12 nodes): Gold, Ghana, Mining Tax, ...
Community 1 (8 nodes): Copper, Chile, Escondida, ...
Community 2 (15 nodes): Lithium, EV, Battery, ...
Community 3 (10 nodes): Silver, Industrial, Solar, ...
```

---

## report

Generate unexpected connections report.

```bash
llmwikify report [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--top <N>` | Number of top connections (default: 10) |
| `--output, -o <path>` | Output file path |

**Output:**
```
=== Surprise Report ===
Top 10 unexpected connections:

1. Gold → Solar Panel (score: 0.85)
   Explanation: Cross-community, different source types, low confidence

2. Ghana → Battery Technology (score: 0.78)
   Explanation: Cross-community, peripheral connection

...
```

---

## mcp

Start MCP server for Agent interaction.

```bash
llmwikify mcp [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--transport <t>` | `stdio` (default), `http`, `sse` |
| `--host <addr>` | Host address |
| `--port, -p <N>` | Port number |

---

## serve

[Reserved] Start a self-hosted Agent with LLM API.

```bash
llmwikify serve [OPTIONS]
```

Same options as `mcp`.
