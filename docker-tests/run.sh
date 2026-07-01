#!/bin/bash
# docker-tests/run.sh
# Convenience script to build and run tests in Docker.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# Parse args
BUILD_FIRST=false
PYTHON_VERSION="3.11"
TEST_ARGS=""
MOUNT_RESULTS=true
SKIP_BUILD=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --build)
            BUILD_FIRST=true
            shift
            ;;
        --no-results)
            MOUNT_RESULTS=false
            shift
            ;;
        --py)
            PYTHON_VERSION="$2"
            shift 2
            ;;
        --no-build)
            SKIP_BUILD=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [options] [-- pytest args...]"
            echo ""
            echo "Options:"
            echo "  --build          Build image before running"
            echo "  --no-build       Skip build (use existing image)"
            echo "  --py VERSION     Python version (default: 3.11)"
            echo "  --no-results     Don't mount test-results volume"
            echo ""
            echo "Examples:"
            echo "  $0 --build                              # Build + run all tests"
            echo "  $0 --no-build -e LLM_API_KEY=sk-xxx     # Run with LLM key"
            echo "  $0 -- tests/scenarios/test_01_*.py      # Run specific test"
            echo "  $0 --py 3.12                            # Use Python 3.12"
            exit 0
            ;;
        --)
            shift
            TEST_ARGS="$@"
            break
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

IMAGE_NAME="llmwikify-test:py${PYTHON_VERSION}"

# Build if requested
if [ "$BUILD_FIRST" = true ] && [ "$SKIP_BUILD" != true ]; then
    echo "=== Building Docker image ==="
    docker build --network=host \
        --build-arg PYTHON_VERSION=$PYTHON_VERSION \
        -f docker-tests/Dockerfile \
        -t "$IMAGE_NAME" .
fi

# Check image exists
if ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
    echo "Image $IMAGE_NAME not found. Building now..."
    docker build --network=host \
        --build-arg PYTHON_VERSION=$PYTHON_VERSION \
        -f docker-tests/Dockerfile \
        -t "$IMAGE_NAME" .
fi

# Get LLM key if available
ENV_ARGS=()
if [ -n "${LLM_API_KEY:-}" ]; then
    ENV_ARGS+=(-e "LLM_API_KEY=$LLM_API_KEY")
elif [ -f "$HOME/.llmwikify/llmwikify.json" ]; then
    KEY=$(python3 -c "import json; print(json.load(open('$HOME/.llmwikify/llmwikify.json'))['llm']['api_key'])" 2>/dev/null || echo "")
    if [ -n "$KEY" ]; then
        ENV_ARGS+=(-e "LLM_API_KEY=$KEY")
    fi
fi

# Prepare test-results mount
if [ "$MOUNT_RESULTS" = true ]; then
    mkdir -p "$PROJECT_ROOT/docker-tests/test-results"
    RESULT_ARGS=(-v "$PROJECT_ROOT/docker-tests/test-results:/app/test-results")
else
    RESULT_ARGS=()
fi

echo "=== Running tests in Docker ==="
echo "Image: $IMAGE_NAME"
echo "Args:  $TEST_ARGS"
echo "============================"

# Run
docker run --rm "${ENV_ARGS[@]}" "${RESULT_ARGS[@]}" \
    "$IMAGE_NAME" $TEST_ARGS
