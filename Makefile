.PHONY: test lint eval-prompts check-prompts harness-tests e2e e2e-local help

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

e2e: ## Run e2e suite in generic python-e2e-runner container (builds wheel + image)
	./docker-tests/run-e2e.sh

e2e-local: ## Run e2e scripts on the host (no docker; uses python -m llmwikify)
	bash examples/09_wiki_build_e2e/scripts/run_all.sh
