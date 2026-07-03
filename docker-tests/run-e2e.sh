#!/bin/bash
# docker-tests/run-e2e.sh
# Run the 4-script e2e suite inside the generic python-e2e-runner image.
#
# The image is **generic**: it contains only Python + pip + tini + curl + git
# + bash. No project code, no project deps. At container start, the
# entrypoint:
#   1. creates a venv at /app/venv
#   2. activates it
#   3. pip installs PIP_PACKAGES (default: the local wheel + httpx)
#   4. exec's TEST_SCRIPT (default: run_all.sh)
#
# Default behaviour:
#   - builds the local wheel if dist/ is missing
#   - builds the image if it doesn't exist
#   - runs the whole 00 -> 03 chain
#
# Environment variables:
#   PIP_PACKAGES       - space-separated pip install list (default below)
#   TEST_SCRIPT        - command to run (default: run_all.sh)
#   LLMWIKIFY_VERSION  - if set, pin llmwikify to this version
#   LLM_API_KEY        - passed to container as LLM_API_KEY
#   PYTHON_VERSION     - python image tag (default: 3.11)
#   SKIP_BUILD         - if 1, don't rebuild the image
#   KEEP_CONTAINER     - if 1, don't --rm the container
#   NO_WHEEL           - if 1, use PIP_PACKAGES from PyPI (don't mount dist/)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

PYTHON_VERSION="${PYTHON_VERSION:-3.11}"
IMAGE="python-e2e-runner:py${PYTHON_VERSION}"
SKIP_BUILD="${SKIP_BUILD:-0}"
NO_WHEEL="${NO_WHEEL:-0}"
KEEP_CONTAINER="${KEEP_CONTAINER:-0}"

print_usage() {
    cat <<EOF
Usage: $0 [options]

Options:
  --py VERSION       Python image tag (default: 3.11)
  --llm-key KEY      Pass LLM_API_KEY=KEY to the container
  --no-build         Skip rebuilding the docker image
  --no-wheel         Don't use the local wheel (install from PyPI instead)
  --keep             Don't --rm the container (debug with docker exec)
  --help             Show this help

Examples:
  $0                                  # default: local wheel + run_all.sh
  $0 --no-wheel                       # use PyPI llmwikify[web,mcp]
  $0 --llm-key sk-xxx                 # pass an LLM key
  $0 --no-build                       # reuse existing image
  $0 --py 3.12                        # use python:3.12-slim

Environment:
  PIP_PACKAGES       space-separated pip install list
                     (default: '<dist>/llmwikify-0.38.0-py3-none-any.whl httpx')
  TEST_SCRIPT        command to exec (default: 'python3 /app/examples/09_wiki_build_e2e/scripts/run_all.sh')
  LLMWIKIFY_VERSION  if set, pin llmwikify to this version
  LLM_API_KEY        LLM key to pass through (or use --llm-key)
EOF
}

# --- parse args ---
LLM_KEY="${LLM_API_KEY:-}"
while [[ $# -gt 0 ]]; do
    case $1 in
        --py)         PYTHON_VERSION="$2"; shift 2 ;;
        --llm-key)    LLM_KEY="$2"; shift 2 ;;
        --no-build)   SKIP_BUILD=1; shift ;;
        --no-wheel)   NO_WHEEL=1; shift ;;
        --keep)       KEEP_CONTAINER=1; shift ;;
        --help|-h)    print_usage; exit 0 ;;
        *) echo "Unknown option: $1"; print_usage; exit 1 ;;
    esac
done

IMAGE="python-e2e-runner:py${PYTHON_VERSION}"

# --- auto-detect LLM key from host config if not given ---
if [ -z "$LLM_KEY" ] && [ -f "$HOME/.llmwikify/llmwikify.json" ]; then
    LLM_KEY=$(python3 -c \
        "import json; print(json.load(open('$HOME/.llmwikify/llmwikify.json'))['llm']['api_key'])" \
        2>/dev/null || echo "")
    if [ -n "$LLM_KEY" ]; then
        echo "▶ LLM_API_KEY auto-loaded from ~/.llmwikify/llmwikify.json"
    fi
fi

# --- decide what to install ---
if [ "$NO_WHEEL" = "1" ]; then
    PIP_PACKAGES="${PIP_PACKAGES:-llmwikify[web,mcp] httpx}"
    WHEEL_VOL=""
    echo "▶ Using PIP_PACKAGES from env (no local wheel): $PIP_PACKAGES"
else
    # Build the wheel if needed
    if [ ! -f "$PROJECT_ROOT/dist/llmwikify-"*.whl ]; then
        echo "=== Building local wheel ==="
        python3 -m pip install --quiet build
        python3 -m build 2>&1 | tail -3
    fi
    WHEEL_FILE=$(ls "$PROJECT_ROOT"/dist/llmwikify-*.whl 2>/dev/null | head -1)
    if [ -z "$WHEEL_FILE" ]; then
        echo "❌ No wheel found in dist/. Run: python -m build" >&2
        exit 1
    fi
    PIP_PACKAGES="${PIP_PACKAGES:-/app/dist/$(basename "$WHEEL_FILE") httpx}"
    WHEEL_VOL="-v $PROJECT_ROOT/dist:/app/dist"
    echo "▶ Wheel: $WHEEL_FILE"
fi

# Default test script
TEST_SCRIPT="${TEST_SCRIPT:-python3 /app/examples/09_wiki_build_e2e/scripts/run_all.sh}"

# --- build image if needed ---
if [ "$SKIP_BUILD" != "1" ]; then
    echo
    echo "=== Building generic image ($IMAGE) ==="
    docker build --network=host \
        --build-arg PYTHON_VERSION="$PYTHON_VERSION" \
        -f docker-tests/Dockerfile.e2e-runner \
        -t "$IMAGE" \
        "$PROJECT_ROOT"
fi

# --- mount points ---
mkdir -p "$PROJECT_ROOT/docker-tests/test-results"
RESULT_VOL="-v $PROJECT_ROOT/docker-tests/test-results:/app/test-results"
EXAMPLES_VOL="-v $PROJECT_ROOT/examples:/app/examples"
DATA_VOL="-v python-e2e-data:/app/data"

# --- env passthrough ---
ENV_ARGS=(-e "PIP_PACKAGES=$PIP_PACKAGES" -e "TEST_SCRIPT=$TEST_SCRIPT")
[ -n "$LLM_KEY" ] && ENV_ARGS+=(-e "LLM_API_KEY=$LLM_KEY")
[ -n "${LLMWIKIFY_VERSION:-}" ] && ENV_ARGS+=(-e "LLMWIKIFY_VERSION=$LLMWIKIFY_VERSION")

echo
echo "=== Running e2e suite ==="
echo "  Image:    $IMAGE"
echo "  PIP:      $PIP_PACKAGES"
echo "  Script:   $TEST_SCRIPT"
echo "  LLM key:  ${LLM_KEY:+set (${#LLM_KEY} chars)}${LLM_KEY:-NOT SET}"
echo "  Python:   $PYTHON_VERSION"
echo "============================================"

RM_FLAG="--rm"
[ "$KEEP_CONTAINER" = "1" ] && RM_FLAG=""

EXIT_CODE=0
docker run $RM_FLAG \
    -e IN_DOCKER=1 \
    -p 8765:8765 \
    $RESULT_VOL \
    $EXAMPLES_VOL \
    ${WHEEL_VOL:-} \
    $DATA_VOL \
    "${ENV_ARGS[@]}" \
    "$IMAGE" || EXIT_CODE=$?

# Cleanup volumes (unless --keep)
if [ "$KEEP_CONTAINER" != "1" ]; then
    docker volume rm python-e2e-data 2>/dev/null || true
fi

exit $EXIT_CODE
