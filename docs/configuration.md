# Configuration Reference

ERS is configured through a combination of environment variables and YAML configuration
files. Environment variable values are resolved lazily at property access time. If a `.env`
file is present in the working directory it is loaded once at process startup via
`python-dotenv`; environment variables already set in the process take precedence over
`.env` values.

## Configuration groups

Each environment variable belongs to one of the groups below, reflecting the component or
concern it configures. The [Environment Variables](#environment-variables) table lists all
variables alphabetically with the group in a dedicated column.

**Admin** — Credentials for the built-in administrator account seeded into the database on
first run. Both variables are mandatory; the service will raise an error on startup if
either is absent.

**Curation API** — Presentation and behaviour settings for the Curation REST API (the
link-curation backend). Adjust `CORS_ORIGINS` to restrict cross-origin access in
production; the default `["*"]` is suitable for development only.

**Decision Store** — Pagination and storage limits for the entity resolution decision store.
`DECISION_STORE_DEFAULT_PAGE_SIZE` must not exceed `DECISION_STORE_MAX_PAGE_SIZE`; the
service enforces this at startup.

**ERE Integration** — Controls the boundary between ERS and the Entity Resolution Engine
(ERE). `REFRESH_BULK_MAX_LIMIT` caps the number of mentions accepted in a single bulk
request forwarded to ERE.

**ERS REST API** — Identity and network settings for the ERS REST API process, which runs
on a separate port from the Curation API.

**JWT / Auth** — Token signing and expiry settings for the JWT-based authentication layer.
`JWT_SECRET_KEY` is mandatory and must be a strong random string of at least 32 characters.

**MongoDB** — Connection settings for the MongoDB (or Amazon DocumentDB) database used to
persist entity resolution decisions. Both variables must point to the same database
instance.

**Observability** — OpenTelemetry tracing configuration. Tracing is disabled by default;
set `TRACING_ENABLED=true` and configure an OTLP exporter to enable distributed tracing.
`OTEL_SERVICE_NAME` is only meaningful when tracing is enabled.

**RDF Mention Parser** — Path and size settings for the RDF mention parsing step.
`ERS_PARSER_MAX_CONTENT_LENGTH` protects the service from oversized payloads (default: 1 MiB).

**Redis** — Connection and channel configuration for the Redis broker used to communicate
with ERE. The four connection variables (`REDIS_HOST`, `REDIS_PORT`, `REDIS_DB`,
`REDIS_PASSWORD`) must all point to the same Redis instance. `ERE_REQUEST_CHANNEL` and
`ERE_RESPONSE_CHANNEL` must match the `REQUEST_QUEUE` and `RESPONSE_QUEUE` values
configured on the ERE side.

**Resolution Coordinator** — Time budget settings for the resolution coordinator. Setting
either budget to `0` enables immediate provisional mode: ERS skips ERE submission entirely
and returns a provisional identifier without any Redis interaction.

## Environment Variables

| Name | Group | Description | Default | Mandatory | Related Variables |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT / Auth | Access token validity period in minutes. | `15` | No | `REFRESH_TOKEN_EXPIRE_MINUTES` |
| `ADMIN_EMAIL` | Admin | Email address for the default administrator account. | | **Yes** | `ADMIN_PASSWORD` |
| `ADMIN_PASSWORD` | Admin | Password for the default administrator account. | | **Yes** | `ADMIN_EMAIL` |
| `API_V1_PREFIX` | Curation API | URL prefix for the Curation API v1 endpoints. | `/api/v1` | No | |
| `APP_NAME` | Curation API | Application name displayed in the Curation API documentation. | `Curation REST API` | No | |
| `CORS_ORIGINS` | Curation API | JSON array of allowed CORS origins. Restrict to the Link Curation UI domain in production. | `["*"]` | No | |
| `DEBUG` | Curation API | Enable debug mode. | `false` | No | |
| `DECISION_STORE_DEFAULT_PAGE_SIZE` | Decision Store | Default page size for decision store queries. Must not exceed `DECISION_STORE_MAX_PAGE_SIZE`. | `250` | No | `DECISION_STORE_MAX_PAGE_SIZE` |
| `DECISION_STORE_MAX_CANDIDATES` | Decision Store | Maximum number of resolution candidates stored per entity mention. | `5` | No | |
| `DECISION_STORE_MAX_PAGE_SIZE` | Decision Store | Maximum allowed page size for decision store queries. | `1000` | No | `DECISION_STORE_DEFAULT_PAGE_SIZE` |
| `ERE_REQUEST_CHANNEL` | Redis | Redis list key for outbound resolution requests sent to ERE. Must match ERE's `REQUEST_QUEUE`. | `ere_requests` | No | `ERE_RESPONSE_CHANNEL` |
| `ERE_RESPONSE_CHANNEL` | Redis | Redis list key for inbound resolution results received from ERE. Must match ERE's `RESPONSE_QUEUE`. | `ere_responses` | No | `ERE_REQUEST_CHANNEL` |
| `ERS_API_NAME` | ERS REST API | Application name displayed in the ERS API documentation. | `ERS REST API` | No | |
| `ERS_API_PORT` | ERS REST API | Port on which the ERS API listens. | `8001` | No | |
| `ERS_API_PREFIX` | ERS REST API | URL prefix for the ERS API v1 endpoints. | `/api/v1` | No | |
| `ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET` | Resolution Coordinator | Maximum time budget in seconds for a bulk resolution response (all mentions combined). Set to `0` to disable the outer timeout entirely. | `120` | No | `ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET` |
| `ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET` | Resolution Coordinator | Maximum time budget in seconds for a single-mention resolution response; also the ERE wait window. Set to `0` to enable immediate provisional mode (no Redis interaction). | `30` | No | `ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET` |
| `ERS_NOTIFICATIONS_CHANNEL` | Redis | Redis Pub/Sub channel used to broadcast ERE outcome notifications across ERS instances. | `ers_notifications` | No | |
| `ERS_PARSER_MAX_CONTENT_LENGTH` | RDF Mention Parser | Maximum byte length of RDF content accepted by the mention parser. | `1048576` | No | |
| `JWT_ALGORITHM` | JWT / Auth | JWT signing algorithm. | `HS256` | No | `JWT_SECRET_KEY` |
| `JWT_SECRET_KEY` | JWT / Auth | Secret key for signing JWT tokens. Must be a strong random string of at least 32 characters. | | **Yes** | `JWT_ALGORITHM` |
| `MONGO_DATABASE_NAME` | MongoDB | MongoDB database name. | `ers` | No | `MONGO_URI` |
| `MONGO_URI` | MongoDB | MongoDB connection URI. | `mongodb://username:password@localhost:27017` | No | `MONGO_DATABASE_NAME` |
| `OTEL_SERVICE_NAME` | Observability | OpenTelemetry service name used in trace exports. Only meaningful when `TRACING_ENABLED=true`. | `entity-resolution-service` | No | `TRACING_ENABLED` |
| `RDF_MENTION_CONFIG_FILE` | RDF Mention Parser | Path to the RDF mention configuration YAML file. | `config/rdf_mention_config.yaml` | No | |
| `REDIS_DB` | Redis | Redis database number. | `0` | No | `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD` |
| `REDIS_HOST` | Redis | Redis server hostname or endpoint. | `localhost` | No | `REDIS_PORT`, `REDIS_DB`, `REDIS_PASSWORD` |
| `REDIS_PASSWORD` | Redis | Redis authentication password. Leave empty if Redis AUTH is not configured. | | No | `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB` |
| `REDIS_PORT` | Redis | Redis server port. | `6379` | No | `REDIS_HOST`, `REDIS_DB`, `REDIS_PASSWORD` |
| `REDIS_SOCKET_CONNECT_TIMEOUT` | Redis | Seconds to wait when establishing a new Redis connection before raising an error. | `5.0` | No | `REDIS_HOST`, `REDIS_PORT` |
| `REFRESH_BULK_MAX_LIMIT` | ERE Integration | Maximum number of entity mentions accepted in a single bulk resolution request. | `1000` | No | |
| `REFRESH_TOKEN_EXPIRE_MINUTES` | JWT / Auth | Refresh token validity period in minutes. Must be greater than `ACCESS_TOKEN_EXPIRE_MINUTES`. | `10080` | No | `ACCESS_TOKEN_EXPIRE_MINUTES` |
| `TRACING_ENABLED` | Observability | Enable OpenTelemetry tracing. | `false` | No | `OTEL_SERVICE_NAME` |

## RDF Mention Mapping: `src/config/rdf_mention_config.yaml`

Maps RDF entity types to extraction rules used when parsing incoming entity mentions. It
tells ERS how to identify each entity type in RDF and which property paths to follow when
extracting attribute values.

**`namespaces`** — prefix registry used to resolve shortened property paths throughout the
file. Each entry maps a prefix (e.g. `epo`) to its full IRI base (e.g.
`http://data.europa.eu/a4g/ontology#`). All prefixes used in `fields` values must be
declared here.

**`entity_types`** — one entry per supported entity type (e.g. `ORGANISATION`,
`PROCEDURE`). Each entry contains:

| Key | Type | Purpose |
|-----|------|---------|
| `rdf_type` | prefixed IRI string | RDF class that identifies this entity type (e.g. `org:Organization`) |
| `fields` | mapping of field name → property path | Attributes to extract; `/` separates hops for multi-step traversal (e.g. `cccev:registeredAddress/epo:hasCountryCode`) |

Field names defined here must match the field names expected by the Entity Resolution
Engine. To add a new entity type, add a new key under `entity_types` with its `rdf_type`
and the `fields` to extract. To add a new attribute to an existing type, add a new key
under its `fields` mapping with the corresponding RDF property path.

The path to this file is controlled by the `RDF_MENTION_CONFIG_FILE` environment variable.
