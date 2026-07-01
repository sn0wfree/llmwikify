# Docker Test Environment

Run llmwikify scenario tests in a Docker container for reproducible CI/CD
and local development.

## Quick Start

```bash
# One command: build + run
./docker-tests/run.sh --build

# With LLM key (auto-detected from ~/.llmwikify/llmwikify.json)
export LLM_API_KEY=sk-xxx
./docker-tests/run.sh

# Run with custom Python version
./docker-tests/run.sh --py 3.12

# Run specific test
./docker-tests/run.sh -- tests/scenarios/test_01_wiki_core.py

# Or manually:
docker build -f docker-tests/Dockerfile -t llmwikify-test .
docker run --rm \
    -e LLM_API_KEY="$LLM_API_KEY" \
    -v $(pwd)/docker-tests/test-results:/app/test-results \
    llmwikify-test
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `LLM_API_KEY` | (required for LLM tests) | API key for LLM provider |
| `LLM_PROVIDER` | `minimax` | LLM provider name |
| `LLM_MODEL` | `minimax-M3` | LLM model name |
| `LLM_BASE_URL` | `https://api.minimaxi.com/v1` | LLM API base URL |
| `SERVER_URL` | `http://localhost:8765` | llmwikify server URL (for chat tests) |
| `TZ` | `UTC` | Timezone |

## Test Behavior

- **No `LLM_API_KEY`**: LLM-marked tests are auto-skipped, others run
- **With `LLM_API_KEY`**: All tests run
- **Output**: JUnit XML written to `/app/test-results/junit.xml`

## Running Specific Tests

```bash
# Run a single test file
docker run --rm -e LLM_API_KEY="$LLM_API_KEY" \
    llmwikify-test pytest tests/scenarios/test_01_wiki_core.py -v

# Run a single test function
docker run --rm -e LLM_API_KEY="$LLM_API_KEY" \
    llmwikify-test pytest tests/scenarios/test_01_wiki_core.py::TestWikiCore::test_1_1_init_wiki -v

# Skip LLM tests
docker run --rm -e LLM_API_KEY="" \
    llmwikify-test pytest tests/scenarios/ -m "not llm"
```

## Multi-Python Support

The Dockerfile accepts a `PYTHON_VERSION` build argument:

```bash
for v in 3.10 3.11 3.12; do
    docker build --build-arg PYTHON_VERSION=$v \
        -t llmwikify-test:py$v \
        -f docker-tests/Dockerfile .
done
```

## Image Structure

- **Base**: `python:3.11-slim`
- **User**: `testuser` (UID 1000, non-root)
- **Timezone**: UTC
- **Workdir**: `/app`
- **Entrypoint**: `tini` + `entrypoint.sh` (clean signal handling)
- **Output**: `/app/test-results/` (mount as volume)

## Layer Caching

The image is built in two layers for optimal caching:

1. **Dependencies layer** (rebuilt only when `pyproject.toml` changes)
2. **Code layer** (rebuilt when test files change)

This makes incremental builds fast (< 5s for code-only changes).

## Troubleshooting

**Tests fail with "LLM_API_KEY not set"**
→ Set `LLM_API_KEY` env var or accept the auto-skip behavior

**Tests fail with "Connection refused"**
→ Server is not running. Tests in `test_04_*` and `test_12_5` need a server.

**Container exits with code 1**
→ Check `/app/test-results/junit.xml` for failure details

**Permission denied on volume mount**
→ Container runs as UID 1000. Ensure host dir is writable.

## Next Steps

- P2: docker-compose with separate server + test containers
- P3: GitHub Actions CI integration
- P4+: AI test generation framework
