SHELL=/bin/bash -o pipefail

BUILD_PRINT = \e[1;34m
END_BUILD_PRINT = \e[0m

REPO_ROOT    = $(shell pwd)
SRC_PATH     = $(REPO_ROOT)/src
TEST_PATH    = $(REPO_ROOT)/test
BUILD_PATH   = $(REPO_ROOT)/dist
PACKAGE_NAME = ers
COMPOSE_FILE = $(SRC_PATH)/infra/compose.dev.yaml
ENV_FILE     = $(SRC_PATH)/infra/.env
OPENAPI_GENERATOR_IMAGE = openapitools/openapi-generator-cli:v7.22.0
DOCS_API_REL ?= docs/api-docs
DOCS_API_PATH = $(REPO_ROOT)/$(DOCS_API_REL)
DOCS_TEMPLATE_PATH = $(REPO_ROOT)/docs/templates/asciidoc
ASCIIDOC_PROPS = useMethodAndPath=true,useIntroduction=true,useTableTitles=true,skipExamples=true

ICON_DONE = [✔]
ICON_ERROR = [x]
ICON_WARNING = [!]
ICON_PROGRESS = [-]

# Coverage flags — appended only in coverage-aware targets
COV_FLAGS = --cov=ers \
            --cov-report=term-missing \
            --cov-report=xml:$(REPO_ROOT)/coverage.xml \
            --cov-fail-under=80

#-----------------------------------------------------------------------------
# Dev commands
#-----------------------------------------------------------------------------
.PHONY: help install-poetry install lock build seed-db openapi api-docs backfill-cluster-sizes backfill-review-counts verify-cluster-sizes

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
	@ echo "    up-with-dev-tools    - Start services + dev-tools profile (Jaeger UI on :16686)"
	@ echo "    down                 - Stop services (docker compose down)"
	@ echo "    down-with-dev-tools  - Stop services including dev-tools profile"
	@ echo "    down-volumes         - Stop services and remove volumes"
	@ echo "    rebuild              - Rebuild and start services"
	@ echo "    rebuild-clean        - Rebuild from scratch (no cache)"
	@ echo "    logs                 - Follow service logs"
	@ echo "    watch                - Start services with file watching (hot-reload)"
	@ echo ""
	@ echo -e "  $(BUILD_PRINT)ERSys tests (black-box, requires make up):$(END_BUILD_PRINT)"
	@ echo "    test-ersys-smoke     - Smoke tests — checks stack reachability"
	@ echo "    test-ersys-e2e       - End-to-end black-box tests"
	@ echo "    test-ersys-all       - All ERSys tests (smoke + e2e)"
	@ echo ""
	@ echo -e "  $(BUILD_PRINT)Dev & testing utilities:$(END_BUILD_PRINT)"
	@ echo "    redis-monitor        - Stream all Redis commands in real time (requires make up)"
	@ echo "    redis-rest-api-start - Start ERE response injector REST API in the background"
	@ echo "    redis-rest-api-stop  - Stop ERE response injector REST API"
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
	@ cd src && poetry install --with dev,test,lint
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) ERS requirements are installed$(END_BUILD_PRINT)"

lock: ## Update poetry.lock
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Locking dependencies$(END_BUILD_PRINT)"
	@ cd src && poetry lock
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Lock file updated$(END_BUILD_PRINT)"

build: ## Build the package distribution
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Building package$(END_BUILD_PRINT)"
	@ cd src && poetry build
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Package built successfully$(END_BUILD_PRINT)"

seed-db: ## Seed the database with mock data (needs running database and config)
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Seeding database with mock data$(END_BUILD_PRINT)"
	@ cd src && poetry run python -m scripts.seed_db
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Database seeding complete$(END_BUILD_PRINT)"

backfill-cluster-sizes: ## Rebuild cluster_sizes projection from decisions (idempotent, run after deploy)
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Backfilling cluster_sizes...$(END_BUILD_PRINT)"
	@ cd src && poetry run python -m scripts.backfill_cluster_sizes
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Done$(END_BUILD_PRINT)"

backfill-review-counts: ## Seed previous_review_count on decisions from user_actions (idempotent, one-off)
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Backfilling previous_review_count...$(END_BUILD_PRINT)"
	@ cd src && poetry run python -m scripts.backfill_previous_review_count
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Done$(END_BUILD_PRINT)"

verify-cluster-sizes: ## Verify cluster_sizes projection is consistent with decisions (exits 0=ok, 1=drift)
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Verifying cluster_sizes...$(END_BUILD_PRINT)"
	@ cd src && poetry run python -m scripts.verify_cluster_sizes

openapi: ## Generate OpenAPI schema into resources/
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Generating OpenAPI schemas$(END_BUILD_PRINT)"
	@ cd src && poetry run python -m scripts.export_openapi
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) OpenAPI schemas generated$(END_BUILD_PRINT)"

# Usage: $(call run-openapi-asciidoc,<schema-file>,<output-subdir>)
define run-openapi-asciidoc
	@ MSYS_NO_PATHCONV=1 docker run --rm \
		-v "$(REPO_ROOT)/resources:/input" \
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
	@ cd src && poetry run python -m scripts.fix_asciidoc_xrefs \
		$(DOCS_API_PATH)/ers/index.adoc \
		$(DOCS_API_PATH)/curation/index.adoc
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) API reference docs generated at $(DOCS_API_REL)/$(END_BUILD_PRINT)"

#-----------------------------------------------------------------------------
# Code quality — mutating targets
#-----------------------------------------------------------------------------
.PHONY: format lint-fix pre-commit

format: ## Format code with Ruff
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Formatting code$(END_BUILD_PRINT)"
	@ cd src && poetry run ruff format ers $(TEST_PATH)
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Format complete$(END_BUILD_PRINT)"

lint-fix: ## Run Ruff checks with auto-fix
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Running Ruff auto-fix$(END_BUILD_PRINT)"
	@ cd src && poetry run ruff check --fix ers $(TEST_PATH)
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Ruff auto-fix complete$(END_BUILD_PRINT)"

pre-commit: ## Run pre-commit hooks on all files
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Running pre-commit hooks$(END_BUILD_PRINT)"
	@ cd src && poetry run pre-commit run --all-files
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Pre-commit hooks passed$(END_BUILD_PRINT)"

#-----------------------------------------------------------------------------
# Validation — non-mutating targets
#-----------------------------------------------------------------------------
.PHONY: lint typecheck check-architecture test test-unit test-feature test-e2e test-integration test-ersys-smoke test-ersys-e2e test-ersys-all

lint: ## Run Ruff linting checks
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Running Ruff checks$(END_BUILD_PRINT)"
	@ cd src && poetry run ruff check ers $(TEST_PATH)
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Ruff checks passed$(END_BUILD_PRINT)"

typecheck: ## Run mypy type checks
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Running mypy$(END_BUILD_PRINT)"
	@ cd src && poetry run mypy ers
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Type checks passed$(END_BUILD_PRINT)"

check-architecture: ## Check architecture constraints with import-linter
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Checking architecture constraints$(END_BUILD_PRINT)"
	@ cd src && poetry run lint-imports --config $(REPO_ROOT)/.importlinter
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Architecture checks passed$(END_BUILD_PRINT)"

test: ## Run all tests (with coverage)
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Running all tests$(END_BUILD_PRINT)"
	@ cd src && poetry run pytest -c pytest.ini --rootdir=$(REPO_ROOT) $(TEST_PATH) --ignore=$(TEST_PATH)/ersys $(COV_FLAGS) --junitxml=$(REPO_ROOT)/test-results.xml
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) All tests passed$(END_BUILD_PRINT)"

test-unit: ## Run unit tests only
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Running unit tests$(END_BUILD_PRINT)"
	@ cd src && poetry run pytest -c pytest.ini --rootdir=$(REPO_ROOT) $(TEST_PATH) --ignore=$(TEST_PATH)/ersys -m "unit"
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Unit tests passed$(END_BUILD_PRINT)"

test-feature: ## Run BDD feature tests only
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Running feature tests$(END_BUILD_PRINT)"
	@ cd src && poetry run pytest -c pytest.ini --rootdir=$(REPO_ROOT) $(TEST_PATH) --ignore=$(TEST_PATH)/ersys -m "feature"
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Feature tests passed$(END_BUILD_PRINT)"

test-e2e: ## Run end-to-end tests only
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Running e2e tests$(END_BUILD_PRINT)"
	@ cd src && poetry run pytest -c pytest.ini --rootdir=$(REPO_ROOT) $(TEST_PATH) --ignore=$(TEST_PATH)/ersys -m "e2e"
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) E2e tests passed$(END_BUILD_PRINT)"

test-integration: ## Run integration tests only
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Running integration tests$(END_BUILD_PRINT)"
	@ cd src && poetry run pytest -c pytest.ini --rootdir=$(REPO_ROOT) $(TEST_PATH) --ignore=$(TEST_PATH)/ersys -m "integration"
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Integration tests passed$(END_BUILD_PRINT)"

#-----------------------------------------------------------------------------
# ERSys tests — black-box tests against the full running stack
#-----------------------------------------------------------------------------

test-ersys-smoke: ## Run ERSys smoke tests — checks stack reachability (requires make up)
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Running ERSys smoke tests$(END_BUILD_PRINT)"
	@ cd $(SRC_PATH) && poetry run pytest -c pytest.ini --rootdir=$(REPO_ROOT) $(TEST_PATH)/ersys/smoke -v
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) ERSys smoke tests passed$(END_BUILD_PRINT)"

test-ersys-e2e: ## Run ERSys end-to-end tests (requires full ERSys stack: make up)
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Running ERSys e2e tests$(END_BUILD_PRINT)"
	@ cd $(SRC_PATH) && poetry run pytest -c pytest.ini --rootdir=$(REPO_ROOT) $(TEST_PATH)/ersys/e2e -v
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) ERSys e2e tests passed$(END_BUILD_PRINT)"

test-ersys-all: ## Run all ERSys tests (smoke + e2e; requires full ERSys stack: make up)
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Running all ERSys tests$(END_BUILD_PRINT)"
	@ cd $(SRC_PATH) && poetry run pytest -c pytest.ini --rootdir=$(REPO_ROOT) $(TEST_PATH)/ersys -v
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) All ERSys tests passed$(END_BUILD_PRINT)"

#-----------------------------------------------------------------------------
# Dev & testing utilities
#-----------------------------------------------------------------------------
.PHONY: redis-monitor redis-rest-api-start redis-rest-api-stop

redis-monitor: ## Stream all Redis commands in real time (requires make up)
	@ docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) exec ersys-redis \
		sh -c 'redis-cli --no-auth-warning -a "$$REDIS_PASSWORD" MONITOR'

INJECT_PID_FILE = .inject-app.pid

redis-rest-api-start: ## Start the ERE response injector REST API in the background
	@ set -a; source $(ENV_FILE); set +a; \
		cd $(SRC_PATH) && INJECT_APP_PORT=$${INJECT_APP_PORT:-8002} poetry run python scripts/inject_ere_response_app.py & \
		echo $$! > $(REPO_ROOT)/$(INJECT_PID_FILE)
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Injector API started on port $${INJECT_APP_PORT:-8002} (PID: $$(cat $(REPO_ROOT)/$(INJECT_PID_FILE)))$(END_BUILD_PRINT)"

redis-rest-api-stop: ## Stop the ERE response injector REST API
	@ if [ -f $(REPO_ROOT)/$(INJECT_PID_FILE) ]; then \
		kill $$(cat $(REPO_ROOT)/$(INJECT_PID_FILE)) 2>/dev/null || true; \
		rm -f $(REPO_ROOT)/$(INJECT_PID_FILE); \
		echo -e "$(BUILD_PRINT)$(ICON_DONE) Injector API stopped$(END_BUILD_PRINT)"; \
	else \
		echo -e "$(BUILD_PRINT)$(ICON_WARNING) No PID file found — is the injector running?$(END_BUILD_PRINT)"; \
	fi

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
	@ mkdir -p $(REPO_ROOT)/reports
	@ cd src && poetry run pytest -c pytest.ini --rootdir=$(REPO_ROOT) $(TEST_PATH) $(COV_FLAGS) --cov-report=html:$(REPO_ROOT)/reports/htmlcov -m "unit or feature"
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Coverage report at $(REPO_ROOT)/reports/htmlcov/index.html$(END_BUILD_PRINT)"

quality-report: ## Generate Radon quality report in reports/
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Generating quality report$(END_BUILD_PRINT)"
	@ mkdir -p $(REPO_ROOT)/reports
	@ cd src && poetry run radon cc ers -s -a -j > $(REPO_ROOT)/reports/complexity.json
	@ cd src && poetry run radon mi ers -s -j > $(REPO_ROOT)/reports/maintainability.json
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Quality reports at $(REPO_ROOT)/reports/$(END_BUILD_PRINT)"

#-----------------------------------------------------------------------------
# Clean code analysis (separate)
#-----------------------------------------------------------------------------
.PHONY: complexity maintainability clean-code

complexity: ## Radon cyclomatic complexity analysis
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Checking cyclomatic complexity$(END_BUILD_PRINT)"
	@ cd src && poetry run radon cc ers -s -a
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Complexity analysis complete$(END_BUILD_PRINT)"

maintainability: ## Radon maintainability index
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Checking maintainability index$(END_BUILD_PRINT)"
	@ cd src && poetry run radon mi ers -s
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Maintainability analysis complete$(END_BUILD_PRINT)"

clean-code: ## Xenon threshold checks
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Running Xenon threshold checks$(END_BUILD_PRINT)"
	@ cd src && poetry run xenon ers --max-absolute B --max-modules A --max-average A
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Clean code checks passed$(END_BUILD_PRINT)"

#-----------------------------------------------------------------------------
# Docker
#-----------------------------------------------------------------------------
.PHONY: check-env up up-with-dev-tools down down-with-dev-tools down-volumes rebuild rebuild-clean logs watch

check-env:
	@ test -f $(ENV_FILE) || (echo -e "$(BUILD_PRINT)$(ICON_ERROR) Missing $(ENV_FILE). Run: cp src/infra/.env.example src/infra/.env$(END_BUILD_PRINT)" && exit 1)

up: check-env ## Start services (docker compose up -d)
	@ docker network create ersys-local || true
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Starting services$(END_BUILD_PRINT)"
	@ docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) up -d
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Services started$(END_BUILD_PRINT)"

up-with-dev-tools: check-env ## Start services including dev-tools (docker dev-tools profile)
	@ docker network create ersys-local || true
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Starting services (incl. dev-tools)$(END_BUILD_PRINT)"
	@ docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) --profile dev-tools up -d
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Services started$(END_BUILD_PRINT)"

down: check-env ## Stop services (docker compose down)
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Stopping services$(END_BUILD_PRINT)"
	@ docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) down
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Services stopped$(END_BUILD_PRINT)"

down-with-dev-tools: check-env ## Stop services including dev-tools (docker dev-tools profile)
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Stopping services (incl. dev-tools)$(END_BUILD_PRINT)"
	@ docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) --profile dev-tools down
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
	@ rm -rf $(REPO_ROOT)/.pytest_cache src/.pytest_cache
	@ rm -rf src/.mypy_cache
	@ rm -rf src/.ruff_cache
	@ rm -rf src/.tox
	@ rm -rf $(REPO_ROOT)/coverage.xml $(REPO_ROOT)/test-results.xml
	@ rm -rf src/*.egg-info
	@ rm -rf $(REPO_ROOT)/reports
	@ cd src && poetry run ruff clean 2>/dev/null || true
	@ find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@ find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@ find . -type f -name "*.pyo" -delete 2>/dev/null || true
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Clean complete$(END_BUILD_PRINT)"

# Default target
.DEFAULT_GOAL := help
