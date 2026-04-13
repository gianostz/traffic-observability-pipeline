# Slice: B2 Generator + Kafka

The following plan should be complete, but it is important to validate documentation
and codebase patterns before implementing.

Pay special attention to: the pure-vs-Spark-aware split for `schemas.py`, the
`confluent-kafka` C-library wheel compatibility in the generator Dockerfile, and the
status-code distribution weights that make dashboard panels non-trivial.

## Slice Description

Stand up the synthetic event generator and wire it to Kafka. After B2 lands, a
contributor can run `docker compose up -d` and within 30 seconds see well-formed
JSON events flowing through `kafka-console-consumer --topic web_events`. The events
conform to the PRD §5.1 schema, draw `server_id` from a real `data/servers.csv`
registry, jitter `event_ts` backwards by 0–30 s to exercise the watermark in B3, and
distribute `status_code` so that error-rate panels will be non-trivial (5 % 4xx,
1 % 5xx). This slice also lands `src/common/schemas.py` as a **pure Python** event
schema definition (no `pyspark` import) that the generator imports and that B3 will
later extend with a `StructType` builder in `src/streaming/`.

## User Story

As a **contributor about to start B3 (Spark + Iceberg)**
I want to **see realistic HTTP access-log events flowing through Kafka with
predictable field names, types, and value distributions**
So that **I can build the Spark consumer, parser, and enrichment join against a live
topic without also having to build the producer at the same time**.

## Problem Statement

The B1 skeleton declared Kafka, Postgres, and Grafana in `docker-compose.yml`, but
there is no producer, no event schema code, no server registry data, and no generator
container. As a result:

- The `web_events` topic has no data, so B3 cannot be developed or validated.
- The event schema exists only in PRD prose — there is no code-level contract that
  both the generator and the future Spark consumer can share.
- The server registry (`data/servers.csv`) does not exist, so the broadcast-join
  enrichment in B3 has nothing to join against.
- The generator Dockerfile and compose service are missing, so the "one command
  startup" promise is broken.

## Solution Statement

Land the generator end-to-end in one slice:

1. **`src/common/schemas.py`** — pure Python event schema (field names, types as
   strings, domain constants: path templates, status-code weights, user-agent pool).
   No `pyspark` import. B3 will add a `StructType` builder in `src/streaming/`.
2. **`data/servers.csv`** — ~30 rows of server registry data across 3 regions,
   6 datacenters, 3 services, all `prod`.
3. **`src/generator/producer.py`** — the event emitter. Reads config via
   `src/common/config.py`, reads `servers.csv` at startup, produces JSON events to
   Kafka at the configured rate with the configured jitter.
4. **`docker/generator/Dockerfile`** — `python:3.11-slim` + `confluent-kafka`.
5. **`generator` service in `docker-compose.yml`** — depends on kafka healthy,
   auto-starts.
6. **Unit tests** for the pure event-generation functions.
7. **Integration test** — testcontainers Kafka, produce events, consume back, assert
   schema conformance.
8. **`DECISIONS.md`** entries for the Kafka client choice, the pure-schema split, and
   the generator integration test.

## Slice Metadata

**Slice Type**: New Pipeline Capability
**Estimated Complexity**: Medium
**Components Touched**: generator, schemas, config, docker-compose, data, tests
**Touches version triangle**: No — no Spark/Iceberg/Hadoop changes.

---

## DATA CONTRACT IMPACT

### Event Schema (`src/common/schemas.py`)

**New file.** Defines the event contract as pure Python — no `pyspark` import.

| Field         | Python type hint | Kafka JSON type | Notes                                |
|---------------|------------------|-----------------|--------------------------------------|
| `event_id`    | `str`            | string          | UUID v4                              |
| `event_ts`    | `str`            | string          | ISO-8601 UTC, e.g. `2026-04-08T14:23:51.482Z` |
| `server_id`   | `str`            | string          | FK into servers.csv                  |
| `method`      | `str`            | string          | HTTP method                          |
| `path`        | `str`            | string          | From fixed template set              |
| `status_code` | `int`            | integer         | Weighted: 94 % 2xx, 5 % 4xx, 1 % 5xx |
| `bytes_sent`  | `int`            | integer         | 100–50 000                           |
| `duration_ms` | `int`            | integer         | 1–2000, skewed low                   |
| `remote_ip`   | `str`            | string          | Synthetic IPv4 from 192.0.2.0/24 (TEST-NET-1) |
| `user_agent`  | `str`            | string          | One of a small fixed set             |

### Lakehouse Table

No change — Iceberg table does not exist yet (B3).

### Serving Tables (`sql/init.sql`)

No change — serving tables do not exist yet (B4).

### Generator (`src/generator/producer.py`)

**New file.** This IS the generator.

### Dashboard

No change — dashboard does not exist yet (B5).

---

## DECISIONS TO LOG

- **D-014 — `confluent-kafka` over `kafka-python` for the generator producer**
  - **Context**: PRD §6 lists both as options. The generator needs a Python Kafka
    client to produce events.
  - **Options considered**: `confluent-kafka` (librdkafka-based, pre-built wheels),
    `kafka-python` (pure Python, unmaintained since 2023).
  - **Chosen**: `confluent-kafka`
  - **Rationale**: Actively maintained (latest release April 2026), pre-built wheels
    bundle librdkafka so no system-level C deps at install time, compatible with
    Kafka 4.x via protocol versioning, significantly higher throughput than
    `kafka-python` (irrelevant at 10 ev/s but removes a future concern).
    `kafka-python` has been effectively unmaintained since late 2023.

- **D-015 — `schemas.py` is pure Python; `StructType` construction deferred to `src/streaming/`**
  - **Context**: `src/common/schemas.py` is listed in the PRD as holding the
    explicit `StructType` for the Kafka payload. But `src/common/` must not import
    `pyspark` (CLAUDE.md structural rule, NFR-3.1). A `StructType` requires
    `from pyspark.sql.types import ...`.
  - **Options considered**: (a) make `schemas.py` the exception to the pyspark
    ban, (b) move `schemas.py` to `src/streaming/`, (c) define the schema as pure
    Python in `src/common/schemas.py` and build the `StructType` in
    `src/streaming/`.
  - **Chosen**: Option (c) — pure Python schema in `src/common/`, `StructType`
    builder in `src/streaming/`.
  - **Rationale**: Preserves the structural rule without exception. The generator
    needs the field names but not the `StructType`. The pure schema is
    unit-testable. The `StructType` builder in B3 is trivial and lives where Spark
    imports are expected.

- **D-016 — Generator reads `servers.csv` at startup, not from a config-provided list**
  - **Context**: The generator needs valid `server_id` values. Options are (a) read
    `data/servers.csv` at startup, (b) hardcode a list in the generator, (c) accept
    a comma-separated env var.
  - **Options considered**: all three above.
  - **Chosen**: Option (a) — read `data/servers.csv`.
  - **Rationale**: Single source of truth. The same file is broadcast-joined in B3.
    If the registry changes, both the generator and the enrichment join see the
    same data. The file path is configurable via `SERVER_REGISTRY_PATH` env var.

- **D-017 — Integration test for producer → Kafka via testcontainers**
  - **Context**: The generator is the source of truth for what enters the pipeline.
    Unit tests validate the pure event-generation functions, but do not exercise the
    serialization path (JSON encoding) or the actual Kafka produce/consume round-trip.
    A broken serialization or a field-name typo would only surface after a full
    `docker compose up -d` + manual `kafka-console-consumer` check.
  - **Options considered**: (a) no integration test — validate only via manual
    `kafka-console-consumer` after compose-up, (b) testcontainers Kafka integration
    test that produces events and consumes them back.
  - **Chosen**: Option (b) — testcontainers Kafka integration test.
  - **Rationale**: The generator does not touch Spark, so its integration test is
    lightweight (~15–20 s, just a Kafka container). It catches serialization bugs and
    field-name mismatches automatically, without requiring the full stack. The cost is
    small: one test file, `confluent-kafka` added as a test dependency, and
    `testcontainers[kafka]` (already budgeted in `pyproject.toml` for B3+). This
    complements — not replaces — the manual smoke test.

---

## CONTEXT REFERENCES

### Relevant Codebase Files — READ BEFORE IMPLEMENTING

- `src/common/config.py` (lines 1–123) — existing config pattern: frozen dataclasses,
  `_get()` / `_get_int()` helpers, `load_*_config()` factory functions. Mirror this
  exactly.
- `tests/unit/test_config.py` (lines 1–69) — unit test pattern: `patch.dict(os.environ, {...}, clear=True)`.
- `docker-compose.yml` (lines 1–84) — existing service declarations: image,
  container_name, hostname, ports, environment, healthcheck, networks, volumes.
  The generator service must follow this pattern.
- `.env.example` (lines 1–28) — env var naming: SCREAMING_SNAKE_CASE, grouped by
  component.
- `DECISIONS.md` (lines 1–660) — D-001 through D-013 already exist. New entries
  start at D-014.
- `pyproject.toml` (lines 1–30) — dependency declaration pattern, ruff/mypy config.

### New Files to Create

- `src/common/schemas.py` — pure Python event schema: field definitions, domain
  constants (path templates, status-code weights, user-agent pool, HTTP methods).
- `data/servers.csv` — static server registry, ~30 rows.
- `src/generator/producer.py` — synthetic event emitter entrypoint.
- `docker/generator/Dockerfile` — `python:3.11-slim` + `confluent-kafka`.
- `docker/generator/requirements.txt` — pinned `confluent-kafka` version for the
  Docker build (the generator runs inside a container, not in the host venv).
- `tests/unit/test_schemas.py` — unit tests for the schema module.
- `tests/unit/test_producer.py` — unit tests for the pure event-generation functions.
- `tests/integration/test_generator_kafka.py` — integration test: produce events to
  testcontainers Kafka, consume back, assert schema conformance.

### Relevant Documentation — READ BEFORE IMPLEMENTING

- [confluent-kafka Python Producer API](https://docs.confluent.io/platform/current/clients/confluent-kafka-python/html/index.html#confluent_kafka.Producer)
  — Section: Producer class. Why: callback pattern, `flush()` semantics, `produce()`
  signature.
- [confluent-kafka PyPI](https://pypi.org/project/confluent-kafka/)
  — Why: verify latest version and wheel availability for python:3.11-slim.
- [Kafka 4.0 protocol compatibility](https://docs.confluent.io/platform/current/installation/versions-interoperability.html)
  — Why: confirm confluent-kafka (librdkafka) works with apache/kafka:4.0.2.

### Patterns to Follow

**Naming**: snake_case for Python, lowercase for Kafka topics.

**Pure-vs-Spark-aware split**: `schemas.py` in `src/common/` is pure Python. No
`pyspark`, no `StructType`. Domain constants (path templates, status weights) also
live here so the generator and future transformation tests share them.

**Config**: every new config value reads from an env var via `src/common/config.py`.
New key for B2: `SERVER_REGISTRY_PATH`.

**Logging**: structured logging (key=value). No `print()` in `src/`.

**Docker**: the generator is a standalone container with its own `requirements.txt`.
It does NOT share the host `pyproject.toml` deps — the host venv is for linting and
testing, not for running the generator.

---

## IMPLEMENTATION PLAN

### Phase 1: Schema & Reference Data

Create the pure Python event schema and the server registry CSV. These have zero
external dependencies and are immediately unit-testable.

1. `src/common/schemas.py` — field definitions, domain constants.
2. `data/servers.csv` — ~30 rows.
3. `tests/unit/test_schemas.py` — validate field list, constant pools.

### Phase 2: Config Update

Add the `SERVER_REGISTRY_PATH` config key to the existing config module.

4. `src/common/config.py` — add to `GeneratorConfig`.
5. `.env.example` — add `SERVER_REGISTRY_PATH`.
6. `tests/unit/test_config.py` — extend with new key test.

### Phase 3: Generator Code

Implement the producer. Pure event-generation logic is unit-testable; the Kafka
producing is validated by `kafka-console-consumer` after compose-up.

7. `src/generator/producer.py` — the entrypoint.
8. `tests/unit/test_producer.py` — unit tests for pure generation functions.

### Phase 4: Container & Compose

Build the Dockerfile and wire the generator into docker-compose.

9. `docker/generator/requirements.txt` — pinned `confluent-kafka`.
10. `docker/generator/Dockerfile` — image build.
11. `docker-compose.yml` — add generator service.

### Phase 5: Integration Test

12. `pyproject.toml` — add `confluent-kafka` and `testcontainers[kafka]` to dev deps.
13. `tests/integration/test_generator_kafka.py` — produce → consume round-trip test.

### Phase 6: Decisions & Validation

14. `DECISIONS.md` — add D-014, D-015, D-016, D-017.
15. Full validation suite.

---

## STEP-BY-STEP TASKS

### CREATE `src/common/schemas.py`

- **IMPLEMENT**: Define the event schema as pure Python. Include:
  - `EVENT_FIELDS`: a tuple of `(field_name, type_string)` pairs matching PRD §5.1.
    Type strings: `"string"`, `"timestamp"`, `"int"`, `"long"`. These are descriptive
    labels the generator uses; B3 maps them to `StructType` fields.
  - `PATH_TEMPLATES`: a tuple of realistic HTTP path templates, e.g.
    `("/api/users/:id", "/api/orders", "/api/products/:id", "/health", "/static/css/main.css", "/static/js/app.js", "/api/auth/login", "/api/search")`.
    At least 8 entries so top-N panels are meaningful.
  - `STATUS_CODE_WEIGHTS`: a tuple of `(status_code, weight)` pairs. Distribution:
    - 200: 0.70, 201: 0.05, 204: 0.04, 301: 0.05, 304: 0.05 → ~89 % success
    - 400: 0.02, 401: 0.01, 403: 0.01, 404: 0.02 → ~6 % 4xx (close enough to ~5 %)
    - 500: 0.005, 502: 0.003, 503: 0.002 → ~1 % 5xx
    (Weights must sum to 1.0.)
  - `HTTP_METHODS`: a tuple of `(method, weight)` pairs. `GET` dominant (~70 %),
    `POST` (~15 %), `PUT` (~8 %), `DELETE` (~5 %), `PATCH` (~2 %).
  - `USER_AGENTS`: a tuple of realistic user-agent strings (5–8 entries).
    E.g. `"Mozilla/5.0 (Windows NT 10.0; Win64; x64)"`,
    `"curl/8.4.0"`, `"python-requests/2.31.0"`, etc.
- **PATTERN**: mirror `src/common/config.py` style — pure stdlib, frozen data, docstrings.
- **IMPORTS**: `from __future__ import annotations` only. No third-party imports.
- **GOTCHA**: Do NOT import `pyspark`. This file is `src/common/` — the pure zone.
  The `StructType` mapping lives in `src/streaming/` and is built in B3.
- **VALIDATE**: `uv run python -c "from src.common.schemas import EVENT_FIELDS, PATH_TEMPLATES, STATUS_CODE_WEIGHTS; print(len(EVENT_FIELDS), 'fields')"` — should print `10 fields`.

### CREATE `data/servers.csv`

- **IMPLEMENT**: CSV with header row and ~30 data rows. Columns: `server_id`, `region`,
  `datacenter`, `service`, `environment`. Naming convention from PRD example:
  `{service}-{region_abbrev}-{nn}`. Use:
  - Regions: `us-east`, `us-west`, `eu-central`
  - Datacenters: `us-east-1a`, `us-east-1b`, `us-west-2a`, `us-west-2b`,
    `eu-central-1a`, `eu-central-1b`
  - Services: `web`, `api`, `static`
  - Environment: always `prod`
  - Distribution: ~10 per region, mix of services per datacenter.
  - Server ID format: `web-use1-01`, `api-usw2-03`, `static-euc1-02`, etc.
- **PATTERN**: plain CSV, no quoting unless a field contains a comma (none will).
- **IMPORTS**: n/a (data file).
- **GOTCHA**: Ensure no trailing whitespace, no BOM, LF line endings. The file will
  be read by both Python `csv.reader` (generator) and `spark.read.csv` (B3).
- **VALIDATE**: `uv run python -c "import csv; rows = list(csv.DictReader(open('data/servers.csv'))); print(len(rows), 'servers'); assert all(r['environment'] == 'prod' for r in rows)"` — should print `30 servers` (or similar).

### CREATE `tests/unit/test_schemas.py`

- **IMPLEMENT**: Test that:
  - `EVENT_FIELDS` has exactly 10 entries matching PRD §5.1 field names.
  - `STATUS_CODE_WEIGHTS` weights sum to ~1.0 (within float tolerance).
  - `HTTP_METHODS` weights sum to ~1.0.
  - `PATH_TEMPLATES` has at least 8 entries.
  - `USER_AGENTS` has at least 5 entries.
  - No duplicate field names in `EVENT_FIELDS`.
  - No duplicate paths in `PATH_TEMPLATES`.
- **PATTERN**: mirror `tests/unit/test_config.py` — plain pytest functions, no fixtures needed.
- **IMPORTS**: `from src.common.schemas import ...`
- **GOTCHA**: None.
- **VALIDATE**: `uv run pytest tests/unit/test_schemas.py -q`

### UPDATE `src/common/config.py`

- **IMPLEMENT**: Add `server_registry_path: str` to `GeneratorConfig`. Default:
  `data/servers.csv` (relative — works on the host for tests; the Dockerfile sets
  the env var to the absolute container path `/app/data/servers.csv`).
  Add the field to `load_generator_config()`.
- **PATTERN**: mirror existing fields in `GeneratorConfig` (line 33–37).
- **IMPORTS**: no new imports.
- **GOTCHA**: The default must work from the repo root on the host (for `uv run pytest`)
  AND inside the container (via env var override).
- **VALIDATE**: `uv run python -c "from src.common.config import load_generator_config; print(load_generator_config())"` — should show the new field.

### UPDATE `.env.example`

- **IMPLEMENT**: Add under the `# ---------- Generator ----------` section:
  ```
  SERVER_REGISTRY_PATH=data/servers.csv
  ```
- **PATTERN**: mirror existing entries.
- **IMPORTS**: n/a.
- **GOTCHA**: None.
- **VALIDATE**: visual inspection.

### UPDATE `tests/unit/test_config.py`

- **IMPLEMENT**: Add a test that `load_generator_config()` includes
  `server_registry_path` with the correct default, and that it reads from the env
  var when set.
- **PATTERN**: mirror `test_generator_config_coerces_int()` (line 38–45).
- **IMPORTS**: add `load_generator_config` to existing import if not already there.
- **GOTCHA**: None.
- **VALIDATE**: `uv run pytest tests/unit/test_config.py -q`

### CREATE `src/generator/producer.py`

- **IMPLEMENT**: The synthetic event emitter. Structure:
  1. **`load_server_ids(path: str) -> list[str]`** — read `data/servers.csv`, return
     the `server_id` column. Pure function, unit-testable.
  2. **`generate_event(server_ids: list[str], now: datetime) -> dict[str, Any]`** —
     produce a single event dict matching the schema. Pure function, unit-testable.
     Uses `random.choices` with weights from `schemas.py` for `status_code`, `method`,
     `path`, `user_agent`. Generates:
     - `event_id`: `str(uuid.uuid4())`
     - `event_ts`: `now - timedelta(seconds=random.uniform(0, jitter))`, formatted
       as ISO-8601 UTC string with milliseconds: `dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"`
     - `server_id`: `random.choice(server_ids)`
     - `method`: weighted random from `HTTP_METHODS`
     - `path`: weighted random from `PATH_TEMPLATES`
     - `status_code`: weighted random from `STATUS_CODE_WEIGHTS`
     - `bytes_sent`: `random.randint(100, 50_000)`
     - `duration_ms`: `int(random.paretovariate(1.5) * 10)` clamped to [1, 2000]
       (gives a realistic long-tail latency distribution)
     - `remote_ip`: `f"192.0.2.{random.randint(1, 254)}"` (TEST-NET-1 per RFC 5737)
     - `user_agent`: uniform random from `USER_AGENTS`
  3. **`create_producer(config: KafkaConfig) -> confluent_kafka.Producer`** — factory.
     Config: `{"bootstrap.servers": config.bootstrap_servers}`. No acks override
     (default is `acks=1` per PRD §7.1).
  4. **`delivery_callback(err, msg)`** — log errors at WARNING, successes at DEBUG.
     Structured logging (key=value).
  5. **`run(kafka_cfg: KafkaConfig, gen_cfg: GeneratorConfig) -> None`** — the main
     loop. Load server IDs, create producer, loop forever: generate event, serialize
     as JSON (UTF-8), `producer.produce(topic, value, callback=delivery_callback)`,
     `producer.poll(0)`, sleep `1.0 / rate_per_sec`. Periodic `producer.flush()` not
     needed on every iteration — `poll(0)` handles delivery reports.
  6. **`if __name__ == "__main__":` / `main()`** — load config, configure logging
     (`logging.basicConfig` with structured format), call `run()`. Handle
     `KeyboardInterrupt` gracefully with a final `producer.flush()`.
- **PATTERN**: structured logging only, no `print()`. Config via `load_kafka_config()`
  and `load_generator_config()`.
- **IMPORTS**: `confluent_kafka`, `json`, `uuid`, `random`, `time`, `datetime`,
  `logging`, `csv`, `src.common.config`, `src.common.schemas`.
- **GOTCHA**: `confluent-kafka` is only installed inside the Docker container, not in
  the host venv. The host venv has no `confluent_kafka` — this is intentional. Unit
  tests for the pure functions (`generate_event`, `load_server_ids`) must not import
  `confluent_kafka`. Structure the file so pure functions are at the top and the
  Kafka-dependent code is in the lower half, or guard Kafka imports in the functions
  that need them.
- **VALIDATE**: `uv run python -c "from src.generator.producer import generate_event, load_server_ids; ids = load_server_ids('data/servers.csv'); e = generate_event(ids, __import__('datetime').datetime.now(__import__('datetime').timezone.utc)); print(e)"` — should print a valid event dict (will fail if `confluent_kafka` is imported at module top level — that's the test).

### CREATE `tests/unit/test_producer.py`

- **IMPLEMENT**: Test the pure functions:
  - `test_load_server_ids` — reads `data/servers.csv`, returns a non-empty list of
    strings, all match expected format.
  - `test_generate_event_has_all_fields` — call `generate_event()`, verify all 10
    fields are present with correct types.
  - `test_generate_event_server_id_from_pool` — verify `server_id` is one of the
    provided IDs.
  - `test_generate_event_timestamp_is_jittered` — call with a known `now`, verify
    `event_ts` is between `now - 30s` and `now`.
  - `test_generate_event_status_code_is_valid` — verify status_code is an int in the
    set of defined codes.
  - `test_generate_event_ip_in_test_net` — verify `remote_ip` matches `192.0.2.*`.
  - `test_generate_event_duration_clamped` — run 1000 events, verify all `duration_ms`
    values are in [1, 2000].
  - `test_generate_event_bytes_sent_range` — verify `bytes_sent` in [100, 50000].
- **PATTERN**: mirror `tests/unit/test_config.py`.
- **IMPORTS**: `from src.generator.producer import generate_event, load_server_ids`,
  `datetime`, `timezone`.
- **GOTCHA**: These tests must NOT trigger a `confluent_kafka` import. The producer
  module must be structured so that importing the pure functions does not pull in
  `confluent_kafka`. If it does, the host venv (which lacks `confluent_kafka`) will
  fail with `ModuleNotFoundError`. Use a conditional import or put Kafka-dependent
  code behind `if TYPE_CHECKING` or in a separate function that is not imported by
  tests.
- **VALIDATE**: `uv run pytest tests/unit/test_producer.py -q`

### CREATE `docker/generator/requirements.txt`

- **IMPLEMENT**: Single line: `confluent-kafka==2.14.0` (latest stable as of
  April 2026). Verify on PyPI before pinning.
- **PATTERN**: n/a.
- **IMPORTS**: n/a.
- **GOTCHA**: The `confluent-kafka` wheel bundles `librdkafka`. No system-level
  `apt install` is needed on `python:3.11-slim` — the manylinux wheel is self-
  contained.
- **VALIDATE**: `docker build -t test-gen docker/generator/` (after Dockerfile exists).

### CREATE `docker/generator/Dockerfile`

- **IMPLEMENT**:
  ```dockerfile
  FROM python:3.11-slim

  WORKDIR /app

  COPY requirements.txt .
  RUN pip install --no-cache-dir -r requirements.txt

  COPY ../../src/common/ src/common/
  COPY ../../src/generator/ src/generator/
  COPY ../../src/__init__.py src/__init__.py
  COPY ../../data/ data/
  ```
  **IMPORTANT**: Docker `COPY` does not support `../../` relative paths. The build
  context must be the repo root, and the Dockerfile path is specified via
  `build.dockerfile` in `docker-compose.yml`. So the COPY paths are relative to
  the repo root:
  ```dockerfile
  FROM python:3.11-slim

  WORKDIR /app

  COPY docker/generator/requirements.txt .
  RUN pip install --no-cache-dir -r requirements.txt

  COPY src/common/ src/common/
  COPY src/generator/ src/generator/
  COPY src/__init__.py src/__init__.py
  COPY data/ data/

  ENV SERVER_REGISTRY_PATH=/app/data/servers.csv
  ENV PYTHONUNBUFFERED=1

  CMD ["python", "-m", "src.generator.producer"]
  ```
- **PATTERN**: standard Python container pattern.
- **IMPORTS**: n/a.
- **GOTCHA**: Build context is the repo root (`.`), not `docker/generator/`. Set
  `build.context: .` and `build.dockerfile: docker/generator/Dockerfile` in
  `docker-compose.yml`. Set `PYTHONUNBUFFERED=1` so logs appear immediately in
  `docker compose logs`.
- **VALIDATE**: `docker build -f docker/generator/Dockerfile -t top-generator .`

### UPDATE `docker-compose.yml`

- **IMPLEMENT**: Add the `generator` service after the `grafana` service block.
  ```yaml
  generator:
    build:
      context: .
      dockerfile: docker/generator/Dockerfile
    container_name: top-generator
    hostname: generator
    environment:
      KAFKA_BOOTSTRAP_SERVERS: kafka:9092
      KAFKA_TOPIC: ${KAFKA_TOPIC:-web_events}
      GENERATOR_RATE_PER_SEC: ${GENERATOR_RATE_PER_SEC:-10}
      GENERATOR_JITTER_SECONDS: ${GENERATOR_JITTER_SECONDS:-30}
      SERVER_REGISTRY_PATH: /app/data/servers.csv
    depends_on:
      kafka:
        condition: service_healthy
    restart: unless-stopped
    networks:
      - top-net
  ```
  No ports (the generator has no API). No volumes (data is baked into the image).
  No healthcheck — the generator is a fire-and-forget producer; if it crashes,
  `restart: unless-stopped` brings it back. `depends_on: kafka: service_healthy`
  ensures Kafka is ready before the generator starts.
- **PATTERN**: mirror existing services (kafka, postgres, grafana) for style:
  `container_name`, `hostname`, `networks`.
- **IMPORTS**: n/a.
- **GOTCHA**: The generator does NOT need a healthcheck. It is not a dependency of
  any other service in B2. In B3, the Spark service depends on Kafka being healthy,
  not on the generator.
- **VALIDATE**: `docker compose config --quiet` — exits 0 if valid.

### UPDATE `pyproject.toml`

- **IMPLEMENT**: Add `confluent-kafka` and `testcontainers[kafka]` to the `dev`
  dependency group:
  ```toml
  [dependency-groups]
  dev = [
      "ruff>=0.6",
      "mypy>=1.10",
      "pytest>=8.0",
      "confluent-kafka>=2.14",
      "testcontainers[kafka]>=4.0",
  ]
  ```
  Then run `uv sync` to update `uv.lock`.
- **PATTERN**: mirror existing dev deps.
- **IMPORTS**: n/a.
- **GOTCHA**: `confluent-kafka` is now in the host venv too (for tests and mypy).
  This is intentional — it allows `uv run mypy src` to resolve the import and
  allows the integration test to use the real producer code.
- **VALIDATE**: `uv sync && uv run python -c "import confluent_kafka; print(confluent_kafka.version())"`

### CREATE `tests/integration/test_generator_kafka.py`

- **IMPLEMENT**: Integration test for the producer → Kafka round-trip.
  1. **Fixture `kafka_container`** (session-scoped) — start a Kafka container via
     `testcontainers.kafka.KafkaContainer`. Yield the bootstrap server address.
     Tear down after the session.
  2. **`test_produce_and_consume_events`**:
     - Create a `confluent_kafka.Producer` with the testcontainer's bootstrap server.
     - Call `generate_event()` 10 times, serialize each as JSON, produce to a test
       topic (e.g. `test_web_events`).
     - `producer.flush()`.
     - Create a `confluent_kafka.Consumer` with `auto.offset.reset=earliest`,
       subscribe to the same topic.
     - Consume 10 messages (with a timeout).
     - For each message: deserialize JSON, assert all 10 PRD §5.1 fields are present,
       assert types are correct (event_id is a string, status_code is an int, etc.).
     - Assert `server_id` is in the set loaded from `data/servers.csv`.
  3. **`test_event_json_is_valid_utf8`**:
     - Produce one event, consume it, assert `msg.value().decode("utf-8")` succeeds,
       assert `json.loads(...)` succeeds.
- **PATTERN**: session-scoped fixture for the Kafka container (same pattern the
  project will use for the SparkSession fixture in B3).
- **IMPORTS**: `confluent_kafka`, `testcontainers.kafka`, `json`,
  `src.generator.producer`, `src.common.schemas`.
- **GOTCHA**: The testcontainers Kafka image may differ from `apache/kafka:4.0.2`.
  This is acceptable — the test validates serialization and field conformance, not
  broker-version-specific behavior. If the testcontainers default image causes
  issues, pin it to match the compose image.
- **VALIDATE**: `uv run pytest tests/integration/test_generator_kafka.py -q`

### UPDATE `DECISIONS.md`

- **IMPLEMENT**: Add D-014, D-015, D-016, D-017 using the content from the "Decisions
  to Log" section above. Follow the existing format (D-001 through D-013): Status,
  Date, Tags, Context, Decision, Consequences, Alternatives considered, Revisit when.
  Update the Index table.
- **PATTERN**: mirror D-013 (most recent entry) for formatting.
- **IMPORTS**: n/a.
- **GOTCHA**: Decision IDs are monotonically increasing. D-014 is next.
- **VALIDATE**: visual inspection — index matches entries.

---

## TESTING STRATEGY

### Unit Tests

| Test file | Functions tested | Key edge cases |
|---|---|---|
| `tests/unit/test_schemas.py` | Schema constants | Field count matches PRD, weights sum to 1.0, no duplicates |
| `tests/unit/test_producer.py` | `generate_event`, `load_server_ids` | All fields present, correct types, jitter within bounds, IP in TEST-NET-1, duration clamped, status codes from defined set |
| `tests/unit/test_config.py` | `load_generator_config` (extended) | New `server_registry_path` field defaults and env override |

### Integration Test

| Test file | What it exercises | Runtime |
|---|---|---|
| `tests/integration/test_generator_kafka.py` | Produce 10 events → testcontainers Kafka → consume back → assert all 10 fields present with correct types, valid JSON/UTF-8, `server_id` from registry | ~15–20 s (Kafka container boot) |

Justification: the generator is the only component that doesn't touch Spark, so its
integration test is lightweight (no SparkSession). It catches serialization bugs and
field-name mismatches that unit tests cannot. Logged as D-017.

### Edge Cases

- **Kafka not ready**: `depends_on: service_healthy` + `restart: unless-stopped`
  handles this. If the generator starts before Kafka is ready, it crashes and restarts.
- **Empty servers.csv**: `load_server_ids` should raise a clear error, not silently
  produce events with no server_id.
- **Invalid CSV path**: `load_server_ids` should raise `FileNotFoundError`.
- **Generator restart**: idempotent — it just produces more events. No state to
  corrupt.

---

## VALIDATION COMMANDS

### Level 1: Syntax & Style
```bash
uv run ruff check src tests
uv run mypy src
```

### Level 2: Unit Tests
```bash
uv run pytest tests/unit -q
```

### Level 3: Integration Tests
```bash
uv run pytest tests/integration -q
```

### Level 4: Stack Smoke Test
```bash
docker compose up -d --build
sleep 30
docker compose ps
```

### Level 5: Slice-Specific Validation

See the **Generator Validation Guide** below — it is the Level 5 validation for this
slice.

---

## GENERATOR VALIDATION GUIDE

A step-by-step guide for verifying that the generator is working correctly and
events are landing in Kafka. Run these checks after `docker compose up -d --build`.

### Step 1: Verify all services are running

```bash
docker compose ps
```

**What "good" looks like:**
```
NAME             IMAGE                    ...  STATUS                    PORTS
top-generator    ...-generator            ...  Up 25 seconds
top-grafana      grafana/grafana:12.4.2   ...  Up 28 seconds (healthy)  0.0.0.0:3000->3000/tcp
top-kafka        apache/kafka:4.0.2       ...  Up 30 seconds (healthy)  0.0.0.0:9092->9092/tcp
top-postgres     postgres:16.13           ...  Up 30 seconds (healthy)  0.0.0.0:5432->5432/tcp
```

**What "bad" looks like:**
- `top-generator` shows `Restarting (1) ...` in a loop → Kafka may not be healthy
  yet (wait longer), or there is a code error. Check logs: `docker compose logs generator --tail 30`.
- `top-kafka` is not `(healthy)` → the broker hasn't finished startup. Wait for the
  healthcheck to pass before diagnosing the generator.

### Step 2: Check the generator logs

```bash
docker compose logs generator --tail 20
```

**What "good" looks like:**
- Structured log lines (key=value or JSON format), no Python tracebacks.
- A startup message indicating the generator loaded the server registry and started
  producing.
- No `ERROR` or `WARNING` lines (an occasional delivery warning on the very first
  event is acceptable — Kafka may still be electing a leader).

**What "bad" looks like:**
- `ModuleNotFoundError: No module named 'confluent_kafka'` → the Docker image was
  not built correctly. Run `docker compose build generator` and check the Dockerfile.
- `FileNotFoundError: ... servers.csv` → the CSV was not copied into the image, or
  `SERVER_REGISTRY_PATH` is wrong. Check the Dockerfile `COPY` directives.
- `KafkaException: ... broker transport failure` → Kafka is not reachable. Verify
  `KAFKA_BOOTSTRAP_SERVERS` is set to `kafka:9092` (the Docker network hostname, not
  `localhost`).

### Step 3: Verify the `web_events` topic exists

```bash
docker compose exec kafka /opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server localhost:9092 --list
```

**What "good" looks like:** output includes `web_events`.

**What "bad" looks like:** `web_events` is missing → the generator has not
successfully produced any events yet. Check generator logs (Step 2).

### Step 4: Consume a sample of events

```bash
docker compose exec kafka /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 --topic web_events \
  --from-beginning --max-messages 3
```

**What "good" looks like:** 3 JSON lines, each containing all 10 fields:

```json
{"event_id": "7c3a9f0e-...", "event_ts": "2026-04-10T15:23:51.482Z", "server_id": "web-use1-01", "method": "GET", "path": "/api/users/:id", "status_code": 200, "bytes_sent": 4821, "duration_ms": 47, "remote_ip": "192.0.2.137", "user_agent": "curl/8.4.0"}
```

**Check each field:**
- `event_id` — looks like a UUID (8-4-4-4-12 hex pattern).
- `event_ts` — ISO-8601 UTC timestamp, within ~30 seconds of the current wall clock
  (it will be jittered backwards).
- `server_id` — matches an entry in `data/servers.csv` (e.g. `web-use1-01`,
  `api-usw2-03`).
- `method` — one of `GET`, `POST`, `PUT`, `DELETE`, `PATCH`.
- `path` — one of the fixed templates (e.g. `/api/users/:id`, `/health`).
- `status_code` — an integer (200, 201, 204, 301, 304, 400, 401, 403, 404, 500, 502, 503).
- `bytes_sent` — integer between 100 and 50,000.
- `duration_ms` — integer between 1 and 2,000.
- `remote_ip` — in the `192.0.2.*` range (TEST-NET-1).
- `user_agent` — one of the defined user-agent strings.

**What "bad" looks like:**
- Empty output / hangs → no events in the topic. Go back to Step 2.
- JSON with missing fields → schema mismatch between `schemas.py` and `producer.py`.
- `status_code` is a string instead of an integer → serialization bug.
- `event_ts` is far from wall clock (e.g. hours off) → jitter logic is wrong.

### Step 5: Verify the topic is receiving events continuously

```bash
docker compose exec kafka /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 --topic web_events \
  --timeout-ms 10000 2>/dev/null | wc -l
```

`--timeout-ms` here is an *idle* timeout: the consumer exits only after 10 seconds
with no new message. At the target rate of 10 ev/s (gaps ~100 ms), the idle timeout
should never fire, so the command should keep running until you Ctrl+C it. This
gives a liveness signal: events are flowing steadily, with no multi-second gap.

**What "good" looks like:** the command keeps printing events and does not exit on
its own. Interrupt it after a few seconds with Ctrl+C.

**What "bad" looks like:**
- Command exits on its own and `wc -l` prints `0` → no events arrived in 10 s. The
  generator is not producing (crashed, blocked on Kafka, sleeping too long).
- Command exits on its own with a small count → events stopped partway through,
  suggesting the generator crashed or stalled mid-run.

### Step 6: Pretty-print one event (optional, for readability)

```bash
docker compose exec kafka /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 --topic web_events \
  --from-beginning --max-messages 1 2>/dev/null | python -m json.tool
```

This formats the JSON with indentation so you can visually inspect the structure.

### Step 7: Verify server_id coverage (optional, longer run)

After the generator has been running for a few minutes:

```bash
docker compose exec kafka /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 --topic web_events \
  --from-beginning --timeout-ms 5000 2>/dev/null \
  | python -c "
import json, sys
ids = set()
for line in sys.stdin:
    ids.add(json.loads(line)['server_id'])
print(f'{len(ids)} unique server_ids seen')
"
```

**What "good" looks like:** close to the number of rows in `data/servers.csv` (e.g.
"28 unique server_ids seen" out of 30). With uniform random selection and thousands
of events, you should see most server IDs represented.

### Quick reference: one-liner health check

For a fast pass/fail after `docker compose up -d --build`:

```bash
sleep 30 && docker compose ps && \
docker compose exec kafka /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 --topic web_events \
  --from-beginning --max-messages 1 2>/dev/null | python -m json.tool && \
echo "=== B2 PASS ==="
```

If you see the pretty-printed JSON followed by `=== B2 PASS ===`, the slice is
working.

---

## ACCEPTANCE CRITERIA

- [ ] `docker compose up -d --build` starts kafka, postgres, grafana, AND generator
- [ ] `docker compose ps` shows generator running (no restart loop)
- [ ] `kafka-console-consumer` shows JSON events on `web_events` within 30 seconds
- [ ] Each event has all 10 fields from PRD §5.1 with correct types
- [ ] `server_id` in every event exists in `data/servers.csv`
- [ ] `event_ts` is jittered backwards 0–30 s from wall clock
- [ ] Status code distribution is approximately 94 % 2xx / 5 % 4xx / 1 % 5xx
- [ ] `uv run ruff check src tests` passes with zero warnings
- [ ] `uv run mypy src` passes with zero errors
- [ ] `uv run pytest tests/unit -q` passes (including new schema and producer tests)
- [ ] `uv run pytest tests/integration -q` passes (producer → Kafka round-trip)
- [ ] `src/common/schemas.py` does NOT import `pyspark`
- [ ] `src/generator/producer.py` pure functions are importable without `confluent_kafka`
- [ ] Generator Validation Guide steps 1–5 all pass
- [ ] DECISIONS.md has D-014, D-015, D-016, D-017
- [ ] No hardcoded broker addresses or file paths in `src/`

---

## COMPLETION CHECKLIST

- [ ] All tasks completed in order
- [ ] Each task validation passed before moving to the next
- [ ] Full validation suite green
- [ ] Generator Validation Guide confirmed (steps 1–5 pass)
- [ ] `DECISIONS.md` updated with D-014, D-015, D-016, D-017
- [ ] Slice plan annotated as complete in `.agents/plans/`

---

## NOTES

- The `confluent-kafka` package is now in the host `pyproject.toml` dev dependencies
  (needed for the integration test and for `uv run mypy src` to resolve the import).
  The generator Docker image uses its own `requirements.txt` with a pinned version.
  Both install the same library — the dev dep uses `>=2.14` (floor pin) and the
  Docker image uses `==2.14.0` (exact pin for reproducibility).
- The `duration_ms` Pareto distribution (`paretovariate(1.5) * 10`, clamped to
  [1, 2000]) produces a realistic long-tail: most requests complete in 10–100 ms,
  with occasional spikes to 500–2000 ms. This makes the p50/p95/p99 latency panel
  visually interesting.
- `remote_ip` uses the 192.0.2.0/24 TEST-NET-1 range (RFC 5737), which is reserved
  for documentation and examples. This avoids accidentally generating a real IP.
- The generator has no state — restarting it is always safe.
- B3 will add a `build_struct_type()` function in `src/streaming/` that reads
  `EVENT_FIELDS` from `schemas.py` and constructs the PySpark `StructType`.
