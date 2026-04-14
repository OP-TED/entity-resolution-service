ARG ENVIRONMENT=production
 
ARG ENVIRONMENT=production
 
# =============================================================================
# Builder stage: install dependencies
# =============================================================================
FROM python:3.14-slim AS builder
 
ARG ENVIRONMENT
 
ENV PYTHONDONTWRITEBYTECODE=1 \
     PYTHONUNBUFFERED=1 \
     POETRY_VERSION=2.3.1 \
     POETRY_VIRTUALENVS_IN_PROJECT=true \
     POETRY_NO_INTERACTION=1
 
RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"
 
WORKDIR /app
 
COPY pyproject.toml poetry.lock LICENSE ./
 
RUN if [ "$ENVIRONMENT" = "development" ]; then \
      poetry install --no-root; \
    else \
      poetry install --no-root --only main; \
    fi
 
COPY . .
 
RUN if [ "$ENVIRONMENT" = "development" ]; then \
      poetry install; \
    else \
      poetry install --only main; \
    fi


# =============================================================================
# Runtime stage: minimal image
# =============================================================================
FROM python:3.14-slim AS runtime

ARG ENVIRONMENT

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

WORKDIR /app

# Core application
COPY --from=builder /app/.venv .venv
COPY --from=builder /app/src src

# Development extras: project scripts and tests (for in-container testing)
COPY --from=builder /app/scripts scripts/
COPY --from=builder /app/tests tests/
RUN if [ "$ENVIRONMENT" != "development" ]; then \
      rm -rf scripts tests; \
    fi

# Container entrypoint
COPY --chmod=755 infra/entrypoint.sh /entrypoint.sh

USER appuser

ENTRYPOINT ["/entrypoint.sh"]
CMD ["curation"]
