.PHONY: test lint eval-prompts check-prompts harness-tests help

PYTHONPATH := src
PYTEST := python3 -m pytest

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

test: ## Run all tests
	PYTHONPATH=$(PYTHONPATH) $(PYTEST) tests/ -v

lint: ## Run prompt lint checks (principle compliance + offline eval)
	PYTHONPATH=$(PYTHONPATH) python3 scripts/check_prompt_principles.py
	PYTHONPATH=$(PYTHONPATH) python3 scripts/eval_prompts.py

check-prompts: ## Check prompt principle compliance
	PYTHONPATH=$(PYTHONPATH) python3 scripts/check_prompt_principles.py

eval-prompts: ## Run offline prompt evaluation
	PYTHONPATH=$(PYTHONPATH) python3 scripts/eval_prompts.py --format json

harness-tests: ## Run prompt harness regression tests
	PYTHONPATH=$(PYTHONPATH) $(PYTEST) tests/test_v019_harness_regression.py -v
