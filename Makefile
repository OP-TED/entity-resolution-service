SHELL=/bin/bash -o pipefail

BUILD_PRINT = \e[1;34m
END_BUILD_PRINT = \e[0m

PROJECT_PATH = $(shell pwd)
SRC_PATH = ${PROJECT_PATH}/src
TEST_PATH = ${PROJECT_PATH}/tests
BUILD_PATH = ${PROJECT_PATH}/dist
PACKAGE_NAME = ers
COMPOSE_FILE = ${PROJECT_PATH}/infra/compose.dev.yaml
ENV_FILE = ${PROJECT_PATH}/infra/.env
# TODO: bump to v7.22.0 once released — v7.21.0 drops descriptions from nullable
#       (anyOf) properties in the asciidoc generator. The fix is in the 7.22.0-SNAPSHOT
#       but no stable release or Docker image exists yet.
OPENAPI_GENERATOR_IMAGE = openapitools/openapi-generator-cli:v7.21.0
DOCS_API_REL ?= docs/api-docs
DOCS_API_PATH = ${PROJECT_PATH}/${DOCS_API_REL}
DOCS_TEMPLATE_PATH = ${PROJECT_PATH}/docs/templates/asciidoc
ASCIIDOC_PROPS = useMethodAndPath=true,useIntroduction=true,useTableTitles=true,skipExamples=true

ICON_DONE = [✔]
ICON_ERROR = [x]
ICON_WARNING = [!]
ICON_PROGRESS = [-]

# Coverage flags — appended only in coverage-aware targets
COV_FLAGS = --cov=src --cov-report=term-missing --cov-report=xml:coverage.xml --cov-fail-under=80

#-----------------------------------------------------------------------------
# Dev commands
#-----------------------------------------------------------------------------
.PHONY: help install-poetry install lock build seed-db openapi generate-api-docs

help: ## Display available targets
	@ echo -e "$(BUILD_PRINT)Available targets:$(END_BUILD_PRINT)"
	@ echo ""
	@ echo -e "  $(BUILD_PRINT)Development:$(END_BUILD_PRINT)"
	@ echo "    install              - Install project dependencies via Poetry"
	@ echo "    lock                 - Update poetry.lock"
	@ echo "    build                - Build the package distribution"
	@ echo "    seed-db              - Seed the database with mock data"
	@ echo "    openapi              - Generate OpenAPI schemas into /resources folder"
	@ echo "    api-docs    		 - Generate AsciiDoc API reference from OpenAPI schemas"
	@ echo "                           Override output path: make api-docs DOCS_API_REL=path"
	@ echo ""
	@ echo -e "  $(BUILD_PRINT)Code Quality (mutating):$(END_BUILD_PRINT)"
	@ echo "    format               - Format code with Ruff"
	@ echo "    lint-fix             - Run Ruff checks with auto-fix"
	@ echo "    pre-commit           - Run pre-commit hooks on all files"
	@ echo ""
	@ echo -e "  $(BUILD_PRINT)Validation (non-mutating):$(END_BUILD_PRINT)"
	@ echo "    lint                 - Run Ruff linting checks"
	@ echo "    typecheck            - Run mypy type checks"
	@ echo "    check-architecture   - Check architecture constraints with import-linter"
	@ echo "    test                 - Run all tests (with coverage)"
	@ echo "    test-unit            - Run unit tests only (exclude features/steps/integration)"
	@ echo "    test-feature         - Run BDD feature tests only (features + steps)"
	@ echo "    test-integration     - Run integration tests only"
	@ echo ""
	@ echo -e "  $(BUILD_PRINT)Aggregates:$(END_BUILD_PRINT)"
	@ echo "    check-quality        - Static checks: lint + typecheck + architecture"
	@ echo "    check-all            - Full suite: quality + all tests"
	@ echo "    ci-quick             - CI fast: quality + unit tests"
	@ echo "    ci-full              - CI full: quality + all tests + clean-code"
	@ echo ""
	@ echo -e "  $(BUILD_PRINT)Reports (opt-in):$(END_BUILD_PRINT)"
	@ echo "    coverage-report      - Generate HTML coverage report in reports/"
	@ echo "    quality-report       - Generate Radon quality report in reports/"
	@ echo ""
	@ echo -e "  $(BUILD_PRINT)Clean Code (separate):$(END_BUILD_PRINT)"
	@ echo "    complexity           - Radon cyclomatic complexity analysis"
	@ echo "    maintainability      - Radon maintainability index"
	@ echo "    clean-code           - Xenon threshold checks"
	@ echo ""
	@ echo -e "  $(BUILD_PRINT)Docker:$(END_BUILD_PRINT)"
	@ echo "    up                   - Start services (docker compose up -d)"
	@ echo "    down                 - Stop services (docker compose down)"
	@ echo "    down-volumes         - Stop services and remove volumes"
	@ echo "    rebuild              - Rebuild and start services"
	@ echo "    rebuild-clean        - Rebuild from scratch (no cache)"
	@ echo "    logs                 - Follow service logs"
	@ echo "    watch                - Start services with file watching (hot-reload)"
	@ echo ""
	@ echo -e "  $(BUILD_PRINT)Utilities:$(END_BUILD_PRINT)"
	@ echo "    clean                - Remove build artifacts and caches"
	@ echo "    help                 - Display this help message"
	@ echo ""

install-poetry: ## Install Poetry if not present
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Installing Poetry$(END_BUILD_PRINT)"
	@ pip install "poetry>=2.0.0"
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Poetry is installed$(END_BUILD_PRINT)"

install: install-poetry ## Install project dependencies
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Installing ERS requirements$(END_BUILD_PRINT)"
	@ poetry install --with dev,test,lint
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) ERS requirements are installed$(END_BUILD_PRINT)"

lock: ## Update poetry.lock
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Locking dependencies$(END_BUILD_PRINT)"
	@ poetry lock
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Lock file updated$(END_BUILD_PRINT)"

build: ## Build the package distribution
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Building package$(END_BUILD_PRINT)"
	@ poetry build
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Package built successfully$(END_BUILD_PRINT)"

seed-db: ## Seed the database with mock data (needs running database and config)
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Seeding database with mock data$(END_BUILD_PRINT)"
	@ poetry run python -m scripts.seed_db
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Database seeding complete$(END_BUILD_PRINT)"

openapi: ## Generate OpenAPI schema into resources/
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Generating OpenAPI schemas$(END_BUILD_PRINT)"
	@ poetry run python -m scripts.export_openapi
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) OpenAPI schemas generated$(END_BUILD_PRINT)"

# Usage: $(call run-openapi-asciidoc,<schema-file>,<output-subdir>)
define run-openapi-asciidoc
	@ MSYS_NO_PATHCONV=1 docker run --rm \
		-v "$(PROJECT_PATH)/resources:/input" \
		-v "$(DOCS_API_PATH)/$(2):/output" \
		-v "$(DOCS_TEMPLATE_PATH):/templates" \
		$(OPENAPI_GENERATOR_IMAGE) generate \
		-i /input/$(1) \
		-g asciidoc \
		-o /output \
		-t /templates \
		--additional-properties=$(ASCIIDOC_PROPS) \
		--remove-operation-id-prefix \
		--skip-validate-spec \
		--inline-schema-name-mappings Location_inner=LocationElement
endef

api-docs: ## Generate AsciiDoc API reference from OpenAPI schemas (override: DOCS_API_REL=path)
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Generating API reference documentation$(END_BUILD_PRINT)"
	@ mkdir -p $(DOCS_API_PATH)/ers $(DOCS_API_PATH)/curation
	$(call run-openapi-asciidoc,ers-openapi-schema.json,ers)
	$(call run-openapi-asciidoc,curation-openapi-schema.json,curation)
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Fixing cross-references$(END_BUILD_PRINT)"
	@ cd $(PROJECT_PATH) && poetry run python -m scripts.fix_asciidoc_xrefs \
		$(DOCS_API_REL)/ers/index.adoc \
		$(DOCS_API_REL)/curation/index.adoc
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) API reference docs generated at $(DOCS_API_REL)/$(END_BUILD_PRINT)"

#-----------------------------------------------------------------------------
# Code quality — mutating targets
#-----------------------------------------------------------------------------
.PHONY: format lint-fix pre-commit

format: ## Format code with Ruff
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Formatting code$(END_BUILD_PRINT)"
	@ poetry run ruff format $(SRC_PATH) $(TEST_PATH)
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Format complete$(END_BUILD_PRINT)"

lint-fix: ## Run Ruff checks with auto-fix
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Running Ruff auto-fix$(END_BUILD_PRINT)"
	@ poetry run ruff check --fix $(SRC_PATH) $(TEST_PATH)
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Ruff auto-fix complete$(END_BUILD_PRINT)"

pre-commit: ## Run pre-commit hooks on all files
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Running pre-commit hooks$(END_BUILD_PRINT)"
	@ poetry run pre-commit run --all-files
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Pre-commit hooks passed$(END_BUILD_PRINT)"

#-----------------------------------------------------------------------------
# Validation — non-mutating targets
#-----------------------------------------------------------------------------
.PHONY: lint typecheck check-architecture test test-unit test-feature test-e2e test-integration

lint: ## Run Ruff linting checks
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Running Ruff checks$(END_BUILD_PRINT)"
	@ poetry run ruff check $(SRC_PATH) $(TEST_PATH)
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Ruff checks passed$(END_BUILD_PRINT)"

typecheck: ## Run mypy type checks
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Running mypy$(END_BUILD_PRINT)"
	@ poetry run mypy $(SRC_PATH)
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Type checks passed$(END_BUILD_PRINT)"

check-architecture: ## Check architecture constraints with import-linter
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Checking architecture constraints$(END_BUILD_PRINT)"
	@ poetry run lint-imports
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Architecture checks passed$(END_BUILD_PRINT)"

test: ## Run all tests (with coverage)
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Running all tests$(END_BUILD_PRINT)"
	@ poetry run pytest $(TEST_PATH) $(COV_FLAGS) --junitxml=test-results.xml
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) All tests passed$(END_BUILD_PRINT)"

test-unit: ## Run unit tests only
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Running unit tests$(END_BUILD_PRINT)"
	@ poetry run pytest $(TEST_PATH) -m "unit"
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Unit tests passed$(END_BUILD_PRINT)"

test-feature: ## Run BDD feature tests only
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Running feature tests$(END_BUILD_PRINT)"
	@ poetry run pytest $(TEST_PATH) -m "feature"
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Feature tests passed$(END_BUILD_PRINT)"

test-e2e: ## Run end-to-end tests only
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Running e2e tests$(END_BUILD_PRINT)"
	@ poetry run pytest $(TEST_PATH) -m "e2e"
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) E2e tests passed$(END_BUILD_PRINT)"

test-integration: ## Run integration tests only
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Running integration tests$(END_BUILD_PRINT)"
	@ poetry run pytest $(TEST_PATH) -m "integration"
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Integration tests passed$(END_BUILD_PRINT)"

#-----------------------------------------------------------------------------
# Aggregates
#-----------------------------------------------------------------------------
.PHONY: check-quality check-all ci-quick ci-full

check-quality: lint typecheck check-architecture ## Static checks: lint + typecheck + architecture
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) All quality checks passed$(END_BUILD_PRINT)"

check-all: check-quality test ## Full suite: quality + all tests
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Full verification suite passed$(END_BUILD_PRINT)"

ci-quick: check-quality test-unit ## CI fast: quality + unit tests
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) CI quick checks passed$(END_BUILD_PRINT)"

ci-full: check-all clean-code ## CI full: quality + all tests + clean-code
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) CI full checks passed$(END_BUILD_PRINT)"

#-----------------------------------------------------------------------------
# Reports (opt-in)
#-----------------------------------------------------------------------------
.PHONY: coverage-report quality-report

coverage-report: ## Generate HTML coverage report in reports/
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Generating coverage report$(END_BUILD_PRINT)"
	@ mkdir -p reports
	@ poetry run pytest $(TEST_PATH) $(COV_FLAGS) --cov-report=html:reports/htmlcov -m "unit or feature"
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Coverage report at reports/htmlcov/index.html$(END_BUILD_PRINT)"

quality-report: ## Generate Radon quality report in reports/
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Generating quality report$(END_BUILD_PRINT)"
	@ mkdir -p reports
	@ poetry run radon cc $(SRC_PATH) -s -a -j > reports/complexity.json
	@ poetry run radon mi $(SRC_PATH) -s -j > reports/maintainability.json
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Quality reports at reports/$(END_BUILD_PRINT)"

#-----------------------------------------------------------------------------
# Clean code analysis (separate)
#-----------------------------------------------------------------------------
.PHONY: complexity maintainability clean-code

complexity: ## Radon cyclomatic complexity analysis
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Checking cyclomatic complexity$(END_BUILD_PRINT)"
	@ poetry run radon cc $(SRC_PATH) -s -a
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Complexity analysis complete$(END_BUILD_PRINT)"

maintainability: ## Radon maintainability index
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Checking maintainability index$(END_BUILD_PRINT)"
	@ poetry run radon mi $(SRC_PATH) -s
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Maintainability analysis complete$(END_BUILD_PRINT)"

clean-code: ## Xenon threshold checks
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Running Xenon threshold checks$(END_BUILD_PRINT)"
	@ poetry run xenon $(SRC_PATH) --max-absolute B --max-modules A --max-average A
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Clean code checks passed$(END_BUILD_PRINT)"

#-----------------------------------------------------------------------------
# Docker
#-----------------------------------------------------------------------------
.PHONY: check-env up down down-volumes rebuild rebuild-clean logs watch

check-env:
	@ test -f $(ENV_FILE) || (echo -e "$(BUILD_PRINT)$(ICON_ERROR) Missing $(ENV_FILE). Run: cp infra/.env.example infra/.env$(END_BUILD_PRINT)" && exit 1)

up: check-env ## Start services (docker compose up -d)
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Starting services$(END_BUILD_PRINT)"
	@ docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) up -d
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Services started$(END_BUILD_PRINT)"

down: check-env ## Stop services (docker compose down)
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Stopping services$(END_BUILD_PRINT)"
	@ docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) down
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Services stopped$(END_BUILD_PRINT)"

down-volumes: check-env ## Stop services and remove volumes
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Stopping services and removing volumes$(END_BUILD_PRINT)"
	@ docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) down -v
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Services stopped and volumes removed$(END_BUILD_PRINT)"

rebuild: check-env ## Rebuild and start services
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Rebuilding services$(END_BUILD_PRINT)"
	@ docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) up -d --build
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Services rebuilt and started$(END_BUILD_PRINT)"

rebuild-clean: check-env ## Rebuild from scratch (no cache) and start services
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Rebuilding services (no cache)$(END_BUILD_PRINT)"
	@ docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) build --no-cache
	@ docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) up -d
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Services rebuilt (clean) and started$(END_BUILD_PRINT)"

logs: check-env ## Follow service logs
	@ docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) logs -f

watch: check-env ## Start services with file watching (hot-reload)
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Starting services with watch$(END_BUILD_PRINT)"
	@ docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) watch

#-----------------------------------------------------------------------------
# Utilities
#-----------------------------------------------------------------------------
.PHONY: clean

clean: ## Remove build artifacts and caches
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Cleaning build artifacts and caches$(END_BUILD_PRINT)"
	@ rm -rf $(BUILD_PATH)
	@ rm -rf .pytest_cache
	@ rm -rf .mypy_cache
	@ rm -rf .ruff_cache
	@ rm -rf .tox
	@ rm -rf .coverage htmlcov coverage.xml test-results.xml
	@ rm -rf *.egg-info
	@ rm -rf reports
	@ poetry run ruff clean 2>/dev/null || true
	@ find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@ find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@ find . -type f -name "*.pyo" -delete 2>/dev/null || true
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Clean complete$(END_BUILD_PRINT)"

# Default target
.DEFAULT_GOAL := help
