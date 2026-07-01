# docker-tests/Dockerfile
# Test image for llmwikify scenario tests.
# Build: docker build -f docker-tests/Dockerfile -t llmwikify-test .
# Run:   docker run --rm -e LLM_API_KEY=$LLM_API_KEY llmwikify-test

ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=UTC \
    LLM_PROVIDER=minimax \
    LLM_MODEL=minimax-M3 \
    LLM_BASE_URL=https://api.minimaxi.com/v1

# Use Aliyun mirrors for faster downloads in CN
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null \
    || sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---- Layer 1: Python dependencies (cached unless pyproject.toml changes) ----
# Use Aliyun pip mirror for fast downloads
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ \
    ".[mcp,config,watch,graph,web,extractors]" \
    "pytest>=7.0.0" \
    "pytest-cov>=4.0.0" \
    "pytest-asyncio>=0.21.0" \
    "httpx>=0.24.0"

# ---- Layer 2: Test code and fixtures ----
COPY tests/ ./tests/
COPY scripts/ ./scripts/
COPY raw/ ./raw/

# ---- User and permissions ----
RUN useradd -m -u 1000 testuser \
    && mkdir -p /app/test-results \
    && chown -R testuser:testuser /app
USER testuser

# Volume for test results
VOLUME ["/app/test-results"]

# Entrypoint
COPY --chown=testuser:testuser docker-tests/entrypoint.sh /app/docker-tests/entrypoint.sh
RUN chmod +x /app/docker-tests/entrypoint.sh

ENTRYPOINT ["/usr/bin/tini", "--", "/app/docker-tests/entrypoint.sh"]
CMD ["pytest", "tests/scenarios/", "-v", "--tb=short", \
     "--junit-xml=/app/test-results/junit.xml"]
