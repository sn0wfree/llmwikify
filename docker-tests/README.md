# Docker Test Environment

Run llmwikify scenario tests in Docker containers for reproducible CI/CD
and local development.

## Quick Start

### P2: Dual Container (Recommended)

Run server + test containers together using Docker Compose:

```bash
# One command: build + run server + run tests
./docker-tests/run-compose.sh

# With LLM key (auto-detected from ~/.llmwikify/llmwikify.json)
export LLM_API_KEY=sk-xxx
./docker-tests/run-compose.sh

# Run with custom Python version
./docker-tests/run-compose.sh --py 3.12

# Keep wiki data after tests (for debugging)
./docker-tests/run-compose.sh --keep-volumes
```

### P1: Single Container (No Server)

Run tests only (server-dependent tests will fail):

```bash
./docker-tests/run.sh --build
```

## Architecture

### P2: Dual Container (docker-compose.yml)

```
┌─────────────────────────────────┐
│  docker-tests network           │
│  ┌───────────────────────────┐  │
│  │  server (long-running)    │  │
│  │  - Port: 8765             │  │
│  │  - Health: /api/health    │  │
│  │  - Volume: wiki-data      │  │
│  └───────────────────────────┘  │
│             ▲                   │
│             │ depends_on        │
│             │ service_healthy   │
│  ┌───────────────────────────┐  │
│  │  test (short-lived)       │  │
│  │  - Runs pytest            │  │
│  │  - Exits after tests      │  │
│  └───────────────────────────┘  │
└─────────────────────────────────┘
```

**Key Features:**
- Server starts first, health-checked before tests run
- Tests use `SERVER_URL=http://server:8765` via Docker DNS
- Wiki data persists in Docker volume (optional cleanup)

### P1: Single Container

```
┌─────────────────────────────┐
│  test container             │
│  - No server running        │
│  - Server tests fail        │
│  - Fast for non-server tests│
└─────────────────────────────┘
```

## Scripts

| Script | Purpose |
|---|---|
| `run-compose.sh` | **P2**: Run server + test containers |
| `run.sh` | **P1**: Run tests only (no server) |
| `server-entrypoint.sh` | Server container entry point |
| `entrypoint.sh` | Test container entry point |

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `LLM_API_KEY` | (required for LLM tests) | API key for LLM provider |
| `LLM_PROVIDER` | `minimax` | LLM provider name |
| `LLM_MODEL` | `minimax-M3` | LLM model name |
| `LLM_BASE_URL` | `https://api.minimaxi.com/v1` | LLM API base URL |
| `SERVER_URL` | `http://localhost:8765` (P1) / `http://server:8765` (P2) | Server URL |
| `AUTH_TOKEN` | (empty) | Bearer token for server auth |
| `TZ` | `UTC` | Timezone |

## Test Behavior

- **No `LLM_API_KEY`**: LLM-marked tests are auto-skipped, others run
- **With `LLM_API_KEY`**: All tests run (76 tests total)
- **P1 (no server)**: Server-dependent tests fail (8 tests in test_04, test_12)
- **P2 (with server)**: All tests pass
- **Output**: JUnit XML written to `/app/test-results/junit.xml`

## Test Results

| Mode | Passed | Skipped | Failed |
|---|---|---|---|
| P2 + LLM key | 76 | 0 | 0 |
| P2 no LLM key | 52 | 24 | 0 |
| P1 + LLM key | 68 | 0 | 8 (server tests) |
| P1 no LLM key | 44 | 24 | 8 (server tests) |

## Commands Reference

```bash
# Full integration (P2 recommended)
./docker-tests/run-compose.sh

# Run server only (for debugging)
./docker-tests/run-compose.sh --profile server

# Skip image rebuild
./docker-tests/run-compose.sh --no-build

# Keep wiki data after tests
./docker-tests/run-compose.sh --keep-volumes

# Run specific tests
docker compose -f docker-tests/docker-compose.yml --profile full up
# Then in test container:
docker exec llmwikify-tests pytest tests/scenarios/test_01_wiki_core.py -v

# Run tests only without server (P1)
./docker-tests/run.sh

# Skip LLM tests
./docker-tests/run.sh -- -m "not llm"
```

## Multi-Python Support

```bash
# Build images for specific Python version
docker build --build-arg PYTHON_VERSION=3.12 \
    -f docker-tests/Dockerfile \
    -t llmwikify-test:py3.12 .

docker build --build-arg PYTHON_VERSION=3.12 \
    -f docker-tests/Dockerfile.server \
    -t llmwikify-server:py3.12 .
```

## Image Structure

### Test Image (Dockerfile)

- **Base**: `python:3.11-slim`
- **User**: `testuser` (UID 1000, non-root)
- **Workdir**: `/app`
- **Entrypoint**: `tini` + `entrypoint.sh`
- **Size**: ~1GB

### Server Image (Dockerfile.server)

- **Base**: `python:3.11-slim`
- **User**: `llmuser` (UID 1000, non-root)
- **Workdir**: `/app`
- **Entrypoint**: `tini` + `server-entrypoint.sh`
- **Healthcheck**: `curl -f http://localhost:8765/api/health`
- **Size**: ~940MB
- **Note**: Reproduction routes disabled (missing QuantNodes dependency)

## Troubleshooting

**Tests fail with "Connection refused"**
→ Run with P2 (docker-compose) which starts server automatically.
Or start server manually before running P1 tests.

**Container exits with code 1**
→ Check `/app/test-results/junit.xml` for failure details

**Permission denied on volume mount**
→ Containers run as UID 1000. Ensure host dir is writable.

**Reproduction routes return 404**
→ Expected when QuantNodes is not installed (private package).
Routes are automatically disabled.

**Build timeout on pip install**
→ Network issues with mirrors. Retry or use `--no-build` with existing images.

## Next Steps

- P3: GitHub Actions CI integration
- P4: AI test generation framework
