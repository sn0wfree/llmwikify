# CLI Subcommand Aliases — `mcp` is an alias of `serve`

**Phase 3 #6** (planned for the next minor release) introduces a
small but useful change to the CLI: the `mcp` subcommand is now an
**argparse alias** of the `serve` subcommand. This document
explains what that means for users, integrators, and the
deprecation timeline.

## What changed

- `llmwikify mcp` still works — argparse treats it as an alias of
  `llmwikify serve`.
- `llmwikify serve` is now the **canonical** subcommand for
  starting the MCP server.
- `mcp` no longer appears in `llmwikify --help` as a separate
  top-level entry, but it is still accepted as input.
- A new `llmwikify help` subcommand lists all registered
  commands and the alias table.

## Why

Historically, the codebase had two separate subcommands — `mcp`
and `serve` — that pointed to the same handler (`run_serve`).
The `mcp` subparser had a strict subset of `serve`'s flags
(no `--web`, no `--auth-token`, no `--multi-wiki`), and the
two parsers were registered separately. This was technically
duplicated logic.

Phase 3 #6 collapses the two into a single `serve` subparser
with `aliases=["mcp"]` (a standard argparse feature). The
benefits are:

- **Single source of truth** — one parser, one Command class,
  one setup function.
- **No behavior change for users** — every command that worked
  with `llmwikify mcp` continues to work.
- **Bonus capabilities** — `mcp` users now have access to
  `serve`'s flags, e.g. `llmwikify mcp --web` (previously an
  argparse error).

## What users see

### `llmwikify --help` (unchanged for end users)

```
commands:
  ...
  serve        Start MCP server with optional Web UI (alias: mcp)
  ...
```

`mcp` is no longer a top-level entry, but the `(alias: mcp)`
hint in `serve`'s help makes the relationship explicit.

### `llmwikify mcp --help` (improved)

Before Phase 3 #6, `mcp --help` showed 4 flags (the strict
`mcp` subset). After, it shows `serve`'s full 8 flags
(because `mcp` is an alias of `serve`, the help is rendered
from the canonical parser).

### `llmwikify help` (new in Phase 3 #6)

```
Available commands:
  analyze-source    Analyze source and cache extraction results
  ...
  serve             Start MCP server with optional Web UI
  ...

Subcommand aliases (backward compat, removed in v0.34.0):
  mcp          → serve       (e.g., 'llmwikify mcp --name foo')
```

### `llmwikify help --aliases` (new in Phase 3 #6)

```
Subcommand aliases (backward compat, removed in v0.34.0):
  mcp          → serve       (e.g., 'llmwikify mcp --name foo')
```

## Backward compatibility

The `mcp` alias preserves **full backward compatibility** for:

- **End users** typing `llmwikify mcp ...` in their shell —
  still works.
- **MCP client configs** written by `llmwikify init --agent ...`:
  the `command: ["llmwikify", "mcp"]` line still launches a
  working MCP server.
- **External scripts** (CI, Docker entry points, etc.) that
  reference `llmwikify mcp` — still works.
- **Tests** that import from `llmwikify.cli.commands` or
  invoke `mcp` via argparse — still work.

The agent-facing MCP config file is the most important
backward-compat surface — it is what Claude Desktop,
Cursor, and other MCP clients read. Tests
`tests/test_init_agent.py` verify the config format remains
unaffected.

## Test coverage

Two pre-existing test cases in `tests/test_init_agent.py` verify
the agent-facing config still works:

- `assert config['mcp']['llmwikify']['command'] == ['llmwikify', 'mcp']`
  (current canonical form, used by Claude Desktop and Codex)
- `assert config['mcpServers']['llmwikify']['args'] == ['mcp']`
  (alternative form, used by some MCP clients)

A new test (`test_init_template_supports_both_mcp_and_serve_aliases`,
in `tests/test_mcp_serve_merge.py`) verifies that **the
canonical command could be rewritten as `['llmwikify',
'serve']` without breaking agent integration** — proving the
template can be safely updated in v0.34.0+.

## Deprecation timeline

- **v0.32.x** (current): `mcp` is an alias. No warnings, no
  removal. Full backward compat. *(this release)*
- **v0.33.x** (next minor): `mcp` remains an alias. No warnings
  yet. Suggests users begin migrating to `serve`.
- **v0.34.0** (planned removal): `mcp` alias **removed**.
  Users who still type `llmwikify mcp` will see an argparse
  error: `argument command: invalid choice: 'mcp'`. A clear
  migration message will be added at that time.

Migrate by replacing `llmwikify mcp` with `llmwikify serve`
in:

- Shell scripts and CI pipelines.
- `~/.config/claude/.../mcp.json` and similar MCP client
  configs (use `args: ["serve"]` instead of `args: ["mcp"]`).
- Documentation and tutorials.
- The `init` templates if the project decides to update them
  (not required — the alias works either way).

## Port and protocol access points

The merge does **not** change any port or protocol access
points. Agents continue to use:

| Access mode | Endpoint | Default port |
|-------------|----------|--------------|
| **stdio** (Claude Desktop / Cursor) | `command: ["llmwikify", "mcp"]` (or `serve`) | none (uses stdin/stdout) |
| **HTTP** | `http://127.0.0.1:8765/mcp` | 8765 |
| **SSE** | `http://127.0.0.1:8765/mcp/sse` | 8765 |
| **Unified server** (with WebUI) | `http://127.0.0.1:8765/` | 8765 |

All defaults remain 8765, configurable via `--mcp-port` or the
deprecated `--port` alias.

## How to find aliases in the future

```bash
# Show all commands + aliases:
llmwikify help

# Show only the alias section:
llmwikify help --aliases
```

Adding new aliases is a one-line argparse change:
`subparsers.add_parser("target", ..., aliases=["new_alias"])`.
The `help` command will pick them up automatically on the next
startup.
