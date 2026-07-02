#!/bin/bash
# docker-tests/run-compose.sh
# Run tests using Docker Compose (server + test containers).
# Equivalent to: docker compose -f docker-tests/docker-compose.yml --profile full up

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# Parse args
PROFILE="full"
PYTHON_VERSION="3.11"
SKIP_BUILD=false
KEEP_VOLUMES=false
LLM_KEY_PROVIDED=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --profile)
            PROFILE="$2"
            shift 2
            ;;
        --py)
            PYTHON_VERSION="$2"
            shift 2
            ;;
        --no-build)
            SKIP_BUILD=true
            shift
            ;;
        --keep-volumes)
            KEEP_VOLUMES=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  --profile PROFILE  Compose profile: full (default) or server"
            echo "  --py VERSION       Python version (default: 3.11)"
            echo "  --no-build         Skip image rebuild"
            echo "  --keep-volumes     Keep wiki-data volume after run"
            echo ""
            echo "Examples:"
            echo "  $0                          # Run full integration"
            echo "  $0 --profile server         # Run server only"
            echo "  $0 --py 3.12                # Use Python 3.12"
            echo "  $0 --no-build               # Use existing images"
            echo "  $0 --keep-volumes           # Don't delete wiki data"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Auto-detect LLM key from config
if [ -z "${LLM_API_KEY:-}" ] && [ -f "$HOME/.llmwikify/llmwikify.json" ]; then
    LLM_API_KEY=$(python3 -c \
        "import json; print(json.load(open('$HOME/.llmwikify/llmwikify.json'))['llm']['api_key'])" \
        2>/dev/null || echo "")
    if [ -n "$LLM_API_KEY" ]; then
        export LLM_API_KEY
        LLM_KEY_PROVIDED=true
        echo "LLM_API_KEY auto-loaded from ~/.llmwikify/llmwikify.json"
    fi
fi

if [ "$LLM_KEY_PROVIDED" = false ] && [ "$PROFILE" = "full" ]; then
    echo "Warning: LLM_API_KEY not set. LLM tests will be auto-skipped."
fi

# Create test-results dir
mkdir -p "$PROJECT_ROOT/docker-tests/test-results"

# Build images (unless --no-build)
if [ "$SKIP_BUILD" = false ]; then
    echo "=== Building Docker images ==="
    docker build \
        --build-arg PYTHON_VERSION=$PYTHON_VERSION \
        -f docker-tests/Dockerfile \
        -t llmwikify-test:py${PYTHON_VERSION} \
        "$PROJECT_ROOT"

    docker build \
        --build-arg PYTHON_VERSION=$PYTHON_VERSION \
        -f docker-tests/Dockerfile.server \
        -t llmwikify-server:py${PYTHON_VERSION} \
        "$PROJECT_ROOT"
fi

# Run compose
echo "=== Running $PROFILE profile ==="
docker compose \
    -f docker-tests/docker-compose.yml \
    --profile "$PROFILE" \
    up \
    --build \
    --abort-on-container-exit \
    --exit-code-from test

EXIT_CODE=$?

# Cleanup
echo "=== Cleanup ==="
if [ "$KEEP_VOLUMES" = true ]; then
    docker compose -f docker-tests/docker-compose.yml down
else
    docker compose -f docker-tests/docker-compose.yml down -v
fi

exit $EXIT_CODE
