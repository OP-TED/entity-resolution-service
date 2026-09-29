# Telemetry (OpenTelemetry + Jaeger)

ERS uses OpenTelemetry for distributed tracing. Tracing is **disabled by default** and must be explicitly enabled via environment variables.

## Local setup with Jaeger

Jaeger runs as an optional service in the `dev-tools` Docker Compose profile.

**1. Start services with Jaeger:**

```bash
make up-with-dev-tools    # start all services + Jaeger
make down-with-dev-tools  # stop all services + Jaeger
```

**2. Enable tracing in `src/infra/.env`:**

```dotenv
TRACING_ENABLED=true
OTEL_SERVICE_NAME=entity-resolution-service
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
```

> `OTEL_EXPORTER_OTLP_ENDPOINT` must be the **base URL only** — the SDK appends `/v1/traces` automatically. Do not include the path.

**3. Open the Jaeger UI:** http://localhost:16686

## Finding traces in the Jaeger UI

Send at least one request to the ERS or Curation API first so spans are available.

1. **Search** — open http://localhost:16686 and go to the **Search** tab (top nav).
2. **Select a service** — pick `entity-resolution-service` (or the service name set in `OTEL_SERVICE_NAME`) from the **Service** dropdown.
3. **Narrow the results** — optionally pick an **Operation**, set a **Lookback** window (e.g. *Last 1 Hour*), and click **Find Traces**.
4. **Inspect a trace** — click any result row to open the waterfall view. Each bar is a span; its width is proportional to duration. Spans are nested to show parent-child relationships across service calls.
5. **Expand a span** — click a span bar to see its tags (HTTP method, status code, DB query, etc.) and any recorded exceptions.

> Full UI reference: https://www.jaegertracing.io/docs/latest/frontend-ui/

## Environment variables reference

| Variable | Default | Description |
|---|---|---|
| `TRACING_ENABLED` | `false` | Set to `true` to enable span export |
| `OTEL_SERVICE_NAME` | `entity-resolution-service` | Service name shown in the trace backend |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | — | Base URL of the OTLP receiver (no path suffix) |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | — | Transport protocol; use `http/protobuf` |
| `OTEL_EXPORTER_OTLP_HEADERS` | — | Auth headers for remote backends |
| `OTEL_RESOURCE_ATTRIBUTES` | — | Extra resource tags (namespace, environment, etc.) |
