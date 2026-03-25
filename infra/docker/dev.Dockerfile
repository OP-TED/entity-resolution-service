FROM python:3.14-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=2.3.1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1

RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"

WORKDIR /app

COPY pyproject.toml poetry.lock LICENSE ./

RUN poetry install --no-root

COPY . .

RUN poetry install


FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

WORKDIR /app

COPY --from=builder /app/.venv .venv
COPY --from=builder /app/src src
COPY --from=builder /app/scripts scripts
COPY --from=builder /app/tests tests

COPY infra/scripts/ /scripts/
RUN sed -i 's/\r$//g' /scripts/*.sh && chmod +x /scripts/*.sh

USER appuser

EXPOSE 8000 8001

ENTRYPOINT ["/scripts/entrypoint.sh"]
CMD ["/scripts/start-curation-api.sh"]
