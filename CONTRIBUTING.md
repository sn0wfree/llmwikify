# Contributing to llmwikify

Thank you for your interest in contributing! This guide covers the development workflow, coding standards, and contribution process.

## Development Setup

```bash
git clone https://github.com/sn0wfree/llmwikify.git
cd llmwikify
pip install -e ".[dev]"
```

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src/llmwikify --cov-report=term-missing

# Run specific test file
pytest tests/test_v023_graph.py -v

# Generate HTML coverage report
pytest --cov=src/llmwikify --cov-report=html
open htmlcov/index.html
```

**Target**: 4454+ Python tests + 38 frontend tests passing, >85% code coverage.

## Code Quality

```bash
# Format code
black src/llmwikify tests

# Lint
ruff check src/llmwikify tests

# Type check
mypy src/llmwikify
```

All three must pass before submitting a PR. CI will enforce this automatically.

## Project Structure

```
src/llmwikify/
├── kernel/                    # Core engines
│   ├── wiki/                  # Wiki domain model (13 mixins)
│   │   ├── wiki.py            # Wiki orchestrator
│   │   ├── mixins/            # Core, IO, Analysis mixins
│   │   ├── engines/           # Analyzer, relation, synthesis
│   │   └── lint/              # Rule-based lint engine
│   ├── multi_wiki/            # Multi-wiki registry
│   ├── search/                # QMD hybrid search
│   ├── graph/                 # Knowledge graph (PageRank, communities)
│   └── storage/               # Persistence (FTS5, index, watcher)
│
├── foundation/                # Cross-cutting primitives
│   ├── llm/                   # LLM client, streaming, token budget
│   ├── prompts/               # YAML+Jinja2 prompt templates
│   ├── extractors/            # Content extractors (PDF, web, YouTube)
│   └── templates/             # JSON templates
│
├── apps/                      # Application services
│   ├── wiki/                  # Wiki application service
│   ├── chat/                  # Chat + ReAct + Skills
│   │   ├── agent/             # Agent runtime, ReAct engine
│   │   ├── skills/            # Skill system (actions, pipelines, workflows)
│   │   └── harness/           # Quality gate, review
│   ├── research/              # Web research engine
│   └── agent/                 # Dream editor, scheduler, hooks
│
└── interfaces/                # Entry points
    ├── cli/                   # CLI commands (30 subcommands)
    │   └── commands/          # Command modules
    ├── mcp/                   # MCP protocol adapter (26 tools)
    ├── server/                # Unified FastAPI server
    │   ├── core.py            # WikiServer orchestrator
    │   └── http/              # REST API routes
    └── web/                   # Web bundle entry

tests/                         # Test suite (4454+ Python tests)
docs/                          # Documentation
ui/webui/                      # React SPA (WebUI)
```

## Adding a New Feature

1. **Open an issue first** — Describe the feature, rationale, and proposed API
2. **Write tests first** (TDD) — Create test cases in `tests/test_<feature>.py`
3. **Implement the feature** — Add code to the appropriate module
4. **Update documentation** — README.md, ARCHITECTURE.md, CHANGELOG.md
5. **Run quality checks** — `black`, `ruff`, `mypy`, `pytest`
6. **Submit a PR** — Reference the issue, describe changes

## Adding a New CLI Command

1. Add the command method to `src/llmwikify/interfaces/cli/commands/<command>.py`
2. Register the subcommand in the `_build_parser()` method in `src/llmwikify/interfaces/cli/_app.py`
3. Write tests in `tests/test_cli.py` or a new test file
4. Update the CLI commands table in README.md

## Adding a New MCP Tool

1. Add the tool definition to `src/llmwikify/interfaces/mcp/tools.py`
2. Add the handler in the `call_tool()` function
3. Update the MCP tools table in README.md
4. Write tests (integration test with mock MCP)

## Prompt Template Changes

When modifying prompts in `src/llmwikify/foundation/prompts/_defaults/`:

1. Run principle compliance: `python scripts/check_prompt_principles.py`
2. Run offline evaluation: `python scripts/eval_prompts.py`
3. Run regression tests: `pytest tests/test_v019_harness_regression.py`

## Versioning

This project uses [Semantic Versioning](https://semver.org/):

- **Patch** (0.x.Y): Bug fixes, no new features
- **Minor** (0.X.0): New features, backward compatible
- **Major** (X.0.0): Breaking changes

When releasing:
1. Update `version` in `pyproject.toml`
2. Add entry to `CHANGELOG.md`
3. Update `MIGRATION.md` if there are breaking changes
4. Update test count badges in README.md and ARCHITECTURE.md
5. Update version headers in ARCHITECTURE.md

## Design Principles

All contributions should align with these principles:

1. **Zero Domain Assumptions** — No hardcoded concepts, all exclusion patterns are empty by default
2. **Configuration-Driven** — User decides what to exclude via `.wiki-config.yaml`
3. **Performance by Default** — Batch operations, PRAGMA optimizations
4. **Pure Tool Design** — Universal patterns only, works for any domain
5. **Knowledge Compounding** — Query answers saved back to wiki as persistent pages
6. **User Control** — Watch defaults to notify-only, graph analysis is opt-in
7. **Modular Architecture** — Clear separation of concerns, optional dependencies

## Pull Request Checklist

- [ ] Tests pass: `pytest`
- [ ] Code formatted: `black src/llmwikify tests`
- [ ] Lint clean: `ruff check src/llmwikify tests`
- [ ] Type check: `mypy src/llmwikify`
- [ ] CHANGELOG.md updated
- [ ] README.md updated (if user-facing changes)
- [ ] ARCHITECTURE.md updated (if structural changes)
- [ ] MIGRATION.md updated (if breaking changes)

## Getting Help

- **GitHub Issues**: [Report bugs or request features](https://github.com/sn0wfree/llmwikify/issues)
- **GitHub Discussions**: [Ask questions or share ideas](https://github.com/sn0wfree/llmwikify/discussions)
- **Email**: linlu1234567@sina.com

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
