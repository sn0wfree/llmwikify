#!/bin/bash
# tests/run_real_world_tests.sh
# Run real-world scenario tests and generate tutorial

set -e

echo "=========================================="
echo "  Real-World Scenario Tests"
echo "  LLM: minimax-M3"
echo "=========================================="

# 1. Check dependencies
echo ""
echo "[1/4] Checking dependencies..."
python3 -c "from llmwikify import create_wiki; print('  ✓ llmwikify OK')" 2>/dev/null || {
    echo "  ✗ llmwikify not installed. Run: pip install -e '.[all]'"
    exit 1
}
python3 -c "import yaml; print('  ✓ pyyaml OK')" 2>/dev/null || {
    echo "  ✗ pyyaml not installed. Run: pip install pyyaml"
    exit 1
}

# 2. Run tests
echo ""
echo "[2/4] Running scenario tests..."
cd /home/ll/llmwikify
pytest tests/scenarios/ -v --tb=short 2>&1 | tee tests/test_report.md
TEST_EXIT=$?

echo ""
echo "[3/4] Generating tutorial..."
python3 scripts/unified_tutorial_generator.py

echo ""
echo "=========================================="
if [ $TEST_EXIT -eq 0 ]; then
    echo "  ✅ All tests passed"
else
    echo "  ⚠️  Some tests failed"
fi
echo ""
echo "  Report: tests/test_report.md"
echo "  Tutorial: docs/TUTORIAL.md"
echo "=========================================="
