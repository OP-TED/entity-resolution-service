# Contributing to Entity Resolution Service

Thank you for considering a contribution. This guide explains how to work on the project effectively and get your changes accepted.

---

## Before You Start

**Pick a subject area you care about or want to learn.**
You don't need to be an expert — you become one through contributions.

**Start small.**
It is easier to get feedback on a small change than a large one. Look for issues labelled `good first issue` or `easy pick`.

**For significant work, confirm support first.**
Before fixing a non-trivial bug or implementing a feature, open an issue or discussion to confirm the problem is real and that there is consensus on the approach. Building something nobody asked for wastes everyone's time.

---

## Development Setup

```bash
# 1. Clone the repository
git clone https://github.com/OP-TED/entity-resolution-service.git
cd entity-resolution-service

# 2. Install all dependencies (runtime + dev + test + lint)
make install

# 3. Copy and configure the environment file
cp infra/.env.example infra/.env
# Edit infra/.env with your local settings

# 4. Start infrastructure services
make up
```

---

## Development Workflow

```bash
make test-unit        # run unit tests (fast, no infrastructure required)
make test-feature     # run BDD feature tests
make test             # run all tests with coverage
make lint             # ruff check
make typecheck        # mypy
make check-quality    # lint + typecheck + architecture constraints
make ci-full          # full CI pipeline (run before opening a PR)
```

Pre-commit hooks run `ruff format` and `ruff check` automatically on every commit. Install them once with:

```bash
poetry run pre-commit install
```

---

## Architecture Constraints

This project follows Cosmic Python layered architecture. The dependency direction is strict:

```
entrypoints → services → adapters → domain
```

Components are organised in tiers (see `.claude/memory/code-anatomy.md`). Architecture boundaries are enforced by `import-linter`:

```bash
make check-architecture
```

**Do not introduce imports that violate layer or tier rules.** If you are unsure, run `make check-architecture` before committing.

---

## Testing Expectations

There is no clean code without tests. All contributions must include:

- **Unit tests** for any new or modified logic in `domain/`, `adapters/`, or `services/`
- **BDD feature tests** (Gherkin) for any new use-case behaviour in `services/` or `entrypoints/`
- Coverage must not drop below 80%

Run `make coverage-report` to generate an HTML coverage report at `reports/htmlcov/`.

---

## Submitting a Pull Request

1. Fork the repository and create a branch from `develop`:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. Make your changes following the coding standards above.
3. Run the full quality check:
   ```bash
   make ci-full
   ```
4. Push and open a pull request targeting the `develop` branch.
5. Fill in the PR template: summary, test plan, and any architectural considerations.

**Wait for feedback and respond to it.**
Focus on one PR at a time, see it through, then move to the next. The shotgun approach — many open PRs left to stall — does more harm than good.

**Be patient.**
Reviews take time. This is not personal. Maintainers have many things to balance.

---

## Commit Messages

Follow this convention:

```
<type>: <short summary in imperative mood>
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`.

Examples:
- `feat: add bulk-delta endpoint to ERS REST API`
- `fix: correct datatable iteration in BDD step definitions`
- `refactor: extract decision store query into dedicated adapter method`

Keep the subject line under 72 characters. Add a body if the change needs explanation.

---

## Code of Conduct

By participating in this project you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

---

## Questions

Open a GitHub issueor start a discussion.
