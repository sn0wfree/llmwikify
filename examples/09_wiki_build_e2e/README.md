# 09 — Wiki Build End-to-End

> **Goal**: A single command that exercises the full install → wiki build →
> chat SSE → agent path, in a **generic Python container** that contains
> nothing project-specific.

This playbook exists to make the first 10 minutes of llmwikify **reproducible**
for a brand-new user. It runs 4 scripts in order and exits non-zero on the
first failure, so it can be wired into CI or used as a smoke test before
release.

---

## Why this exists

A user audit (v0.38, 2026-07) found that someone who just `git clone`d the
repo would hit **3 documented failure paths** before doing anything useful,
despite the underlying code being deeply functional (32 CLI commands, 8
playbooks, FTS5 + graph + MCP all working). The gap was in **discoverability
and first-run guidance**.

This playbook fixes that. It assumes nothing about the host except:

* `python3.10+` is available
* `docker` is available
* outbound HTTPS to `pypi.org` and `files.pythonhosted.org` works

---

## The 4 scripts

Run in this order; each exits 0 on success:

| # | Script | What it does | Works without LLM? | Works without agent? |
|---|--------|--------------|---------------------|----------------------|
| 00 | `00_install_check.py` | Verify Python, llmwikify import, CLI on PATH, [web/mcp] extras, doctor | **yes** | **yes** |
| 01 | `01_cli_only.py` | 10 core wiki CLI commands: init → ingest → write → search → build-index → references → lint → status | **yes** | **yes** |
| 02 | `02_chat_sse.py` | Spawn `llmwikify serve --web`, POST to `/api/agent/chat`, parse SSE events | no (needs a working LLM key for real events) | **yes** |
| 03 | `03_agent_real.py` | If `opencode` / `claude` / `codex` is on PATH, verify `init --agent <X>` writes the right config files | **yes** | no (graceful skip) |

`scripts/run_all.sh` chains all four and bails on the first failure.

---

## Quick start

### Run locally (host)

```bash
pip install 'llmwikify[extractors,web]' httpx
python examples/09_wiki_build_e2e/scripts/run_all.sh
```

`00` should report **7/7 passed** and the chain should finish with **all
green**. `02` and `03` will print `[SKIP]` if no LLM key / no agent CLI is
available — they do not block.

### Run in a generic Docker container (recommended for CI)

```bash
# 1. Build the local wheel (one time)
python -m build

# 2. Run the whole chain in the generic python-e2e-runner image
./docker-tests/run-e2e.sh
```

`run-e2e.sh` will:

1. `docker build` the **generic** `python-e2e-runner:py3.11` image
   (no llmwikify, no source, no test scripts - just `python + pip + tini + curl + git + bash`).
2. Mount `dist/`, `examples/`, and the test results dir.
3. `docker run` with `PIP_PACKAGES` pointing at the local wheel and
   `TEST_SCRIPT` pointing at `run_all.sh`.
4. The entrypoint creates a venv, `pip install`s the wheel + minimal
   `[web,mcp]` deps, then exec's the test chain.

To pin a specific llmwikify version:

```bash
LLMWIKIFY_VERSION=0.38.0 ./docker-tests/run-e2e.sh
```

To use the **PyPI version** instead of the local wheel (will install
whatever pip resolves, which may be 0.30.0 due to the jaraco pin
workaround — see "Known issues" below):

```bash
PIP_PACKAGES="llmwikify[web,mcp] httpx" ./docker-tests/run-e2e.sh
```

To pass an LLM key (for the `02` step to produce real SSE events):

```bash
./docker-tests/run-e2e.sh --llm-key sk-xxx
```

---

## What's inside

```
examples/09_wiki_build_e2e/
├── README.md                          ← you are here
├── fixtures/
│   ├── sample-1.md                    (Karpathy "LLM-Native Wiki" excerpt)
│   └── sample-2.md                    (Andrew Ng "Bidirectional Refs" excerpt)
└── scripts/
    ├── _lib.py                        (shared helpers: cli(), WIKI_ROOT, AUTH_TOKEN, IN_DOCKER)
    ├── 00_install_check.py            (Python + llmwikify + extras + doctor)
    ├── 01_cli_only.py                 (10-step CLI smoke test)
    ├── 02_chat_sse.py                 (server + chat + SSE event parse)
    ├── 03_agent_real.py               (opencode / claude / codex discovery)
    └── run_all.sh                     (00 → 01 → 02 → 03 chain)
```

```
docker-tests/
├── Dockerfile.e2e-runner              (generic python + pip image, ~200MB)
├── e2e-entrypoint.sh                  (dynamic venv + pip install + exec test)
└── run-e2e.sh                         (host-side wrapper)
```

---

## Expected output

A successful run (with a working LLM key) ends with:

```
============================================================
  03 agent: 4/4 passed, 0 failed
============================================================

==========================================
 All 4 e2e scripts passed.
==========================================
```

If you do **not** have a working LLM key, `02` will pass (the server streams
3 events: `session_created`, `error` from a 401, and `done`) but the script
will note the LLM error in the step-5 classification. The chain still exits
0 — the test verifies the **wire format**, not the LLM quality.

If you do **not** have an agent CLI installed, `03` will print `[SKIP] agent
CLI present` and exit 0.

---

## Why a generic container?

The image is **200MB** and contains only:

* `python3.11-slim`
* `tini` (proper init, clean SIGTERM)
* `curl` (health check)
* `git` (for sdist / git+https installs)
* `bash` (entrypoint)

It does **not** contain:

* llmwikify
* test scripts
* project source
* project data

Everything is mounted or installed at runtime via `PIP_PACKAGES` +
`TEST_SCRIPT` env vars. This means:

* One image can test **any** project, not just llmwikify
* `pip install` failures don't pollute the image layer
* You can pin a different llmwikify version per run with `LLMWIKIFY_VERSION`

---

## Dual-habitat: same scripts run locally and in Docker

Each script imports `_lib.py`, which reads three env vars:

| Env var | Host default | Container default |
|---------|--------------|-------------------|
| `IN_DOCKER` | unset (= 0) | `1` (set by entrypoint) |
| `WIKI_ROOT` | `tempfile.mkdtemp(...)` | same (or set by user) |
| `AUTH_TOKEN` | `demo-token` | `demo-token` |
| `SERVER_PORT` | `8765` | `8765` |

When `IN_DOCKER=0`, scripts use `python -m llmwikify` (works on a dev
checkout). When `IN_DOCKER=1` and `llmwikify` is on PATH, they use the
console entry point. The entrypoint sources `/app/venv/bin/activate` so
the console entry point is on PATH inside the container.

This means **the same script file works on both** a developer's laptop and
inside the generic runner. No need to maintain two copies.

---

## Known issues

### 1. PyPI pip resolution can fall back to llmwikify 0.30.0

`pyproject.toml` pins `keyring<24,>=21.2.0` as a workaround for the
`jaraco.functools 1.x` metadata bug. This conflicts with the latest
`py-key-value-aio`'s `keyring>=25.6.0` requirement, so a bare
`pip install llmwikify[web,mcp]` against PyPI may resolve to **0.30.0**
(the last version published before the pin).

**Workaround**: use the **local wheel** instead of `pip install
llmwikify` from PyPI. `run-e2e.sh` does this by default when `dist/`
exists.

### 2. `[extractors]` is heavy

`markitdown[all]` is ~200MB to download (audio, image, PDF extras).
**Step 00** therefore marks `markitdown` as **optional** — it does not
fail the e2e chain if missing. Run `00` with `llmwikify[extractors]`
explicitly if you want to verify that path.

### 3. Cold pip install takes ~3 min

The first `run-e2e.sh` invocation downloads ~50 wheels (fastmcp, mcp,
duckdb, pydantic, ...). Subsequent runs in the **same** image cache
the venv, but a fresh image re-downloads everything.

If you want a faster image, see the [fast variant recipe](#fast-variant).

---

## Fast variant (pre-baked venv)

If cold installs are too slow, build a venv into the image:

```bash
# Build venv on the host
python3.11 -m venv /tmp/llmwikify-venv
source /tmp/llmwikify-venv/bin/activate
pip install 'llmwikify[web,mcp]' httpx

# Build a fat image with the venv baked in
docker build -t python-e2e-runner:fat -f- . <<'EOF'
FROM python:3.11-slim
COPY --from=python-e2e-runner:py3.11 /app/entrypoint.sh /app/entrypoint.sh
COPY --chown=root /tmp/llmwikify-venv /app/venv
ENV PATH=/app/venv/bin:$PATH
RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
EOF
```

This is **not** the default — the user explicitly asked for a generic
image with install-at-runtime.

---

## Wiring into CI

Add a job to `.github/workflows/e2e.yml`:

```yaml
name: E2E
on: [push, pull_request]
jobs:
  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.11"}
      - run: pip install build
      - run: python -m build
      - run: ./docker-tests/run-e2e.sh
```

The first run will take ~3 min (cold install). Cache the docker image
between runs to bring it down to ~30s:

```yaml
      - run: docker load < llmwikify-e2e.tar || true
      - run: docker build -f docker-tests/Dockerfile.e2e-runner -t python-e2e-runner:py3.11 .
      - run: docker save python-e2e-runner:py3.11 > llmwikify-e2e.tar
      - uses: actions/cache@v4
        with:
          path: llmwikify-e2e.tar
          key: docker-${{ runner.os }}-py3.11
      - run: ./docker-tests/run-e2e.sh
```

---

## See also

* `docs/USAGE_MODES.md` — when to use the **agent** path vs the **LLM**
  path; this playbook exercises both.
* `examples/01_personal_reading_notes/` — a manual walkthrough of
  scenario 1 (PDF → wiki), no LLM needed.
* `examples/04_chat_sse_client/` — the same SSE event flow exercised
  manually, with a long-running server.

---

*Last updated: 2026-07-02 · Version: 0.38.0 · Container: 227MB*
