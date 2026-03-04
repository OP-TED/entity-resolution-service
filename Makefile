SHELL=/bin/bash -o pipefail

BUILD_PRINT = \e[1;34m
END_BUILD_PRINT = \e[0m

PROJECT_PATH = $(shell pwd)
SRC_PATH = ${PROJECT_PATH}/src
TEST_PATH = ${PROJECT_PATH}/tests
BUILD_PATH = ${PROJECT_PATH}/dist
PACKAGE_NAME = ers

ICON_DONE = [✔]
ICON_ERROR = [x]
ICON_WARNING = [!]
ICON_PROGRESS = [-]

#-----------------------------------------------------------------------------
# Dev commands
#-----------------------------------------------------------------------------
.PHONY: help install-poetry install build
help: ## Display available targets
	@ echo -e "$(BUILD_PRINT)Available targets:$(END_BUILD_PRINT)"
	@ echo ""
	@ echo -e "  $(BUILD_PRINT)Development:$(END_BUILD_PRINT)"
	@ echo "    install              - Install project dependencies via Poetry"
	@ echo "    install-poetry       - Install Poetry if not present"
	@ echo "    build                - Build the package distribution"
	@ echo "    seed-db              - Seed the database with mock data (requires running database and config)"
	@ echo ""
	@ echo -e "  $(BUILD_PRINT)Testing:$(END_BUILD_PRINT)"
	@ echo "    test                 - Run all tests"
	@ echo "    test-unit            - Run unit tests only (exclude integration)"
	@ echo "    test-integration     - Run integration tests only"
	@ echo ""
	@ echo -e "  $(BUILD_PRINT)Code Quality:$(END_BUILD_PRINT)"
	@ echo "    format               - Format code with Ruff"
	@ echo "    lint-check           - Run Ruff linting checks"
	@ echo "    lint-fix             - Run Ruff checks with auto-fix"
	@ echo ""
	@ echo -e "  $(BUILD_PRINT)Utilities:$(END_BUILD_PRINT)"
	@ echo "    clean                - Remove build artifacts and caches"
	@ echo "    help                 - Display this help message"
	@ echo ""

install-poetry: ## Install Poetry if not present
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Installing Poetry $(END_BUILD_PRINT)"
	@ pip install "poetry>=2.0.0"
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Poetry  is installed$(END_BUILD_PRINT)"

install: install-poetry ## Install project dependencies
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Installing ERS requirements$(END_BUILD_PRINT)"
	@ poetry lock
	@ poetry install --with dev,test
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) ERS requirements are installed$(END_BUILD_PRINT)"

build: ## Build the package distribution
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Building package$(END_BUILD_PRINT)"
	@ poetry build
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Package built successfully$(END_BUILD_PRINT)"

seed-db: ## Seed the database with mock data (needs running database and config)
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Seeding database with mock data$(END_BUILD_PRINT)"
	@ poetry run python -m scripts.seed_db
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Database seeding complete$(END_BUILD_PRINT)"

#-----------------------------------------------------------------------------
# Testing commands
#-----------------------------------------------------------------------------
.PHONY: test test-unit test-integration
test: ## Run all tests
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Running all tests$(END_BUILD_PRINT)"
	@ poetry run pytest $(TEST_PATH)
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) All tests passed$(END_BUILD_PRINT)"

test-unit: ## Run unit tests only (exclude integration)
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Running unit tests$(END_BUILD_PRINT)"
	@ poetry run pytest $(TEST_PATH) -m "not integration"
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Unit tests passed$(END_BUILD_PRINT)"

test-integration: ## Run integration tests only
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Running integration tests$(END_BUILD_PRINT)"
	@ poetry run pytest $(TEST_PATH) -m "integration"
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Integration tests passed$(END_BUILD_PRINT)"

#-----------------------------------------------------------------------------
# Code quality commands
#-----------------------------------------------------------------------------
.PHONY: format lint-check lint-fix
format: ## Format code with Ruff
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Formatting code with Ruff$(END_BUILD_PRINT)"
	@ poetry run ruff format $(SRC_PATH) $(TEST_PATH)
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Format complete$(END_BUILD_PRINT)"

lint-check: ## Run Ruff linting checks
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Running Ruff checks $(END_BUILD_PRINT)"
	@ poetry run ruff check $(SRC_PATH) $(TEST_PATH)
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Running Ruff checks done$(END_BUILD_PRINT)"

lint-fix: ## Run Ruff checks with auto-fix
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Running Ruff checks with auto-fix$(END_BUILD_PRINT)"
	@ poetry run ruff check --fix $(SRC_PATH) $(TEST_PATH)
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Running Ruff checks with auto-fix done$(END_BUILD_PRINT)"

#-----------------------------------------------------------------------------
# Utility commands
#-----------------------------------------------------------------------------
.PHONY: clean
clean: ## Remove build artifacts and caches
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Cleaning build artifacts and caches$(END_BUILD_PRINT)"
	@ rm -rf $(BUILD_PATH)
	@ rm -rf .pytest_cache
	@ rm -rf .tox
	@ rm -rf *.egg-info
	@ poetry run ruff clean
	@ find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@ find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@ find . -type f -name "*.pyo" -delete 2>/dev/null || true
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Clean complete$(END_BUILD_PRINT)"

# Default target
.DEFAULT_GOAL := help