# Slice: B3 — Spark + Iceberg

The following plan should be complete, but it is important to validate documentation
and codebase patterns before implementing.

Pay special attention to: the pinned JAR versions in `docker/spark/Dockerfile`, the
Kafka connector transitive resolution strategy (do NOT pin `kafka-clients` or
`commons-pool2`), and the pure-vs-Spark-aware boundary for transformations.

## Slice Description

Stand up the Spark Structured Streaming job and the Iceberg lakehouse sink. After B3
lands, a contributor can run `docker compose up -d` and within 90 seconds see enriched
events flowing from Kafka into `lakehouse.web_events`, queryable via the Spark shell.
The events are parsed with an explicit `StructType`, broadcast-enriched against
`data/servers.csv`, and appended to an Iceberg table partitioned by
`hours(event_ts)`. Malformed and unenrichable events are dropped and counted in a
structured per-batch log line.

This slice also lands `src/common/transformations.py` with pure-Python parse and
enrich functions that serve as the unit-tested specification for the business logic
the Spark job implements via DataFrame API.

## User Story

As a **contributor about to start B4 (Postgres serving sinks)**
I want to **see enriched HTTP access-log events accumulating in an Iceberg table with
region, datacenter, and service columns populated from the server registry**
So that **I can build the four aggregation queries and Postgres sinks against a live
Iceberg table without also having to build the Spark job, parse logic, enrichment
join, or Iceberg integration at the same time**.

## Problem Statement

The B2 generator emits well-formed JSON events to Kafka, but there is no consumer.
As a result:

- Events accumulate in Kafka but nothing reads them.
- There is no Spark container, no Iceberg table, no enrichment join.
- The `docker/spark/Dockerfile` does not exist — the Spark image with
  Iceberg/Kafka/JDBC JARs has not been built.
- `src/common/transformations.py` does not exist — there are no pure-function parse
  or enrich implementations.
- `src/streaming/` has only `__init__.py` — the streaming job and Iceberg sink are
  missing.
- The `spark` service is not declared in `docker-compose.yml`.

## Solution Statement

Land the Spark + Iceberg layer end-to-end in one slice:

1. **`docker/spark/Dockerfile`** — `apache/spark:3.5.8` base image with
   Iceberg 1.10.1, Kafka connector 3.5.8 (transitives resolved via Ivy at build
   time), and PostgreSQL JDBC 42.7.10 JARs pre-downloaded.
2. **`src/common/transformations.py`** — pure Python functions: `load_server_registry`,
   `parse_event_json`, `enrich_event`. No `pyspark` import. Unit-tested specification
   of the business logic.
3. **`src/streaming/schemas_spark.py`** — `StructType` builder that maps
   `src/common/schemas.py` field definitions to PySpark types. Lives in `streaming/`
   per D-015.
4. **`src/streaming/iceberg_sink.py`** — Iceberg table creation (CREATE TABLE IF NOT
   EXISTS) and append write function.
5. **`src/streaming/stream_processor.py`** — streaming job entrypoint: SparkSession
   setup with Iceberg catalog config, Kafka source, parse via `from_json`, broadcast
   join, `foreachBatch` with Iceberg append + structured logging.
6. **`spark` service in `docker-compose.yml`** — depends on kafka healthy, mounts
   warehouse + checkpoint volumes, exposes Spark UI on 4040.
7. **`tests/unit/test_transformations.py`** — unit tests for every pure function.
8. **`DECISIONS.md`** entries for JAR versions and download strategy, and pyspark as
   host dev dependency.

## Slice Metadata

**Slice Type**: New Pipeline Capability
**Estimated Complexity**: High
**Components Touched**: streaming job, transformations, schemas (StructType builder),
iceberg sink, docker-compose, Spark Dockerfile, tests
**Touches version triangle**: **Yes** — Spark 3.5.8 + Iceberg 1.10.1 + Hadoop 3.x +
Scala 2.12 + Java 11. Double the slack budget.

---

## DATA CONTRACT IMPACT

### Event Schema (`src/common/schemas.py`)
**No change.** The pure Python schema from B2 is consumed as-is. The `StructType`
builder in `src/streaming/schemas_spark.py` maps these field definitions to PySpark
types.

### Lakehouse Table
**New table: `lakehouse.web_events`** created by Spark on first micro-batch.

| Column        | Iceberg Type | Source                          |
|---------------|--------------|---------------------------------|
| `event_id`    | string       | Kafka payload                   |
| `event_ts`    | timestamp    | Kafka payload (parsed from ISO-8601 string) |
| `server_id`   | string       | Kafka payload                   |
| `method`      | string       | Kafka payload                   |
| `path`        | string       | Kafka payload                   |
| `status_code` | int          | Kafka payload                   |
| `bytes_sent`  | long         | Kafka payload (bigint per PRD §5.4) |
| `duration_ms` | int          | Kafka payload                   |
| `remote_ip`   | string       | Kafka payload                   |
| `user_agent`  | string       | Kafka payload                   |
| `region`      | string       | enriched (registry join)        |
| `datacenter`  | string       | enriched (registry join)        |
| `service`     | string       | enriched (registry join)        |
| `ingest_ts`   | timestamp    | enriched (Spark `current_timestamp()`) |

- **Partition spec:** `PARTITIONED BY (hours(event_ts))` (D-002)
- **Sort order:** unsorted (D-002)
- **Write mode:** append-only via `foreachBatch`
- **Backfill:** N/A — new table, no existing data.

### Serving Tables (`sql/init.sql`)
**No change in B3.** Postgres serving tables are created in B4.

### Generator (`src/generator/producer.py`)
**No change.** The generator from B2 is consumed as-is.

### Dashboard
**No change in B3.** Grafana dashboard is created in B5.

---

## DECISIONS TO LOG

- **D-018 — Pinned JAR versions: Spark 3.5.8, Iceberg 1.10.1, Kafka connector 3.5.8, JDBC 42.7.10**
  - **Context**: B3 introduces the Spark container with custom JARs. The
    Spark/Iceberg/Hadoop version triangle is the highest-risk component in the stack
    (PRD §14). Every JAR must be pinned explicitly.
  - **Options considered**: (a) Pin all JARs via direct download, (b) use
    `--packages` at runtime, (c) mix — direct download for fat JARs, Ivy for
    connector transitives.
  - **Chosen**: (c) — Direct download for Iceberg runtime (fat JAR, no transitives)
    and PostgreSQL JDBC (standalone). Ivy-resolved at Docker build time for
    `spark-sql-kafka-0-10` so its transitives (`kafka-clients`, `commons-pool2`) are
    pulled by Maven dependency resolution, not manually pinned.
  - **Rationale**: Respects the CLAUDE.md hard rule ("do not pin `kafka-clients`,
    `commons-pool2` explicitly"). The Iceberg runtime is a shaded fat JAR that bundles
    everything. Ivy resolution at build time means no internet needed at container
    start.

- **D-019 — `pyspark>=3.5,<3.6` as host dev dependency**
  - **Context**: `src/streaming/` imports `pyspark`. NFR-3.3 requires `uv run mypy
    src` to pass, which requires resolving pyspark types on the host. The integration
    test also needs a host-side SparkSession to validate the Kafka→Spark→Iceberg path.
  - **Options considered**: (a) Add pyspark to dev deps, (b) exclude `src/streaming/`
    from mypy, (c) use third-party stubs only.
  - **Chosen**: (a) — `pyspark>=3.5,<3.6` in the `dev` dependency group.
  - **Rationale**: The streaming code must be type-checked like everything else. The
    pyspark package is only a dev dependency — it runs inside Docker in production.
    It is also required for the B3 integration test (SparkSession on host).

- **D-020 — Integration test for Kafka→Spark→Iceberg path via testcontainers**
  - **Context**: B3 introduces the Spark/Iceberg/Kafka classpath — the highest-risk
    part of the stack. Unit tests validate pure functions but cannot catch classpath
    collisions, Iceberg catalog config bugs, or Kafka connector wire-protocol issues.
    The manual smoke test catches these but is not repeatable or CI-friendly.
  - **Options considered**: (a) Defer to B6, validate only via manual smoke test,
    (b) add integration test in B3 using testcontainers Kafka + host SparkSession +
    temp Iceberg warehouse.
  - **Chosen**: (b) — Add a focused integration test in B3 that produces events to
    testcontainers Kafka, reads them via Spark's Kafka connector, enriches via
    broadcast join, and writes to a temp Iceberg warehouse on local FS.
  - **Rationale**: The classpath is where B3 is most likely to break. An automated
    test that exercises the real Spark→Kafka→Iceberg path catches JAR skew and config
    bugs before the Docker image is ever built. Reuses the existing testcontainers
    Kafka fixture from `test_generator_kafka.py`. The SparkSession is session-scoped
    to amortize boot cost (D-008). Uses `spark.jars.packages` to resolve the same
    JARs the Dockerfile uses — validates that the Maven coordinates are correct.

---

## CONTEXT REFERENCES

### Relevant Codebase Files — READ BEFORE IMPLEMENTING

- `src/common/schemas.py` (lines 1–72) — pure Python field definitions and domain
  constants. The `StructType` builder must map these, not duplicate them.
- `src/common/config.py` (lines 42–105) — `SparkConfig`, `KafkaConfig`, and
  `PostgresConfig` dataclasses with all env-var keys. The streaming job must use these.
- `src/generator/producer.py` (lines 34–75) — `generate_event` shows the exact field
  names and value ranges. Parse/validate functions must match.
- `data/servers.csv` (lines 1–31) — 30 rows, 5 columns. The broadcast join key is
  `server_id`. Enrichment adds `region`, `datacenter`, `service`.
- `docker-compose.yml` (lines 1–100) — existing services: kafka, postgres, grafana,
  generator. Spark service must follow the same patterns (healthcheck, named volumes,
  env-var substitution, `top-net` network).
- `DECISIONS.md` — D-001 through D-017. Respect all. Key ones for B3: D-001 (single
  app, foreachBatch), D-002 (hourly partition), D-005 (broadcast join), D-006 (Hadoop
  catalog), D-015 (StructType in streaming/).
- `.env.example` (lines 1–29) — all config keys. Spark keys already defined.

### New Files to Create

| Path | Purpose |
|------|---------|
| `docker/spark/Dockerfile` | Spark image with pinned Iceberg/Kafka/JDBC JARs |
| `src/common/transformations.py` | Pure Python parse + enrich functions (no pyspark) |
| `src/streaming/schemas_spark.py` | `StructType` builder mapping schemas.py → PySpark types |
| `src/streaming/iceberg_sink.py` | Iceberg table creation + append write |
| `src/streaming/stream_processor.py` | Streaming job entrypoint |
| `tests/unit/test_transformations.py` | Unit tests for every pure function |
| `tests/integration/conftest.py` | Shared session-scoped fixtures: testcontainers Kafka + SparkSession |
| `tests/integration/test_spark_iceberg.py` | Integration test: Kafka→Spark read→enrich→Iceberg write |

### Files to Update

| Path | Change |
|------|--------|
| `docker-compose.yml` | Add `spark` service |
| `pyproject.toml` | Add `pyspark>=3.5,<3.6` to dev deps |
| `DECISIONS.md` | Add D-018, D-019, D-020 |

### Relevant Documentation — READ BEFORE IMPLEMENTING

- [Iceberg: Spark Structured Streaming](https://iceberg.apache.org/docs/latest/spark-structured-streaming/)
  - Section: Appending data / Writing with DataFrames
  - Why: Confirms the `writeTo(...).append()` API for foreachBatch Iceberg writes

- [Iceberg: Spark Configuration](https://iceberg.apache.org/docs/latest/spark-configuration/)
  - Section: Catalogs
  - Why: Exact config keys for Hadoop catalog (`spark.sql.catalog.<name>.type=hadoop`,
    `.warehouse`)

- [Spark: Structured Streaming Programming Guide](https://spark.apache.org/docs/3.5.8/structured-streaming-programming-guide.html)
  - Section: Using foreachBatch
  - Why: foreachBatch contract — receives (DataFrame, batchId), must be idempotent

- [Spark: Kafka Integration](https://spark.apache.org/docs/3.5.8/structured-streaming-kafka-integration.html)
  - Section: Creating a Kafka Source for Streaming Queries
  - Why: Required options (`kafka.bootstrap.servers`, `subscribe`, `startingOffsets`)

### Patterns to Follow

**Naming**: snake_case for Python, lowercase for Iceberg identifiers, `SCREAMING_SNAKE`
for env vars.

**Pure-vs-Spark-aware split**: `src/common/transformations.py` has zero pyspark
imports. It defines the business logic as pure functions. `src/streaming/` implements
the same logic via DataFrame API for performance ("no per-row Python" rule).

**Schema declaration**: The `StructType` is built in `src/streaming/schemas_spark.py`
by mapping `EVENT_FIELDS` from `src/common/schemas.py`. No duplicate field name lists.

**foreachBatch body**: Idempotent. One structured log line per batch. No per-row Python
(no UDFs). Batch metrics: batch_id, input_count, iceberg_rows, malformed_dropped,
unenriched_dropped, elapsed_sec.

**Config**: All values via `src/common/config.py`. No hardcoded URLs.

**Logging**: `logging` stdlib, structured key=value format. No `print()`.

---

## IMPLEMENTATION PLAN

### Phase 1: Pure Functions & StructType Builder

Create `src/common/transformations.py` with pure-Python parse and enrich functions
that serve as the unit-tested specification:

- `load_server_registry(path: str) -> dict[str, dict[str, str]]` — reads
  `data/servers.csv`, returns `{server_id: {region, datacenter, service, environment}}`.
- `parse_event_json(raw: str) -> dict[str, Any] | None` — parses JSON, validates all
  10 fields present with correct types. Returns `None` for malformed events.
- `enrich_event(event: dict[str, Any], registry: dict[str, dict[str, str]]) -> dict[str, Any] | None`
  — adds `region`, `datacenter`, `service` from registry lookup on `server_id`.
  Returns `None` for unknown server_id.

Create `src/streaming/schemas_spark.py`:

- `build_event_struct() -> StructType` — maps `EVENT_FIELDS` from `schemas.py` to
  PySpark types. Type mapping: `"string"` → `StringType`, `"int"` → `IntegerType`.
  `bytes_sent` is mapped to `LongType` (PRD §5.4 says `bigint`).
- `build_enriched_struct() -> StructType` — event struct + `region`, `datacenter`,
  `service` (StringType), `ingest_ts` (TimestampType).

### Phase 2: Spark Dockerfile

Create `docker/spark/Dockerfile` with:

- Base image: `apache/spark:3.5.8-scala2.12-java11-python3-r-ubuntu`
- Direct-download JARs:
  - `iceberg-spark-runtime-3.5_2.12-1.10.1.jar` (fat JAR)
  - `postgresql-42.7.10.jar` (standalone)
- Ivy-resolved at build time:
  - `org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.8` + transitives
- Copy `src/` and `data/` into `/app/`
- Set `PYTHONPATH=/app`, `PYTHONUNBUFFERED=1`
- CMD: `spark-submit --master local[*] /app/src/streaming/stream_processor.py`

### Phase 3: Streaming Job + Iceberg Sink

Create `src/streaming/iceberg_sink.py`:

- `ensure_table(spark: SparkSession, catalog: str, table: str) -> None` — runs
  `CREATE TABLE IF NOT EXISTS` via `spark.sql(...)` with the enriched schema and
  `PARTITIONED BY (hours(event_ts))`.
- `append_to_iceberg(df: DataFrame, catalog: str, table: str) -> int` — writes
  DataFrame via `df.writeTo(f"{catalog}.{table}").append()`, returns row count.

Create `src/streaming/stream_processor.py`:

1. **SparkSession setup**: Iceberg catalog config (`spark.sql.catalog.lakehouse`,
   `.type=hadoop`, `.warehouse`), Iceberg extensions.
2. **Load server registry**: `spark.read.csv(path, header=True)` → `broadcast(...)`.
3. **Kafka source**: `spark.readStream.format("kafka")` with `subscribe`,
   `kafka.bootstrap.servers`, `startingOffsets=earliest`.
4. **Parse**: `CAST(value AS STRING)` → `from_json(col, event_struct)` →
   `select("event.*")` → `filter` out nulls (malformed).
5. **Convert types**: `to_timestamp(col("event_ts"))` to convert ISO-8601 string →
   TimestampType. Cast `bytes_sent` to `LongType`.
6. **Enrich**: `inner join` on `broadcast(registry_df)` on `server_id`. Inner join
   naturally drops events with unknown server_id.
7. **Add ingest_ts**: `withColumn("ingest_ts", current_timestamp())`.
8. **Ensure Iceberg table exists** (called once at startup).
9. **foreachBatch callback**:
   ```
   def process_batch(batch_df: DataFrame, batch_id: int) -> None:
       if batch_df.isEmpty():
           log empty batch, return
       start = time.time()
       input_count = batch_df.count()
       # Append to Iceberg
       iceberg_rows = append_to_iceberg(batch_df, catalog, table)
       # Structured log line
       logger.info("event=batch_complete batch_id=%d input_rows=%d ...")
   ```
10. **Start streaming query**: `.foreachBatch(process_batch)` with checkpoint location
    from config.

**Drop counting strategy**: Malformed events (null after `from_json`) and unenriched
events (dropped by inner join) are counted by comparing row counts at each stage:
- `raw_count` = rows from Kafka
- `parsed_count` = rows after null filter (malformed_dropped = raw - parsed)
- `enriched_count` = rows after join (unenriched_dropped = parsed - enriched)

These counts are logged in the per-batch structured log line.

### Phase 4: Docker Compose

Add `spark` service to `docker-compose.yml`:

```yaml
spark:
  build:
    context: .
    dockerfile: docker/spark/Dockerfile
  container_name: top-spark
  hostname: spark
  ports:
    - "4040:4040"
  environment:
    KAFKA_BOOTSTRAP_SERVERS: kafka:9092
    KAFKA_TOPIC: ${KAFKA_TOPIC:-web_events}
    SPARK_DRIVER_MEMORY: ${SPARK_DRIVER_MEMORY:-2g}
    SPARK_EXECUTOR_MEMORY: ${SPARK_EXECUTOR_MEMORY:-2g}
    SPARK_CHECKPOINT_DIR: /opt/checkpoints/web_events
    ICEBERG_WAREHOUSE_DIR: /opt/warehouse
    ICEBERG_CATALOG: lakehouse
    ICEBERG_TABLE: web_events
    WATERMARK_DURATION: ${WATERMARK_DURATION:-2 minutes}
    SERVER_REGISTRY_PATH: /app/data/servers.csv
  depends_on:
    kafka:
      condition: service_healthy
  volumes:
    - spark_warehouse:/opt/warehouse
    - spark_checkpoints:/opt/checkpoints
  networks:
    - top-net
```

Add `spark_warehouse` and `spark_checkpoints` to the top-level `volumes:` block.

### Phase 5: Tests & Validation

Create `tests/unit/test_transformations.py`:

- `test_load_server_registry_returns_all_servers` — 30 entries from servers.csv
- `test_load_server_registry_keys_match_csv` — spot-check server_id → region mapping
- `test_load_server_registry_empty_file_raises` — ValueError on empty CSV
- `test_parse_event_json_valid` — round-trip a generate_event() output
- `test_parse_event_json_malformed` — bad JSON returns None
- `test_parse_event_json_missing_field` — missing required field returns None
- `test_parse_event_json_wrong_type` — string where int expected returns None
- `test_enrich_event_known_server` — adds region/datacenter/service
- `test_enrich_event_unknown_server` — returns None
- `test_enrich_event_preserves_all_original_fields` — no fields lost

Update `pyproject.toml`: add `pyspark>=3.5,<3.6` to dev dependencies.

---

## STEP-BY-STEP TASKS

Execute every task in order, top to bottom. Each task is atomic and validates
immediately.

### 1. CREATE `src/common/transformations.py`

- **IMPLEMENT**: Three pure functions:
  1. `load_server_registry(path: str) -> dict[str, dict[str, str]]` — read CSV with
     `csv.DictReader`, build dict keyed by `server_id` with values
     `{region, datacenter, service, environment}`. Raise `ValueError` if empty.
  2. `parse_event_json(raw: str) -> dict[str, Any] | None` — `json.loads`, validate
     all 10 field names from `EVENT_FIELDS` are present, validate types (`status_code`,
     `bytes_sent`, `duration_ms` are int). Return `None` on any failure.
  3. `enrich_event(event: dict[str, Any], registry: dict[str, dict[str, str]]) -> dict[str, Any] | None`
     — lookup `event["server_id"]` in registry. If found, return `{**event, **registry_row}`
     (adding `region`, `datacenter`, `service`, `environment`). If not found, return `None`.
- **PATTERN**: `src/generator/producer.py:34-41` — `load_server_ids` is a simpler
  version of `load_server_registry`. Mirror the CSV reading pattern.
- **IMPORTS**: `csv`, `json`, `logging` from stdlib. `EVENT_FIELDS` from
  `src.common.schemas`. No pyspark.
- **GOTCHA**: Do NOT import `pyspark` — this file is under `src/common/`.
- **VALIDATE**: `python -c "from src.common.transformations import load_server_registry, parse_event_json, enrich_event; print('OK')"`

### 2. CREATE `tests/unit/test_transformations.py`

- **IMPLEMENT**: 10+ test functions covering all three pure functions with happy path
  and edge cases (see Phase 5 above for full list).
- **PATTERN**: `tests/unit/test_producer.py` — same style: import pure functions,
  use `data/servers.csv` for registry tests, generate events via
  `src.generator.producer.generate_event` for parse/enrich tests.
- **IMPORTS**: `pytest`, `json`, `src.common.transformations`, `src.common.schemas`,
  `src.generator.producer.generate_event`.
- **GOTCHA**: Do NOT import pyspark in unit tests.
- **VALIDATE**: `uv run pytest tests/unit/test_transformations.py -q`

### 3. CREATE `tests/integration/conftest.py`

- **IMPLEMENT**: Shared session-scoped fixtures for the integration test suite:
  1. `kafka_container` — start a `KafkaContainer`, yield it, stop on teardown.
     Refactored from the inline fixture in `test_generator_kafka.py` (which should be
     updated to import from `conftest.py` instead of defining its own).
  2. `bootstrap_server(kafka_container)` — return
     `kafka_container.get_bootstrap_server()`.
  3. `spark_session(tmp_path_factory)` — build a SparkSession with:
     ```python
     SparkSession.builder \
         .master("local[*]") \
         .appName("integration-tests") \
         .config("spark.jars.packages",
                 "org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.10.1,"
                 "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.8") \
         .config("spark.sql.catalog.test_lakehouse",
                 "org.apache.iceberg.spark.SparkCatalog") \
         .config("spark.sql.catalog.test_lakehouse.type", "hadoop") \
         .config("spark.sql.catalog.test_lakehouse.warehouse",
                 str(tmp_path_factory.mktemp("iceberg_warehouse"))) \
         .config("spark.sql.extensions",
                 "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions") \
         .config("spark.driver.memory", "1g") \
         .config("spark.ui.enabled", "false") \
         .getOrCreate()
     ```
     Yield the session, stop on teardown.
  4. `iceberg_warehouse(tmp_path_factory)` — return the warehouse path (reused by
     tests that need to inspect the filesystem).
- **PATTERN**: `tests/integration/test_generator_kafka.py:17-29` — existing
  `kafka_container` and `bootstrap_server` fixtures. Lift them into conftest.
- **IMPORTS**: `pytest`, `testcontainers.kafka.KafkaContainer`, `pyspark.sql.SparkSession`.
- **GOTCHA**: The first `spark_session` creation triggers Ivy resolution of
  `spark.jars.packages` — this downloads JARs on first run (~30 s). Subsequent runs
  use the Ivy cache. The session-scoped fixture ensures this happens once per
  `pytest` invocation.
- **GOTCHA**: Use `spark.ui.enabled=false` to avoid port conflicts with a running
  Docker stack.
- **VALIDATE**: `uv run pytest tests/integration --co -q` (collect-only, no execution)

### 4. CREATE `tests/integration/test_spark_iceberg.py`

- **IMPLEMENT**: Four integration tests:
  1. `test_spark_reads_from_kafka(spark_session, bootstrap_server)` — produce 10
     events via `confluent_kafka.Producer`, read them back via
     `spark.read.format("kafka").option("kafka.bootstrap.servers", ...).option("subscribe", topic).load()`,
     parse with `from_json(col("value").cast("string"), build_event_struct())`,
     assert 10 rows, assert all 10 field names present.
  2. `test_broadcast_enrich_drops_unknown_server(spark_session)` — create a DataFrame
     with two rows (one known server_id from `servers.csv`, one unknown), load
     registry via `spark.read.csv("data/servers.csv", header=True)`, broadcast-join,
     assert only the known row survives.
  3. `test_iceberg_append_and_read_back(spark_session, bootstrap_server)` — produce
     events, read from Kafka, enrich via broadcast join, call
     `ensure_table(spark, "test_lakehouse", "web_events")` +
     `append_to_iceberg(df, "test_lakehouse", "web_events")`, read back via
     `spark.sql("SELECT * FROM test_lakehouse.web_events")`, assert row count > 0,
     assert enrichment columns populated (region, datacenter, service not null).
  4. `test_iceberg_table_is_partitioned_by_hour(spark_session)` — after writing,
     inspect via `spark.sql("DESCRIBE EXTENDED test_lakehouse.web_events")` or
     `spark.sql("SELECT * FROM test_lakehouse.web_events.partitions")`, assert
     partition spec includes `hours(event_ts)`.
- **PATTERN**: `tests/integration/test_generator_kafka.py:31-67` — produce/consume
  pattern. Replace Kafka consumer with Spark Kafka batch reader.
- **IMPORTS**: `confluent_kafka.Producer`, `pyspark.sql.functions`, `json`, `uuid`,
  `src.streaming.schemas_spark`, `src.streaming.iceberg_sink`,
  `src.generator.producer.generate_event`, `src.common.transformations.load_server_registry`.
- **GOTCHA**: Use `spark.read` (batch), not `spark.readStream` (streaming). Batch
  is deterministic and doesn't need checkpoints. Set
  `startingOffsets=earliest` and `endingOffsets=latest`.
- **GOTCHA**: Each test should use a unique topic name (e.g. `f"test_{uuid.uuid4().hex[:8]}"`)
  to avoid cross-test interference.
- **GOTCHA**: The Iceberg table name may conflict across tests. Use `spark.sql("DROP TABLE IF EXISTS ...")`
  in setup or use unique table names per test.
- **VALIDATE**: `uv run pytest tests/integration/test_spark_iceberg.py -q`

### 5. UPDATE `tests/integration/test_generator_kafka.py`

- **IMPLEMENT**: Remove the inline `kafka_container` and `bootstrap_server` fixtures.
  They now live in `conftest.py` and are auto-discovered by pytest.
- **PATTERN**: The test functions themselves (`test_produce_and_consume_events`,
  `test_event_json_is_valid_utf8`) remain unchanged — only the fixtures move.
- **VALIDATE**: `uv run pytest tests/integration/test_generator_kafka.py -q`

### 6. CREATE `src/streaming/schemas_spark.py`

- **IMPLEMENT**:
  1. `EVENT_TYPE_MAP: dict[str, DataType]` — maps schema type labels to PySpark types:
     `{"string": StringType(), "int": IntegerType()}`.
  2. `build_event_struct() -> StructType` — iterates `EVENT_FIELDS`, maps each
     `(name, type_label)` to `StructField(name, EVENT_TYPE_MAP[type_label])`.
     Special case: `bytes_sent` → `LongType()` (PRD §5.4 says `bigint`).
  3. `build_enriched_struct() -> StructType` — event struct fields + `region` (string),
     `datacenter` (string), `service` (string), `ingest_ts` (TimestampType).
- **PATTERN**: `src/common/schemas.py:13-24` — reads `EVENT_FIELDS` tuple, does not
  duplicate field names.
- **IMPORTS**: `pyspark.sql.types`, `src.common.schemas.EVENT_FIELDS`.
- **GOTCHA**: `bytes_sent` is `"int"` in schemas.py but must be `LongType` in the
  StructType to match PRD §5.4 (`bigint`). Hard-code this override.
- **VALIDATE**: `uv run python -c "from src.streaming.schemas_spark import build_event_struct; print(build_event_struct())"`

### 7. CREATE `src/streaming/iceberg_sink.py`

- **IMPLEMENT**:
  1. `ensure_table(spark: SparkSession, catalog: str, table: str) -> None` — executes:
     ```sql
     CREATE TABLE IF NOT EXISTS {catalog}.{table} (
         event_id STRING,
         event_ts TIMESTAMP,
         server_id STRING,
         method STRING,
         path STRING,
         status_code INT,
         bytes_sent BIGINT,
         duration_ms INT,
         remote_ip STRING,
         user_agent STRING,
         region STRING,
         datacenter STRING,
         service STRING,
         ingest_ts TIMESTAMP
     ) USING iceberg
     PARTITIONED BY (hours(event_ts))
     ```
  2. `append_to_iceberg(df: DataFrame, catalog: str, table: str) -> int` —
     `df.writeTo(f"{catalog}.{table}").append()`, returns `df.count()`.
- **PATTERN**: N/A — first Iceberg code in the repo. Follow the Iceberg Spark
  Structured Streaming docs.
- **IMPORTS**: `pyspark.sql`, `logging`.
- **GOTCHA**: `writeTo(...).append()` is the DataFrameWriterV2 API. Do NOT use
  `df.write.format("iceberg").mode("append")` — that is the V1 API which does not
  honor the catalog namespace.
- **VALIDATE**: Deferred to stack smoke test (task 8).

### 8. CREATE `src/streaming/stream_processor.py`

- **IMPLEMENT**: The streaming job entrypoint. Structure:
  1. Configure `logging` (structured key=value, INFO level).
  2. Load config: `load_kafka_config()`, `load_spark_config()`.
  3. Build `SparkSession` with Iceberg catalog config:
     - `spark.sql.catalog.{catalog}` = `org.apache.iceberg.spark.SparkCatalog`
     - `spark.sql.catalog.{catalog}.type` = `hadoop`
     - `spark.sql.catalog.{catalog}.warehouse` = config warehouse dir
     - `spark.sql.extensions` = `org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions`
     - `spark.driver.memory` and `spark.executor.memory` from config
  4. Load server registry CSV: `spark.read.csv(path, header=True, inferSchema=False)`.
     All columns are strings — no inference needed.
  5. Build event `StructType` via `build_event_struct()`.
  6. Call `ensure_table(spark, catalog, table)`.
  7. Kafka source: `spark.readStream.format("kafka")` with options:
     - `kafka.bootstrap.servers`
     - `subscribe` = topic
     - `startingOffsets` = `earliest`
  8. Parse pipeline:
     ```python
     raw = kafka_df.selectExpr("CAST(value AS STRING) as json_str")
     parsed = raw.select(
         from_json(col("json_str"), event_struct).alias("event")
     ).select("event.*")
     ```
  9. Filter malformed: `.filter(col("event_id").isNotNull())`
  10. Convert types:
      - `to_timestamp(col("event_ts"))` → overwrite `event_ts` column
      - `col("bytes_sent").cast(LongType())` → overwrite `bytes_sent`
  11. Broadcast join:
      ```python
      enriched = parsed.join(
          broadcast(registry_df),
          on="server_id",
          how="inner"
      ).withColumn("ingest_ts", current_timestamp())
      ```
  12. Select final columns in Iceberg table order.
  13. Define `process_batch(batch_df, batch_id)`:
      - If empty: log and return.
      - Count input rows.
      - Call `append_to_iceberg(...)`.
      - Log structured line: `event=batch_complete batch_id=N input_rows=N
        iceberg_rows=N elapsed_sec=N.NN`.
  14. Start query:
      ```python
      query = enriched.writeStream \
          .foreachBatch(process_batch) \
          .option("checkpointLocation", config.checkpoint_dir) \
          .start()
      query.awaitTermination()
      ```
  15. Wrap in `if __name__ == "__main__"` guard.
- **PATTERN**: `src/generator/producer.py:138-160` — entrypoint pattern (load config,
  configure logging, run main loop).
- **IMPORTS**: `pyspark.sql` (SparkSession, DataFrame, functions), `logging`, `time`,
  config loaders, schema builder, iceberg sink.
- **GOTCHA**: The `from_json` parse returns null for the entire struct if JSON is
  malformed — filtering on `event_id IS NOT NULL` catches this. However, if only
  `event_ts` is missing, the struct is non-null but `event_ts` is null. Add a filter
  for `event_ts IS NOT NULL` as well since it's the partition key.
- **GOTCHA**: `to_timestamp` without a format string defaults to
  `yyyy-MM-dd HH:mm:ss`. The generator emits `yyyy-MM-ddTHH:mm:ss.SSSZ`. Use
  `to_timestamp(col("event_ts"), "yyyy-MM-dd'T'HH:mm:ss.SSS'Z'")`.
- **GOTCHA**: Drop counting. To count malformed and unenriched events, compute counts
  BEFORE the join step inside the foreachBatch callback is not possible because the
  join happens in the streaming pipeline before foreachBatch. Instead, log only
  `input_rows` (what foreachBatch receives = already enriched) and `iceberg_rows`.
  The malformed/unenriched drops happen in the streaming plan and are not directly
  countable per-batch without caching intermediate DataFrames. **Revised approach**:
  move the join and filtering INTO the foreachBatch callback so we can count at each
  stage. The streaming pipeline produces the parsed (but not yet enriched) DataFrame,
  and foreachBatch handles enrichment + write.
- **VALIDATE**: `uv run ruff check src/streaming/stream_processor.py`

**IMPORTANT — Revised streaming architecture for drop counting:**

The parse step (from_json + null filter) stays in the streaming pipeline because it
defines the schema. But the broadcast join moves INTO `foreachBatch` so we can count:

```
streaming pipeline: kafka → parse (from_json) → convert types
                                                        ↓
foreachBatch receives: parsed DataFrame (may include unknown server_ids)
  1. count parsed rows
  2. broadcast join → enriched (inner join drops unknown server_ids)  
  3. count enriched rows
  4. unenriched_dropped = parsed - enriched
  5. append enriched to Iceberg
  6. log all counts
```

This is safe because the broadcast DataFrame (registry) is loaded once at job start
and captured in the closure. The join inside foreachBatch is cheap (broadcast).

### 9. CREATE `docker/spark/Dockerfile`

- **IMPLEMENT**:
  ```dockerfile
  FROM apache/spark:3.5.8-scala2.12-java11-python3-r-ubuntu

  USER root

  ARG ICEBERG_VERSION=1.10.1
  ARG SPARK_VERSION=3.5.8
  ARG POSTGRES_JDBC_VERSION=42.7.10

  # Iceberg runtime (fat JAR — bundles all Iceberg dependencies)
  RUN curl -fSL -o $SPARK_HOME/jars/iceberg-spark-runtime.jar \
      "https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-spark-runtime-3.5_2.12/${ICEBERG_VERSION}/iceberg-spark-runtime-3.5_2.12-${ICEBERG_VERSION}.jar"

  # PostgreSQL JDBC driver (standalone JAR — needed in B4, pre-installed now)
  RUN curl -fSL -o $SPARK_HOME/jars/postgresql.jar \
      "https://repo1.maven.org/maven2/org/postgresql/postgresql/${POSTGRES_JDBC_VERSION}/postgresql-${POSTGRES_JDBC_VERSION}.jar"

  # Kafka connector + transitives resolved by Ivy at build time
  # Per CLAUDE.md: do NOT pin kafka-clients or commons-pool2 explicitly
  RUN echo ':quit' | $SPARK_HOME/bin/spark-shell \
      --packages "org.apache.spark:spark-sql-kafka-0-10_2.12:${SPARK_VERSION}" \
      2>&1 && \
      cp -n ~/.ivy2/jars/*.jar $SPARK_HOME/jars/ 2>/dev/null; \
      rm -rf ~/.ivy2 ~/.m2

  COPY src/ /app/src/
  COPY data/ /app/data/

  USER spark
  WORKDIR /app

  ENV PYTHONPATH=/app
  ENV PYTHONUNBUFFERED=1

  CMD ["/opt/spark/bin/spark-submit", "--master", "local[*]", \
       "/app/src/streaming/stream_processor.py"]
  ```
- **PATTERN**: `docker/generator/Dockerfile` — similar structure (COPY src/, COPY
  data/, set WORKDIR, set ENV, CMD).
- **GOTCHA**: The base image user is `spark` (UID 185). Switch to `root` for JAR
  downloads, switch back to `spark` before CMD.
- **GOTCHA**: `curl -fSL` — `-f` fails on HTTP errors, `-S` shows errors, `-L`
  follows redirects. All three are required for Maven Central.
- **GOTCHA**: The Ivy `spark-shell` step may print warnings to stderr — that's
  expected. The `2>&1` captures everything; the `cp -n` is no-clobber so it won't
  overwrite JARs already in `$SPARK_HOME/jars/`.
- **GOTCHA**: The image tag `3.5.8-scala2.12-java11-python3-r-ubuntu` includes R.
  If a tag without R exists (`3.5.8-scala2.12-java11-python3-ubuntu`), prefer it
  for a smaller image. Check Docker Hub at build time. Both work identically.
- **VALIDATE**: `docker build -f docker/spark/Dockerfile -t top-spark .`

### 10. UPDATE `docker-compose.yml`

- **IMPLEMENT**: Add `spark` service after `generator`:
  ```yaml
  spark:
    build:
      context: .
      dockerfile: docker/spark/Dockerfile
    container_name: top-spark
    hostname: spark
    ports:
      - "4040:4040"
    environment:
      KAFKA_BOOTSTRAP_SERVERS: kafka:9092
      KAFKA_TOPIC: ${KAFKA_TOPIC:-web_events}
      SPARK_DRIVER_MEMORY: ${SPARK_DRIVER_MEMORY:-2g}
      SPARK_EXECUTOR_MEMORY: ${SPARK_EXECUTOR_MEMORY:-2g}
      SPARK_CHECKPOINT_DIR: /opt/checkpoints/web_events
      ICEBERG_WAREHOUSE_DIR: /opt/warehouse
      ICEBERG_CATALOG: lakehouse
      ICEBERG_TABLE: web_events
      WATERMARK_DURATION: ${WATERMARK_DURATION:-2 minutes}
      SERVER_REGISTRY_PATH: /app/data/servers.csv
    depends_on:
      kafka:
        condition: service_healthy
    restart: unless-stopped
    networks:
      - top-net
    volumes:
      - spark_warehouse:/opt/warehouse
      - spark_checkpoints:/opt/checkpoints
  ```
  Add to top-level `volumes:`:
  ```yaml
  spark_warehouse:
  spark_checkpoints:
  ```
- **PATTERN**: `docker-compose.yml:76-94` — `generator` service (build context,
  depends_on kafka healthy, restart unless-stopped, top-net network).
- **GOTCHA**: No healthcheck for Spark — the Spark UI is not guaranteed to be up
  during startup. The `depends_on: kafka: service_healthy` ensures Kafka is ready
  before Spark starts. Future slices can add a healthcheck if needed.
- **VALIDATE**: `docker compose config --quiet`

### 11. UPDATE `pyproject.toml`

- **IMPLEMENT**: Add `pyspark>=3.5,<3.6` to the dev dependency group.
- **PATTERN**: `pyproject.toml:9-15` — existing dev deps list.
- **GOTCHA**: The version constraint `>=3.5,<3.6` ensures we get a 3.5.x release
  matching the Docker image. Do not allow 4.x.
- **VALIDATE**: `uv sync --dev && uv run python -c "import pyspark; print(pyspark.__version__)"`

### 12. UPDATE `DECISIONS.md`

- **IMPLEMENT**: Add D-018, D-019, and D-020 entries following the existing ADR format.
- **PATTERN**: `DECISIONS.md:536-580` — D-011 is a good template (infrastructure
  decision with clear alternatives).
- **VALIDATE**: Visual inspection — entries follow format, index table updated.

### 13. RUN full validation suite

- **VALIDATE**:
  ```bash
  uv run ruff check src tests
  uv run mypy src
  uv run pytest tests/unit -q
  docker compose up -d --build
  # Wait for stack to stabilize
  sleep 60
  docker compose ps
  docker compose logs spark --tail 30
  # Verify Iceberg table has data
  docker compose exec spark python -c "
  from pyspark.sql import SparkSession
  spark = SparkSession.builder \
      .config('spark.sql.catalog.lakehouse', 'org.apache.iceberg.spark.SparkCatalog') \
      .config('spark.sql.catalog.lakehouse.type', 'hadoop') \
      .config('spark.sql.catalog.lakehouse.warehouse', '/opt/warehouse') \
      .config('spark.sql.extensions', 'org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions') \
      .getOrCreate()
  spark.sql('SELECT count(*) as cnt FROM lakehouse.web_events').show()
  spark.sql('SELECT * FROM lakehouse.web_events.snapshots ORDER BY committed_at DESC LIMIT 3').show(truncate=False)
  "
  ```

---

## TESTING STRATEGY

### Unit Tests
- **`test_transformations.py`**: 10+ tests covering `load_server_registry`,
  `parse_event_json`, `enrich_event` with happy paths and edge cases (malformed JSON,
  missing fields, wrong types, unknown server_id, empty registry).
- **Existing tests**: `test_config.py`, `test_schemas.py`, `test_producer.py` must
  continue to pass unchanged.
- **Target**: `uv run pytest tests/unit -q` under 5 seconds.

### Integration Test — Kafka → Spark → Iceberg (NEW in B3)

B3 introduces the highest-risk classpath in the stack. An automated integration test
catches JAR skew, catalog config bugs, and schema-mapping issues before the Docker
image is ever built.

**Fixtures** (in `tests/integration/conftest.py`, session-scoped):

1. **`kafka_container`** — refactored from the existing `test_generator_kafka.py`
   fixture into `conftest.py` so both test files share the same Kafka container.
2. **`spark_session`** — session-scoped SparkSession configured with:
   - `spark.jars.packages` = `org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.10.1,org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.8`
   - Iceberg Hadoop catalog pointing at a `tmp_path_factory`-created temp directory.
   - `spark.master` = `local[*]`
   - `spark.driver.memory` = `1g` (lighter than production; host test only)
   This fixture amortizes the ~15 s SparkSession boot across all integration tests
   (D-008).

**Test file** (`tests/integration/test_spark_iceberg.py`):

- `test_spark_reads_from_kafka` — produce 10 events to testcontainers Kafka via
  `confluent_kafka.Producer`, read them back via `spark.read.format("kafka")` (batch
  mode, not streaming — simpler for test), parse with `from_json` + the StructType
  from `schemas_spark.py`, assert 10 rows, assert all field names present.
- `test_broadcast_enrich_drops_unknown_server` — create a DataFrame with one known
  and one unknown `server_id`, broadcast-join against registry, assert only the known
  row survives.
- `test_iceberg_append_and_read_back` — produce events, read from Kafka, enrich,
  call `append_to_iceberg(...)` to the temp warehouse, read back via
  `spark.sql("SELECT * FROM ...")`, assert row count matches, assert enrichment
  columns (`region`, `datacenter`, `service`) are populated, assert `event_ts` is
  TimestampType.
- `test_iceberg_table_is_partitioned_by_hour` — after writing, inspect partitions
  via `spark.sql("SELECT * FROM {table}.partitions")`, assert partition spec is
  `hours(event_ts)`.

**Note on batch vs streaming for test**: The integration test uses `spark.read`
(batch) to read from Kafka, not `spark.readStream` (streaming). This is intentional —
batch mode is deterministic and does not require checkpoints or `awaitTermination`.
The streaming mechanics are validated by the Docker smoke test. The integration test
focuses on: (1) classpath works, (2) schema parsing works, (3) Iceberg writes work.

**Target**: `uv run pytest tests/integration -q` under 5 minutes.

### Manual Smoke Test
1. `docker compose down -v` (clean slate)
2. `docker compose up -d --build`
3. Wait 60 seconds
4. `docker compose ps` — all services healthy/running
5. `docker compose logs spark --tail 20` — structured log lines with
   `event=batch_complete`
6. Iceberg query (see task 10 validation) — `count(*) > 0`
7. `docker compose logs spark 2>&1 | grep "event=batch_complete"` — verify per-batch
   metrics appear

### Edge Cases
- **Generator not running**: Spark starts, waits for events, no errors. First batch
  is empty.
- **Kafka not yet ready**: `depends_on: service_healthy` prevents this. If Kafka dies
  mid-stream, Spark logs errors and retries.
- **Malformed event**: If an event with bad JSON reaches Kafka, `from_json` returns
  null struct, filtered out by `event_id IS NOT NULL`.
- **Unknown server_id**: Inner join drops the event. Count appears in batch log.
- **Spark restart**: Checkpoint resumes from last committed offset. Iceberg append is
  safe to replay (at-least-once, D-001).

---

## VALIDATION COMMANDS

Execute every command. Zero failures, zero warnings on the linters.

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
docker compose down -v
docker compose up -d --build
sleep 60
docker compose ps
docker compose logs spark --tail 30
```

### Level 5: Slice-Specific Manual Validation
```bash
# Verify Iceberg table exists and has data
docker compose exec spark python -c "
from pyspark.sql import SparkSession
spark = SparkSession.builder \
    .config('spark.sql.catalog.lakehouse', 'org.apache.iceberg.spark.SparkCatalog') \
    .config('spark.sql.catalog.lakehouse.type', 'hadoop') \
    .config('spark.sql.catalog.lakehouse.warehouse', '/opt/warehouse') \
    .config('spark.sql.extensions', 'org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions') \
    .getOrCreate()
spark.sql('SELECT count(*) as cnt FROM lakehouse.web_events').show()
spark.sql('SELECT * FROM lakehouse.web_events ORDER BY event_ts DESC LIMIT 5').show(truncate=False)
spark.sql('SELECT * FROM lakehouse.web_events.snapshots ORDER BY committed_at DESC LIMIT 5').show(truncate=False)
"

# Verify enrichment columns are populated
docker compose exec spark python -c "
from pyspark.sql import SparkSession
spark = SparkSession.builder \
    .config('spark.sql.catalog.lakehouse', 'org.apache.iceberg.spark.SparkCatalog') \
    .config('spark.sql.catalog.lakehouse.type', 'hadoop') \
    .config('spark.sql.catalog.lakehouse.warehouse', '/opt/warehouse') \
    .config('spark.sql.extensions', 'org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions') \
    .getOrCreate()
spark.sql('SELECT DISTINCT region, datacenter, service FROM lakehouse.web_events ORDER BY region').show()
"

# Verify Spark UI is reachable
curl -fsS http://localhost:4040 > /dev/null && echo 'Spark UI OK' || echo 'Spark UI FAIL'

# Verify structured batch logs
docker compose logs spark 2>&1 | grep "event=batch_complete" | tail -5
```

---

## ACCEPTANCE CRITERIA

- [ ] `docker compose up -d --build` brings the full stack up including Spark
- [ ] Spark container starts, connects to Kafka, and begins processing events
- [ ] `lakehouse.web_events` is created with correct schema and hourly partitioning
- [ ] Events appear in the Iceberg table within 90 seconds
- [ ] Enrichment columns (`region`, `datacenter`, `service`, `ingest_ts`) are populated
- [ ] Structured per-batch log lines appear in `docker compose logs spark`
- [ ] Spark UI is reachable at `http://localhost:4040`
- [ ] All validation commands pass with zero errors and zero linter warnings
- [ ] Unit tests cover every new pure function in `transformations.py`
- [ ] Integration test validates Kafka→Spark→Iceberg path (classpath, schema, write)
- [ ] Existing tests pass unchanged (with fixtures refactored into conftest.py)
- [ ] Code follows the pure-vs-Spark-aware split (no pyspark in `src/common/`)
- [ ] `DECISIONS.md` updated with D-018, D-019, and D-020
- [ ] No regressions: generator still produces events, Kafka still healthy
- [ ] No new floating-version dependencies

---

## COMPLETION CHECKLIST

- [ ] All tasks completed in order (1–13)
- [ ] Each task validation passed before moving to the next
- [ ] Full validation suite green (Levels 1–5)
- [ ] Manual smoke test confirmed via USER VALIDATION GUIDE
- [ ] `DECISIONS.md` updated with D-018, D-019, and D-020
- [ ] Slice plan annotated as complete

---

## USER VALIDATION GUIDE

After `docker compose up -d --build` and a ~60 s warm-up, use the following to
explore the running stack interactively.

### 1. Spark UI — http://localhost:4040

Open in a browser. Key things to look at:

- **Streaming tab** → shows the active streaming query. Confirm:
  - "Input Rate" is non-zero (~10 rows/sec, matching the generator rate).
  - "Process Rate" is keeping up (no growing backlog).
  - "Batch Duration" is in the low seconds (not minutes).
- **SQL tab** → shows executed SQL plans. Look for the `from_json` parse and the
  broadcast join in the query plan.
- **Jobs tab** → each micro-batch appears as a job. All should show green (completed).
  Red (failed) jobs indicate a sink error — check `docker compose logs spark`.

### 2. Interactive Spark Shell (PySpark)

Launch a PySpark shell inside the running Spark container with the Iceberg catalog
pre-configured. We run it from `/tmp` because the PySpark REPL enables Hive support
by default, and its embedded Derby metastore tries to create `metastore_db/` in the
current working directory — `/app` is root-owned and not writable by the `spark`
user (uid 185), which would fail the first `spark.sql(...)` call. `/tmp` is
writable and its Derby state is ephemeral (the Iceberg `lakehouse` catalog is
independent of the session's Derby metastore, so nothing durable lives there).

```bash
docker compose exec -w /tmp spark /opt/spark/bin/pyspark \
  --conf spark.sql.catalog.lakehouse=org.apache.iceberg.spark.SparkCatalog \
  --conf spark.sql.catalog.lakehouse.type=hadoop \
  --conf spark.sql.catalog.lakehouse.warehouse=/opt/warehouse \
  --conf spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions
```

Once inside the shell (`>>>` prompt), you can run:

```python
# How many events are in the lakehouse?
spark.sql("SELECT count(*) FROM lakehouse.web_events").show()

# Sample recent events (check enrichment columns are populated)
spark.sql("""
    SELECT event_id, event_ts, server_id, region, datacenter, service, status_code
    FROM lakehouse.web_events
    ORDER BY event_ts DESC
    LIMIT 10
""").show(truncate=False)

# Check distinct enrichment values (should match data/servers.csv regions)
spark.sql("""
    SELECT DISTINCT region, datacenter, service
    FROM lakehouse.web_events
    ORDER BY region, service
""").show()

# Iceberg metadata: snapshot history (one snapshot per micro-batch)
spark.sql("""
    SELECT snapshot_id, committed_at, operation, summary
    FROM lakehouse.web_events.snapshots
    ORDER BY committed_at DESC
    LIMIT 5
""").show(truncate=False)

# Iceberg metadata: partition info
spark.sql("SELECT * FROM lakehouse.web_events.partitions").show()

# Iceberg metadata: data files (shows actual Parquet files)
spark.sql("""
    SELECT file_path, record_count, file_size_in_bytes
    FROM lakehouse.web_events.files
    LIMIT 10
""").show(truncate=False)

# Schema inspection
spark.sql("DESCRIBE EXTENDED lakehouse.web_events").show(100, truncate=False)
```

Exit with `exit()` or Ctrl+D.

### 3. Peeking at Raw Kafka Events

Spark Structured Streaming tracks offsets in its checkpoint directory and does
not commit them to Kafka, so `kafka-consumer-groups.sh` will not show the Spark
consumer. To confirm events are flowing into the topic, read a few directly:

```bash
docker compose exec kafka /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 --topic web_events \
  --from-beginning --max-messages 3
```

To confirm Spark is consuming them, use the batch logs in section 4.

### 4. Structured Batch Logs

```bash
# See per-batch metrics (event=batch_complete lines)
docker compose logs spark 2>&1 | grep "event=batch_complete"
```

Each `event=batch_complete` line should show:
- `batch_id` incrementing
- `input_rows` > 0
- `iceberg_rows` > 0
- `elapsed_sec` in the low seconds

### 5. Quick Health Checks

```bash
# All containers running?
docker compose ps

# Spark UI responding?
curl -fsS http://localhost:4040 > /dev/null && echo "Spark UI: OK"

# Kafka broker alive?
docker compose exec kafka /opt/kafka/bin/kafka-broker-api-versions.sh \
  --bootstrap-server localhost:9092 > /dev/null 2>&1 && echo "Kafka: OK"

# Events flowing into Kafka?
docker compose exec kafka /opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server localhost:9092 --describe --topic web_events
```

---

## NOTES

- **Image tag**: `apache/spark:3.5.8-scala2.12-java11-python3-r-ubuntu` includes R.
  If `3.5.8-scala2.12-java11-python3-ubuntu` (without R) exists on Docker Hub, prefer
  it for a ~200 MB smaller image. Both work identically for PySpark.

- **Kafka connector Ivy resolution**: The `spark-shell --packages` step in the
  Dockerfile downloads JARs at build time. This requires internet during `docker build`
  but not at container runtime. If the Ivy step fails (network issues), the build
  fails loudly — no silent classpath gaps.

- **`bytes_sent` type mismatch**: `schemas.py` declares `("bytes_sent", "int")` but
  PRD §5.4 says `bigint`. The StructType builder in `schemas_spark.py` overrides this
  to `LongType()`. A follow-up could update `schemas.py` to `("bytes_sent", "long")`
  for consistency, but this is cosmetic — the generator produces values that fit in
  both.

- **Drop counting inside foreachBatch**: Moving the broadcast join into
  `foreachBatch` (rather than the streaming pipeline) enables per-batch drop counting.
  This is slightly less efficient (broadcast is re-applied per batch) but the broadcast
  DataFrame is tiny (~30 rows, ~2 KB) so the cost is negligible. The benefit —
  accurate per-batch metrics — is worth it per NFR-4.2.

- **No watermark in B3**: The watermark is needed for windowed aggregations in B4. B3
  does not add it because the Iceberg append does not need event-time state. B4 will
  add `.withWatermark("event_ts", config.watermark_duration)` to the stream before
  the aggregation logic in foreachBatch.

- **`startingOffsets=earliest`**: On first start, reads all existing Kafka data. On
  restart from checkpoint, the checkpoint overrides this. Safe in both cases.

- **Postgres JDBC JAR pre-installed**: Even though B3 does not write to Postgres, the
  JDBC JAR is included in the Dockerfile now because B4 will need it and the Spark
  image is built once. Avoids a Dockerfile change in B4.
