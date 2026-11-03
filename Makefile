# Match the skillsaw action revision in .github/workflows/lint.yml.
SKILLSAW_PACKAGE := git+https://github.com/stbenjam/skillsaw@d252498eb6260e197c9c395a650643d9c49ae37b

.PHONY: help
help: ## Show this help message
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

.PHONY: skillsaw
skillsaw: ## Run skillsaw linter on skills and plugins
	@echo "Running skillsaw..."
	@if [ -n "$${SKILLSAW_BIN:-}" ]; then \
		"$${SKILLSAW_BIN}"; \
	else \
		uvx --from "$(SKILLSAW_PACKAGE)" skillsaw; \
	fi

.PHONY: skillsaw-fix
skillsaw-fix: ## Auto-fix fixable skillsaw issues
	@echo "Fixing skillsaw issues..."
	@if [ -n "$${SKILLSAW_BIN:-}" ]; then \
		"$${SKILLSAW_BIN}" fix; \
	else \
		uvx --from "$(SKILLSAW_PACKAGE)" skillsaw fix; \
	fi

.PHONY: lint
lint: ## Run all linters
	@$(MAKE) skillsaw

.DEFAULT_GOAL := help
