#!/bin/bash
# docker-tests/e2e-entrypoint.sh
# Dynamic installer + test runner for the generic e2e image.
#
# The container runs as a non-root user (e2euser, uid 1000). The
# system site-packages are owned by root, so a plain ``pip install``
# would silently fall back to ``--user`` and drop ``llmwikify`` into
# ``/home/e2euser/.local/bin/`` - which is NOT on PATH. To keep the
# console entry point visible to every child process, we create a
# throw-away venv at /app/venv and source it before running tests.
#
# Env:
#   PIP_PACKAGES      - space-separated pip install list
#   TEST_SCRIPT       - command to exec after install
#   LLMWIKIFY_VERSION - if set AND PIP_PACKAGES contains "llmwikify",
#                       pin to that version
#   IN_DOCKER         - always "1" inside this container (set by us)

set -e

VENV=/app/venv

echo "=========================================="
echo " llmwikify e2e runner (generic)"
echo "=========================================="
echo " Python:  $(python3 --version 2>&1)"
echo " pip:     $(pip3 --version 2>&1)"
echo " Date:    $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo " User:    $(id -un) (uid=$(id -u))"
echo " CWD:     $(pwd)"
echo " PIP:     ${PIP_PACKAGES:-(none)}"
echo " VERSION: ${LLMWIKIFY_VERSION:-(unpinned)}"
echo " SCRIPT:  ${TEST_SCRIPT:-(none)}"
echo "=========================================="

# 1. venv (idempotent - reuse if cached in the image layer)
if [ ! -d "$VENV" ]; then
    echo
    echo "▶ Creating venv at $VENV"
    python3 -m venv "$VENV"
fi

# 2. Activate venv (puts $VENV/bin first on PATH, exposes pip/python)
# shellcheck disable=SC1091
source "$VENV/bin/activate"
echo "▶ venv: $VENV (python $(python --version 2>&1))"

# Tell downstream e2e scripts they're in a container.
export IN_DOCKER=1

# 3. pip install (with optional version pin)
if [ -n "${PIP_PACKAGES:-}" ]; then
    actual="$PIP_PACKAGES"

    if [ -n "${LLMWIKIFY_VERSION:-}" ]; then
        if echo "$actual" | grep -qE '(^|\s)llmwikify(\[|==|\s|$)'; then
            pinned="llmwikify==${LLMWIKIFY_VERSION}"
            actual=$(echo "$actual" | sed -E "s/llmwikify(\[[^]]+\])?/${pinned}\1/g")
            echo "▶ Pinned llmwikify to ${LLMWIKIFY_VERSION}"
        fi
    fi

    echo
    echo "▶ Installing: $actual"
    # Use -- to stop option parsing, then quote $actual to prevent
    # glob expansion of [] in extras like "llmwikify[web,mcp]".
    #
    # --no-deps is intentional: the published 0.38.0 pyproject pins
    # ``keyring<24`` for the jaraco.functools 1.x workaround, which
    # conflicts with mcp 1.28's transitive dep on keyring>=25.6. We
    # install llmwikify without resolving its deps, then explicitly
    # install a known-good dep set below. This makes the e2e test
    # reproducible across keyring / jaraco changes.
    #
    # 600s timeout: markitdown[all] / pymupdf wheels are large
    # (~100MB) and slow on some networks. Default pip timeout (15s) is
    # too aggressive.
    if echo "$actual" | grep -qE 'llmwikify.*\.whl'; then
        echo "  (local wheel detected, installing --no-deps)"
        # Use array form so multiple packages in $actual stay separate
        # args. Quoting "$actual" as one string would conflate them.
        # shellcheck disable=SC2206
        pkgs=($actual)
        pip install --no-cache-dir --no-deps --timeout 600 "${pkgs[@]}"
        # Then install the minimal extra deps for [web,mcp] manually
        pip install --no-cache-dir --timeout 600 \
            'jinja2>=3.1.0' 'pyyaml>=6.0' 'requests>=2.28.0' \
            'duckdb>=1.0.0' 'pyjwt>=2.0,<3' \
            'fastapi>=0.104.0' 'starlette>=0.27.0' \
            'uvicorn>=0.23.0' 'httpx>=0.24.0' \
            'fastmcp>=3.0.0' 'tiktoken>=0.7.0' \
            'rich>=13' 'rich-rst' 'cyclopts>=4.0' \
            'pydantic-settings>=2.0' 'joserfc>=1.0' \
            'pyperclip'
    else
        # shellcheck disable=SC2206
        pkgs=($actual)
        pip install --no-cache-dir --timeout 600 "${pkgs[@]}"
    fi
    echo "✅ pip install done"
else
    echo
    echo "▶ No PIP_PACKAGES set, skipping install"
fi

# 4. Sanity check - is llmwikify now in PATH?
if command -v llmwikify &>/dev/null; then
    echo
    echo "▶ llmwikify: $(llmwikify --version 2>&1 | head -1)"
else
    echo
    echo "⚠️  llmwikify not in PATH after install (check PIP_PACKAGES)"
fi

# 5. Run the test script
if [ -n "${TEST_SCRIPT:-}" ]; then
    echo
    echo "▶ Running: $TEST_SCRIPT"
    echo "------------------------------------------"
    exec bash -c "$TEST_SCRIPT"
fi

# 6. Fallback: drop to shell
echo
echo "▶ No TEST_SCRIPT set, dropping to shell"
exec "$@"
