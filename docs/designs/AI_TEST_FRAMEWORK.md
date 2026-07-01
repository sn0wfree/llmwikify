# AI Test Generation Framework - Design Document

> **Status**: Design draft for discussion
> **Author**: llmwikify project
> **Date**: 2026-07-01
> **Target**: 2-3 days implementation, 1-2 weeks total (including Docker test system)

## 1. Background & Motivation

### 1.1 Problem Statement

Current test workflow in llmwikify:
1. **Human writes tests** based on documentation and code understanding
2. **Human runs tests** locally with own LLM config
3. **CI runs tests** with secrets injected
4. **Human maintains tests** when code changes

Pain points:
- **High maintenance cost**: 14 test files, 76 tests, all hand-written
- **Documentation drift**: TUTORIAL.md, README.md, and tests evolve independently
- **Slow iteration**: Adding a new feature requires manually writing tests
- **CI inconsistency**: Local environment differs from CI environment
- **Knowledge gap**: New contributors don't know what to test

### 1.2 Vision

**Let AI be a senior test engineer.**

The AI Test Generation Framework (ATF) enables:
1. **AI reads** documentation, source code, and existing tests
2. **AI writes** pytest tests following project conventions
3. **AI runs** tests in Docker (real environment)
4. **AI fixes** failures autonomously (with retry limits)
5. **Human reviews** the final output

### 1.3 Goals

| Goal | Success Metric |
|---|---|
| Reduce test writing time | 80% reduction for new scenarios |
| Improve test coverage | 90%+ API surface covered |
| Maintain test quality | 95%+ tests pass without human fix |
| CI/CD integration | Nightly auto-PR with new tests |
| Project-agnostic | Works for any Python project |

### 1.4 Non-Goals

- Replace human review (AI suggests, human approves)
- Support non-Python projects (initially)
- Build a full-blown QA platform (out of scope)
- Replace existing unit tests (focus on integration/scenario tests)

## 2. Architecture Overview

### 2.1 System Components

```
┌─────────────────────────────────────────────────────────────┐
│                    AI Test Framework                         │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  Discoverer  │→ │  Generator   │→ │   Fixer      │       │
│  │  (read docs) │  │  (LLM write) │  │  (LLM fix)   │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│         │                  │                  │              │
│         └──────────────────┼──────────────────┘              │
│                            ↓                                 │
│                    ┌──────────────┐                          │
│                    │  Agent       │  (Orchestrator)         │
│                    │  (main API)  │                          │
│                    └──────────────┘                          │
│                            │                                 │
│         ┌──────────────────┼──────────────────┐              │
│         ↓                  ↓                  ↓              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  LLM Client  │  │ Docker       │  │  CLI / API   │       │
│  │  (abstraction│  │  Runner      │  │  (user       │       │
│  │   + provider)│  │  (subprocess)│  │   interface) │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Data Flow

```
Input Sources                AI Processing                 Output
─────────────                ─────────────                 ──────
                                                            
TUTORIAL.md ─┐                                                 
             │                                                 
README.md ───┼──→  Discoverer  ──→  Scenario  ──┐             
             │      (AST parse,                   │             
examples/ ───┘       regex)                        ↓             
                                     Generator  → TestFile ─┐
src/*.py ────→  Code AST   ──→  Scenarios       │            │
                                     (LLM)        │            
                                                     ↓         
User ────────→  CLI command  ──→  Agent         Docker      ↓
                                     (orchestrate) Runner  → JUnit XML
                                                  (subprocess)     
                                                     ↓            
                                                Fixer (if fail) 
                                                     ↓            
                                                Retry (max 3)   
                                                     ↓            
                                        Final TestFile (git) 
```

### 2.3 Component Responsibilities

| Component | Responsibility | Input | Output |
|---|---|---|---|
| **Discoverer** | Extract testable scenarios from various sources | TUTORIAL.md, README.md, source code | `list[Scenario]` |
| **Generator** | Write pytest test code via LLM | `Scenario`, project context | `TestFile` |
| **Fixer** | Repair failing tests via LLM | `TestFailure`, original test | Fixed `TestFile` |
| **Runner** | Execute tests in Docker | `TestFile` list, env vars | `TestResult` |
| **Agent** | Orchestrate the full workflow | User command | Generated tests + report |
| **LLM Client** | Abstract LLM provider calls | Prompt text | LLM response |
| **CLI** | User-facing command interface | CLI args | Exit code + output |

## 3. Detailed Component Design

### 3.1 Scenario (Data Model)

```python
@dataclass
class Scenario:
    """A testable scenario extracted from project."""
    name: str                              # "Wiki Init + FTS5 Search"
    description: str                       # Full description
    background: str = ""                   # "Notion lacks LLM-native search..."
    steps: list[str] = field(default_factory=list)   # ["init wiki", "write page", "search"]
    expected_outcome: str = ""             # "5 results found"
    prerequisites: list[str] = field(default_factory=list)  # ["wiki initialized"]
    llm_required: bool = False             # Need LLM calls?
    server_required: bool = False          # Need server running?
    tags: list[str] = field(default_factory=list)  # ["ingest", "llm"]
```

### 3.2 TestFile (Data Model)

```python
@dataclass
class TestFile:
    """A generated pytest test file."""
    path: Path                             # tests/scenarios/test_15_*.py
    content: str                           # Full file content
    scenario: Scenario                     # Source scenario
    imports: list[str] = field(default_factory=list)   # Required imports
    fixtures: list[str] = field(default_factory=list)  # Required fixtures
    marker: str = ""                       # @pytest.mark.llm
```

### 3.3 Discoverer

**Responsibility**: Find testable scenarios in the project.

**Three discovery modes**:

| Source | Method | Use Case |
|---|---|---|
| TUTORIAL.md | Markdown section parsing | High-level scenarios |
| README.md | Feature list extraction | Smoke tests |
| Source code | AST analysis | API coverage tests |
| examples/ | Directory walk | Run-through tests |

**TUTORIAL parsing** (illustrative):
```python
# Parse "## Scenario 1: Personal Reading Notes" sections
# Extract: title, background, steps, expected outcome
# Return as Scenario objects
```

**Source code parsing**:
```python
# Walk AST of all .py files
# Find public functions (not starting with _)
# Extract docstring as description
# Determine if LLM-required based on name/content
```

### 3.4 Generator

**Responsibility**: Generate pytest test code using LLM.

**Generation prompt structure**:
1. **System context**: "You are a senior Python test engineer"
2. **Project info**: name, existing test pattern
3. **Scenario**: description, background, steps, expected outcome
4. **Code context**: relevant source code
5. **Output format**: Python code only, no explanations

**Code extraction**:
```python
import re
match = re.search(r"```python\n(.*?)\n```", llm_output, re.DOTALL)
return match.group(1) if match else llm_output
```

**Test file assembly**:
1. Generate imports based on what's used
2. Add module docstring
3. Add test class with class docstring
4. Add test methods with docstrings
5. Add fixtures if needed

### 3.5 Fixer

**Responsibility**: Repair failing tests autonomously.

**Fix loop**:
```
for attempt in range(max_retries):
    result = runner.run([test])
    if result.failed == 0:
        return test
    
    for failure in result.failures:
        fixed = fixer.fix(test.content, failure)
        test = TestFile(content=fixed, ...)
    
return test
```

**Fix prompt**:
1. Original test code
2. Error type and message
3. Full traceback
4. Related source code
5. Instruction: minimal change, preserve intent

**Limits**:
- `max_retries`: 3 (configurable)
- After max retries: return current state, escalate to human
- Each fix counted for metrics

### 3.6 Docker Runner

**Responsibility**: Execute tests in real Docker environment.

**Execution flow**:
```
1. Copy test files to project/tests/
2. Set environment variables (LLM_API_KEY, SERVER_URL)
3. Run: docker compose --profile full up --abort-on-container-exit
4. Wait for completion
5. Parse test-results/junit.xml
6. Return TestResult with failures
```

**TestResult structure**:
```python
@dataclass
class TestResult:
    passed: int
    failed: int
    skipped: int
    errors: int
    total: int
    duration: float
    failures: list[TestFailure]
    raw_output: str
    junit_xml_path: Optional[Path]
```

**Failure parsing** (from JUnit XML):
```xml
<testcase name="test_X" classname="...">
  <failure type="AssertionError" message="...">
    Traceback...
  </failure>
</testcase>
```

### 3.7 Agent (Orchestrator)

**Responsibility**: Coordinate the full workflow.

**Main APIs**:

| API | Purpose | Returns |
|---|---|---|
| `generate(description)` | From natural language | `TestFile` |
| `auto_from_tutorial(path)` | From TUTORIAL.md | `list[TestFile]` |
| `auto_from_source(src_dir)` | From source AST | `list[TestFile]` |
| `run_with_fix(test_file)` | Run + auto-fix loop | `(TestFile, TestResult)` |
| `nightly_job()` | CI scheduled task | `dict` report |

**CI integration**:
- Trigger: GitHub Actions schedule (nightly)
- Action: discover → generate → run → PR if new tests
- Review: human reviews PR before merge

### 3.8 LLM Client

**Responsibility**: Abstract LLM provider.

**Provider interface**:
```python
class LLMClient(ABC):
    @abstractmethod
    def chat(self, prompt: str, **kwargs) -> str: ...
    
    @abstractmethod
    def chat_json(self, prompt: str, schema: dict) -> dict: ...
```

**Supported providers** (v0.1):
- `minimax` (default for llmwikify)
- `openai` (generic OpenAI-compatible)
- `mock` (for testing framework itself)

**Provider-agnostic config**:
```yaml
llm:
  provider: minimax
  model: minimax-M3
  api_key: ${LLM_API_KEY}
  base_url: ${LLM_BASE_URL}
```

## 4. CLI Design

### 4.1 Commands

```bash
# From natural language description
ai-test generate "test wiki init and FTS5 search"

# From TUTORIAL.md batch
ai-test from-tutorial docs/TUTORIAL.md -o tests/auto/

# From source code (API coverage)
ai-test from-source src/llmwikify -o tests/api/

# Run specific test with auto-fix
ai-test run tests/scenarios/test_new.py --auto-fix --max-retries 3

# Discover scenarios only
ai-test discover --tutorial docs/TUTORIAL.md

# CI mode (discover + generate + run)
ai-test ci --report ci-report.md

# Generate coverage gap report
ai-test coverage-gap --source src/ --tests tests/

# Initialize framework in a project
ai-test init  # Creates .ai-test.yaml config
```

### 4.2 Configuration (`.ai-test.yaml`)

```yaml
llm:
  provider: minimax
  model: minimax-M3
  base_url: ${LLM_BASE_URL}
  api_key: ${LLM_API_KEY}

docker:
  compose_path: docker-tests/docker-compose.yml
  timeout: 600

generator:
  max_retries: 3
  temperature: 0.3
  existing_test_pattern: tests/scenarios/test_01_wiki_core.py

runner:
  profile: full  # or "standalone"
  output_dir: test-results

discoverer:
  sources:
    - docs/TUTORIAL.md
    - docs/README.md
    - examples/
  
fixer:
  enabled: true
  max_retries: 3
```

## 5. Project Structure

```
ai-test-framework/                      # Standalone Python package
├── pyproject.toml
├── README.md
├── LICENSE
├── src/ai_test_framework/
│   ├── __init__.py
│   ├── cli.py                         # Click CLI
│   ├── agent.py                       # Main orchestrator
│   ├── generator.py                   # Test generation
│   ├── runner.py                      # Docker execution
│   ├── fixer.py                       # Auto-fix failures
│   ├── discoverer.py                  # Scenario discovery
│   ├── llm.py                         # LLM abstraction
│   ├── models.py                      # Data models
│   ├── prompts.py                     # Prompt templates
│   └── utils.py                       # Helpers
├── templates/
│   ├── pytest_test.py.j2             # Test file template
│   ├── conftest.py.j2                # conftest template
│   └── fixtures.py.j2                # Fixtures template
├── examples/
│   ├── llmwikify_demo/                # Demo with llmwikify
│   │   ├── ai_test_demo.py
│   │   ├── .ai-test.yaml
│   │   └── README.md
│   └── basic_python/                  # Generic Python project
│       ├── ai_test_demo.py
│       └── README.md
├── tests/
│   ├── test_generator.py
│   ├── test_fixer.py
│   ├── test_discoverer.py
│   ├── test_runner.py
│   └── test_agent.py
└── docs/
    ├── design.md                      # This document
    ├── user-guide.md
    └── api-reference.md
```

## 6. Integration with Docker Test System

The ATF reuses the Docker test system (Part 1) as its execution backend:

```
AI Test Framework                 Docker Test System
─────────────────                 ─────────────────
                                                    
generator.py ─→ TestFile ─→ runner.py ─→ docker compose ─→ tests run
                                          │               
                                          ↓               
                                     JUnit XML            
                                          │               
                  fixer.py ← TestFailure                   
```

**Key integration points**:
1. `DockerTestRunner` in ATF wraps `docker compose` commands from Part 1
2. Test results parsed from `test-results/junit.xml` (generated by Part 1)
3. Same `docker-tests/Dockerfile` and `docker-tests/docker-compose.yml` used
4. Same environment variables (LLM_API_KEY, SERVER_URL, etc.)

## 7. Implementation Plan

### 7.1 Phase Breakdown

| Phase | Component | Deliverable | Time |
|---|---|---|---|
| **B1** | Project skeleton + CLI | `ai-test-framework/` package with Click CLI | 3h |
| **B2** | Generator + LLM integration | `generator.py` + `llm.py` + 2 providers | 4h |
| **B3** | Docker Runner | `runner.py` wraps Part 1 docker compose | 2h |
| **B4** | Fixer + auto-fix loop | `fixer.py` + retry logic | 3h |
| **B5** | Discoverer (4 sources) | `discoverer.py` parsing TUTORIAL/README/code/examples | 3h |
| **B6** | Agent + CI integration | `agent.py` + nightly workflow | 2h |
| **B7** | Documentation + demos | README, examples, docs/ | 2h |
| **Total** | | | **19h** |

### 7.2 Dependencies

| Dependency | Version | Purpose |
|---|---|---|
| click | >=8.0 | CLI framework |
| openai | >=1.0 | LLM client (OpenAI-compatible) |
| pydantic | >=2.0 | Data validation |
| pyyaml | >=6.0 | Config file |
| jinja2 | >=3.0 | Template rendering |
| docker | >=6.0 | Docker SDK (optional) |
| pyyaml | >=6.0 | YAML parsing |

### 7.3 Testing Strategy

**Framework self-tests**:
- `test_generator.py`: Mock LLM, verify prompt structure
- `test_fixer.py`: Mock failure, verify fix prompt
- `test_discoverer.py`: Fixture TUTORIAL, verify extraction
- `test_runner.py`: Mock subprocess, verify docker call
- `test_agent.py`: End-to-end with mock LLM

**Integration test**:
- Use llmwikify as integration test target
- Generate tests for simple scenario (init wiki)
- Verify they actually run in Docker

## 8. Risk Analysis

| Risk | Impact | Probability | Mitigation |
|---|---|---|---|
| AI generates low-quality tests | Wasted CI time, false confidence | High | Mandatory human review before merge |
| Auto-fix loops infinitely | CI hangs | Medium | Max retries (3), timeout, escalation |
| LLM API costs | High CI bills | Medium | Cache results, rate limiting, local LLM option |
| Generated tests unstable | Flaky CI | High | Mark AI-generated tests separately, quarantine |
| Prompt injection | Security risk | Low | Sandbox LLM, validate generated code |
| LLM provider changes | Breaking | Medium | Abstract LLM behind interface |

## 9. Success Metrics

### 9.1 Quantitative

| Metric | Target | Measurement |
|---|---|---|
| Test generation success rate | >90% tests pass first time | CI metrics |
| Auto-fix success rate | >70% failures fixed within 3 retries | CI metrics |
| Time saved per new scenario | >80% reduction | Manual comparison |
| API coverage | >90% of public functions have tests | Coverage report |
| False positive rate | <5% | Manual review of generated tests |

### 9.2 Qualitative

- New contributors can use ATF to bootstrap their tests
- Documentation stays in sync with tests automatically
- CI provides actionable insights, not just pass/fail
- ATF can be applied to other projects with minimal config

## 10. Open Questions

### 10.1 Architecture
- [ ] Should ATF be a standalone PyPI package or llmwikify submodule?
- [ ] Should it support non-Python projects in v0.1?
- [ ] How to handle project-specific test patterns? (Plugin system?)

### 10.2 Autonomy
- [ ] Should ATF auto-merge generated tests in CI? (Risk vs velocity)
- [ ] Should it learn from user modifications to generated tests?
- [ ] What's the right human-in-the-loop balance?

### 10.3 Integration
- [ ] How does ATF interact with pytest fixtures system?
- [ ] Should it generate conftest.py files automatically?
- [ ] How to handle test data (PDFs, fixtures)?

### 10.4 Quality
- [ ] What's the minimum coverage threshold for auto-merge?
- [ ] Should we have a "AI confidence score" for generated tests?
- [ ] How to detect and reject malicious/harmful generated tests?

## 11. Future Roadmap

### v0.1 (MVP, 2-3 days)
- Basic Generator + LLM integration
- Docker Runner (uses Part 1)
- CLI: generate, run, discover
- Single project support (llmwikify)

### v0.2 (1 week)
- Fixer with auto-retry
- Discoverer (TUTORIAL + source)
- Configuration file (.ai-test.yaml)
- Templates (jinja2)

### v0.3 (2 weeks)
- Agent orchestration
- CI integration (nightly)
- Coverage gap analysis
- Multi-project support

### v1.0 (1 month)
- PyPI release
- Plugin system
- Web UI for reviewing generated tests
- Learning from user feedback
- Multi-language support (JS, Go)

## 12. References

- [llmwikify TUTORIAL.md](../TUTORIAL.md) - Target documentation
- [Docker Test System Plan](./DOCKER_TESTS_PLAN.md) - Part 1 (companion document)
- [Playwright](https://playwright.dev/) - Inspiration for E2E test automation
- [SWE-bench](https://www.swebench.com/) - Inspiration for AI test generation
- [Anthropic Claude Tool Use](https://docs.anthropic.com/claude/docs/tool-use) - Inspiration for agent design

## 13. Discussion

This document is open for discussion. Please add comments, questions, and suggestions as GitHub issues or in the discussion thread.

Key discussion topics:
1. **Scope**: Is v0.1 scope appropriate? What to defer?
2. **Autonomy**: How much should AI do autonomously vs human review?
3. **Quality gates**: What's the minimum bar for auto-generated tests?
4. **Project structure**: Standalone package vs submodule?
5. **LLM choice**: Default to minimax or OpenAI?
6. **Integration**: How to handle existing test suites?
