# PRD — Traffic Observability Pipeline

> Status: draft v1 — generated from `/plan` session, plan file at
> `~/.claude/plans/cuddly-petting-goblet.md`. All exact JAR patch versions in §8 are
> placeholders pending Maven Central verification at scaffolding time.

---

## 1. Executive Summary

The Traffic Observability Pipeline is a self-contained streaming demonstration that
ingests synthetic HTTP access-log events from a fleet of web servers, enriches them
against a static server registry, lands them in an Apache Iceberg lakehouse for
historical analysis, and surfaces near-real-time operational aggregates in a Grafana
dashboard backed by PostgreSQL. Everything runs on a single developer laptop via
`docker compose up -d` with no manual setup steps.

The consumer of the dashboard output is a hypothetical site-reliability engineer who
wants to see request rate, error rate, latency percentiles, and hot endpoints across
their multi-region web fleet, refreshed every minute. The consumer of the lakehouse
output is a hypothetical analyst who wants append-only historical data for ad-hoc
queries.

**MVP goal:** A laptop-only stack that, after one `docker compose up -d`, produces
a live Grafana dashboard fed by enriched HTTP traffic flowing Kafka → Spark → Iceberg
+ Postgres, with no manual wiring required.

**Single most important constraint:** Must run end-to-end on a 16 GB laptop alongside
an IDE and a browser. Memory budget — not throughput, not feature breadth — is the
binding constraint.

---

## 2. Mission & Principles

**Mission:** Build the smallest credible streaming pipeline that exercises the full
shape of a real lakehouse stack — Kafka source, Structured Streaming with broadcast
enrichment, Iceberg fact table, JDBC serving sink, provisioned dashboard — without
any cloud dependencies and without any manual setup.

**Principles:**

1. **No manual setup.** If a step is not in `docker compose up -d`, it does not
   exist. Init scripts, JAR copies, and provisioning files are all baked into the
   compose stack.
2. **Explicit schemas, never inferred.** Every Kafka payload schema is declared as a
   `StructType`. Schema drift fails loud.
3. **Idempotent sinks.** Iceberg appends are checkpointed; Postgres serving tables
   are truncate-and-reload. Either sink can be replayed from a Spark checkpoint
   without corrupting downstream state.
4. **Pure functions for everything that does not need Spark.** Parsing, enrichment,
   and aggregation logic live in `src/common/transformations.py` with zero `pyspark`
   imports, so the unit suite stays sub-second.
5. **Decisions are artifacts.** Every non-obvious trade-off lands in `DECISIONS.md`
   in the same commit that introduces it. The PRD references those entries by name.
6. **Pin every JAR.** Floating versions in a Spark + Iceberg stack are the #1 cause
   of "works on my machine" failures.

---

## 3. Scenario & Domain

### Scenario

A fictional company operates a multi-region web fleet of ~20–50 servers spread
across a few regions (`us-east`, `us-west`, `eu-central`) and a few services (`web`,
`api`, `static`). Each server emits HTTP access logs as it serves requests. An SRE
team wants live operational visibility (request rate, error rate, latency, hot
paths) plus an append-only historical store for ad-hoc analysis.

### Why this scenario

HTTP access logs are the most universally-understood streaming dataset in software:
every reader knows what a 5xx is, what p99 latency means, and why grouping by region
matters. The scenario is rich enough to demonstrate broadcast enrichment, four
distinct aggregations, and a meaningful dashboard, but constrained enough that the
schema fits on one page and the generator is trivially replayable.

### Domain summary

An HTTP access log entry records a single request: when it happened, which server
handled it, what method/path was requested, what status code came back, how big the
response was, and how long it took. The server registry maps each `server_id` to
operational metadata (region, datacenter, service, environment) that the request
itself does not carry.

---

## 4. Scope & Trade-offs

| # | Trade-off                                                  | Decision                                                   | Reason                                                                                                          | DECISIONS.md entry        |
|---|------------------------------------------------------------|------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------|---------------------------|
| 1 | One Spark application vs split jobs                        | One application, dual sinks via `foreachBatch`             | Fewer moving parts on a laptop. Both sinks share the same enriched DataFrame, so splitting would just duplicate work. | to be added (`D-001`)     |
| 2 | Iceberg partitioning                                       | `PARTITIONED BY (hours(event_ts))`                         | At ~10 ev/s a daily partition would be a single partition for the whole demo run. Hourly partitions exercise hidden partitioning meaningfully. | to be added (`D-002`)     |
| 3 | Postgres write strategy                                    | Truncate-and-reload (last 60 1-minute windows per batch)   | Idempotent by construction — replay-safe with no MERGE complexity. Acceptable because per-batch volume is tiny. | to be added (`D-003`)     |
| 4 | PySpark vs Scala                                           | PySpark                                                    | Same data plane (JVM Spark), Python skin avoids a Scala build chain on the laptop and matches the test stack.   | to be added (`D-004`)     |
| 5 | Broadcast vs stream-stream join for enrichment             | Broadcast (registry is static, ~50 rows)                   | Stream-stream is overkill and stateful for a 50-row reference set.                                              | to be added (`D-005`)     |
| 6 | Iceberg catalog                                            | Hadoop catalog on local FS                                 | No Hive Metastore container, no REST catalog container. Sufficient for single-writer dev.                       | to be added (`D-006`)     |
| 7 | Kafka deployment                                           | KRaft single-node, single partition                        | No ZooKeeper, no replication, smallest memory footprint that still validates the source path.                   | to be added (`D-007`)     |
| 8 | Test scope                                                 | Unit (pure fns) + integration via testcontainers           | Pure-function tests cover transformations; testcontainers covers JDBC + Iceberg classpath risk. SparkSession boot is amortized into a single fixture. | to be added (`D-008`)     |
| 9 | Watermark policy                                           | 2-minute event-time watermark, drop later, count metric    | Generator emits ~30s of jitter — well inside 2 min — so the watermark is exercised but never breached normally. | to be added (`D-009`)     |
| 10 | Reading the dashboard from Postgres (not Iceberg)         | Postgres is the dashboard source of truth                  | Iceberg snapshot visibility lags one micro-batch and Grafana has no Iceberg-native datasource on the laptop.    | to be added (`D-010`)     |

---

## 5. Data Model

### 5.1 Event schema (Kafka payload, JSON)

| Field         | Type             | Description                                     | Example                                      |
|---------------|------------------|-------------------------------------------------|----------------------------------------------|
| `event_id`    | string (UUID v4) | Globally unique per request                     | `7c3a9f0e-1d22-4a51-bf0a-8e5d9c1a4e21`       |
| `event_ts`    | timestamp (UTC)  | When the request was served (ISO-8601 string)   | `2026-04-08T14:23:51.482Z`                   |
| `server_id`   | string           | FK into the server registry                     | `web-use1-07`                                |
| `method`      | string           | HTTP method                                     | `GET`                                        |
| `path`        | string           | Normalized request path template                | `/api/users/:id`                             |
| `status_code` | int              | HTTP status code                                | `200`                                        |
| `bytes_sent`  | long             | Response payload size in bytes                  | `4821`                                       |
| `duration_ms` | int              | Server-side handling time                       | `47`                                         |
| `remote_ip`   | string           | Client IP (synthetic, IPv4)                     | `192.0.2.137`                                |
| `user_agent`  | string           | One of a small enum                             | `curl/8.4.0`                                 |

### 5.2 Reference data — server registry

Static CSV at `data/servers.csv`. ~20–50 rows. Loaded once at job startup,
broadcast-joined against the streaming DataFrame.

| Field         | Type   | Description                           | Example      |
|---------------|--------|---------------------------------------|--------------|
| `server_id`   | string | Primary key                           | `web-use1-07`|
| `region`      | string | Coarse geographic region              | `us-east`    |
| `datacenter`  | string | Specific facility within the region   | `us-east-1a` |
| `service`     | string | Logical service the server runs       | `web`        |
| `environment` | string | Always `prod` for the demo            | `prod`       |

**Refresh strategy:** none — the file is shipped in the repo. Changes to the file
require a Spark job restart (documented in `DECISIONS.md`).

### 5.3 Enrichment fields

| Field         | Source                      | Rule                                                      |
|---------------|-----------------------------|-----------------------------------------------------------|
| `region`      | server registry             | join on `server_id`                                       |
| `datacenter`  | server registry             | join on `server_id`                                       |
| `service`     | server registry             | join on `server_id`                                       |
| `ingest_ts`   | Spark `current_timestamp()` | added by the streaming job at write time                  |

Events whose `server_id` is not in the registry are **dropped and counted** in a
per-batch log metric (see §7 — fail-loud-but-don't-crash).

### 5.4 Lakehouse schema — `lakehouse.web_events`

Apache Iceberg table, Hadoop catalog, warehouse rooted at `/opt/warehouse` inside
the Spark container (host-mounted volume).

| Column        | Type      | Source                          |
|---------------|-----------|---------------------------------|
| `event_id`    | string    | Kafka payload                   |
| `event_ts`    | timestamp | Kafka payload                   |
| `server_id`   | string    | Kafka payload                   |
| `method`      | string    | Kafka payload                   |
| `path`        | string    | Kafka payload                   |
| `status_code` | int       | Kafka payload                   |
| `bytes_sent`  | bigint    | Kafka payload                   |
| `duration_ms` | int       | Kafka payload                   |
| `remote_ip`   | string    | Kafka payload                   |
| `user_agent`  | string    | Kafka payload                   |
| `region`      | string    | enriched (registry)             |
| `datacenter`  | string    | enriched (registry)             |
| `service`     | string    | enriched (registry)             |
| `ingest_ts`   | timestamp | enriched (Spark write time)     |

- **Partition spec:** `PARTITIONED BY (hours(event_ts))`
- **Sort order:** unsorted (deferred — see DECISIONS.md `D-002`)
- **Write mode:** append-only

### 5.5 Serving schema — Postgres `serving.*`

Four tables. All four are written with **truncate-and-reload of the last 60
1-minute windows** on every Spark micro-batch via `foreachBatch`. The owner sink for
all four is the same single Spark application.

| Table                            | Grain                              | Columns                                                                            | Refresh                                  |
|----------------------------------|------------------------------------|------------------------------------------------------------------------------------|------------------------------------------|
| `serving.requests_per_minute`    | (region, window_start)             | `region`, `window_start`, `window_end`, `request_count`                            | truncate + reload, every micro-batch     |
| `serving.error_rate_per_minute`  | (region, service, window_start)    | `region`, `service`, `window_start`, `window_end`, `total`, `errors_4xx`, `errors_5xx`, `error_rate` | truncate + reload, every micro-batch     |
| `serving.latency_per_minute`     | (service, window_start)            | `service`, `window_start`, `window_end`, `p50_ms`, `p95_ms`, `p99_ms`, `sample_count` | truncate + reload, every micro-batch     |
| `serving.top_paths_per_minute`   | (window_start, rank)               | `window_start`, `window_end`, `rank`, `path`, `request_count`                      | truncate + reload, every micro-batch     |

Each table holds at most `60 windows × cardinality` rows. Earlier windows fall off
naturally on the next reload — no retention job needed.

---

## 6. Architecture

```
┌─────────────┐    ┌────────┐    ┌──────────────────────────┐    ┌────────────┐
│  generator  │───▶│ Kafka  │───▶│  Spark Structured        │───▶│  Iceberg   │
│  (Python)   │    │ (KRaft)│    │  Streaming (local mode)  │    │ (Hadoop    │
└─────────────┘    └────────┘    │                          │    │  catalog)  │
                                 │  parse → enrich          │    └────────────┘
                                 │      ↓                   │
                                 │  ┌───┴────────────────┐  │    ┌────────────┐    ┌─────────┐
                                 │  │  fact append       │  │───▶│ PostgreSQL │───▶│ Grafana │
                                 │  │  agg ×4 (1-min)    │  │    │ (serving.*)│    │ (4 panels)│
                                 │  └────────────────────┘  │    └────────────┘    └─────────┘
                                 └──────────────────────────┘
```

| Component   | Responsibility                                                                 | Technology                                                       | Scaling assumption                              |
|-------------|--------------------------------------------------------------------------------|------------------------------------------------------------------|-------------------------------------------------|
| `generator` | Emit synthetic HTTP access log events at ~10 ev/s with ~30s jitter             | Python 3.11, `confluent-kafka` (or `kafka-python`)               | Single producer, single Kafka partition         |
| `kafka`     | Buffer events between generator and Spark                                      | Apache Kafka (KRaft mode, single broker, single partition)       | Single-node, no replication                     |
| `spark`     | Source from Kafka, parse with explicit schema, broadcast-enrich, write both sinks | Apache Spark Structured Streaming (local mode), PySpark          | Single JVM, ~2 GB driver + ~2 GB executor       |
| `iceberg`   | Append-only fact table on local FS                                             | Apache Iceberg via `iceberg-spark-runtime-3.5_2.12`              | Single writer (Spark), no concurrent maintenance|
| `postgres`  | Hold the four serving tables for Grafana                                       | PostgreSQL 16, init via mounted `sql/init.sql`                   | Single instance, ~256 MB memory                 |
| `grafana`   | Auto-provisioned dashboard with four panels                                    | Grafana OSS, Postgres datasource provisioned from YAML           | Single instance, ~256 MB memory                 |

**Sink ownership:** the `spark` Structured Streaming application owns **both** the
Iceberg sink and all four Postgres serving tables. No other process writes to either.

---

## 7. Semantics & Guarantees

### 7.1 Source semantics

- **Kafka → Spark:** at-least-once. Spark commits Kafka offsets to its checkpoint
  after a successful micro-batch. On restart, the last uncommitted batch is
  reprocessed.
- **Generator → Kafka:** at-least-once. Producer uses default `acks=1`. Duplicates
  are allowed; downstream sinks tolerate them by construction.

### 7.2 Watermark / late-data policy

- **Watermark:** event-time, 2 minutes.
- **Late events:** events arriving more than 2 minutes after the current watermark
  are dropped during windowed aggregation. The drop is logged as a per-batch metric
  (`late_events_dropped`).
- **Justification:** generator jitter is bounded at ~30 seconds, so the watermark is
  exercised on every batch but never breached in normal operation. Pulling the
  watermark in tighter would risk dropping legitimate late events; pushing it out
  inflates Spark state without benefit.

### 7.3 Idempotency per sink

| Sink                            | Mechanism                                                                                                               |
|---------------------------------|-------------------------------------------------------------------------------------------------------------------------|
| `lakehouse.web_events`          | Iceberg snapshot isolation + Spark checkpoint. Replayed batches re-write the same events as a new snapshot; reads are consistent against the latest committed snapshot. Acceptable duplication on replay (at-least-once by design). |
| `serving.requests_per_minute`   | `foreachBatch` runs `TRUNCATE` then `INSERT` of the last 60 windows in a single transaction. Replay re-truncates and re-inserts — idempotent. |
| `serving.error_rate_per_minute` | Same TRUNCATE + INSERT pattern, same transaction.                                                                       |
| `serving.latency_per_minute`    | Same TRUNCATE + INSERT pattern, same transaction.                                                                       |
| `serving.top_paths_per_minute`  | Same TRUNCATE + INSERT pattern, same transaction.                                                                       |

### 7.4 Failure recovery

| Failure                          | Behavior                                                                                                                  |
|----------------------------------|---------------------------------------------------------------------------------------------------------------------------|
| Spark restart                    | Checkpoint dir holds Kafka offsets and stream state. On restart, the last incomplete batch is reprocessed; both sinks are idempotent so this is safe. |
| Kafka rebalance                  | Single partition + single consumer means rebalances are no-ops in practice.                                               |
| Schema drift (extra field)       | Explicit `StructType` ignores unknown fields. Logged at INFO with field name and batch id.                                |
| Schema drift (missing required)  | Row fails parsing, is dropped, counted in `malformed_events_dropped` metric. Batch continues.                             |
| Malformed event (bad JSON)       | Same as above — drop + count, never crash the batch.                                                                      |
| Unknown `server_id`              | Drop + count in `unenriched_events_dropped` metric.                                                                       |
| Postgres unavailable             | `foreachBatch` raises, Spark retries the batch per its retry policy, then fails the query. Iceberg sink does **not** advance for that batch (both sinks share the same `foreachBatch`). |
| Iceberg write failure            | Same — `foreachBatch` raises, batch is retried.                                                                           |

### 7.5 Backpressure

Spark Structured Streaming pulls from Kafka at its own pace. If the generator
outpaces processing, Kafka acts as the buffer; the Spark consumer lag grows but
nothing fails. The 10 ev/s default leaves at least 1–2 orders of magnitude of
headroom on any modern laptop, so backpressure is a theoretical concern only.

---

## 8. Technology Stack

> All exact patch versions below are placeholders sourced from a research subagent's
> web search and **must be re-verified against Maven Central / official release
> pages at scaffolding time**, before they are pinned into Dockerfiles.

| Layer                  | Technology                                                       | Version (placeholder) | Why over the obvious alternative                                      |
|------------------------|------------------------------------------------------------------|-----------------------|-----------------------------------------------------------------------|
| Stream broker          | Apache Kafka (KRaft mode)                                        | bundled in image      | KRaft removes ZooKeeper, halves the container count                   |
| Stream processing      | Apache Spark Structured Streaming (PySpark, local mode)          | 3.5.x (latest patch)  | Spark 4.x Iceberg support is still maturing — 3.5 is the boring path  |
| Scala (under PySpark)  | Scala 2.12                                                       | 2.12                  | Matches the official Spark Docker image; Scala 2.13 buys nothing for a PySpark project |
| JVM                    | OpenJDK                                                          | 11                    | Java 17 works but adds zero benefit for local dev and risks Hadoop native lib edge cases |
| Hadoop                 | bundled `hadoop3` distribution                                   | 3.3.x                 | Local-FS Iceberg works on the bundled Hadoop libs without extras      |
| Lakehouse format       | Apache Iceberg                                                   | 1.10.x (latest)       | Hadoop catalog on local FS = zero infra; REST catalog deferred to future work |
| Iceberg runtime JAR    | `org.apache.iceberg:iceberg-spark-runtime-3.5_2.12`              | matches Iceberg ver   | The single JAR bundles every Iceberg dep Spark needs                  |
| Kafka connector        | `org.apache.spark:spark-sql-kafka-0-10_2.12`                     | matches Spark ver     | Official Spark sub-project; transitive `kafka-clients` and `commons-pool2` come with it |
| Serving DB             | PostgreSQL                                                       | 16                    | Free, well-known, has a Grafana datasource out of the box             |
| JDBC driver            | `org.postgresql:postgresql`                                      | 42.7.x                | Latest stable, Java 8+ compatible                                     |
| Dashboard              | Grafana OSS                                                      | latest                | Auto-provisioning via mounted YAML is well-documented                 |
| Container orchestration| Docker Compose v2                                                | latest                | Single command, no Kubernetes                                         |
| Spark base image       | `apache/spark:<ver>-scala2.12-java11-python3-ubuntu`             | matches Spark ver     | Official, includes Python 3.11 and Spark — no manual install         |
| Python                 | CPython                                                          | 3.11                  | Matches the Spark base image's bundled Python                         |
| Dep management         | `uv`                                                             | latest                | Per project convention (`CLAUDE-template.md`)                         |
| Lint / type            | `ruff`, `mypy`                                                   | latest                | Per project convention                                                |
| Test runner            | `pytest`                                                         | latest                | Per project convention                                                |
| Integration test infra | `testcontainers-python`                                          | latest                | Real Postgres container per integration suite, single SparkSession fixture |

**Hard rule:** Do not pin `kafka-clients`, `commons-pool2`, or `commons-io` versions
explicitly. Let `spark-sql-kafka-0-10` pull its own transitives. Manual overrides
cause serialization errors at runtime.

---

## 9. Functional Requirements

### Generator

| ID      | Requirement                                                                                                          |
|---------|----------------------------------------------------------------------------------------------------------------------|
| FR-G-1  | The generator MUST emit events to Kafka topic `web_events` at a sustained rate of 10 events/sec (configurable via env). |
| FR-G-2  | Each emitted event MUST conform to the schema in §5.1, serialized as UTF-8 JSON.                                     |
| FR-G-3  | The generator MUST draw `server_id` from the registry in `data/servers.csv` so every event is enrichable.            |
| FR-G-4  | The generator MUST jitter `event_ts` backwards by 0–30s relative to wall-clock to exercise the watermark.            |
| FR-G-5  | The generator MUST distribute `path` across a small fixed set of templates so top-N is meaningful.                   |
| FR-G-6  | The generator MUST distribute `status_code` so that 4xx is ~5% and 5xx is ~1% of total — error-rate panels are non-trivial. |
| FR-G-7  | The generator MUST start automatically as part of `docker compose up -d`.                                            |

### Streaming job

| ID      | Requirement                                                                                                                                                |
|---------|------------------------------------------------------------------------------------------------------------------------------------------------------------|
| FR-S-1  | The streaming job MUST read from Kafka topic `web_events` using `spark-sql-kafka-0-10`, parsing JSON with the explicit `StructType` from `src/common/schemas.py`. |
| FR-S-2  | The streaming job MUST broadcast-join the parsed stream with the server registry on `server_id`, adding `region`, `datacenter`, `service`.                  |
| FR-S-3  | The streaming job MUST drop and count any event that fails to parse, fails to enrich, or violates field constraints.                                       |
| FR-S-4  | The streaming job MUST append every enriched event to `lakehouse.web_events` (Iceberg, Hadoop catalog, partitioned by hour of `event_ts`).                  |
| FR-S-5  | The streaming job MUST compute the four aggregations defined in §5.5 over a 1-minute tumbling event-time window, with a 2-minute watermark.                 |
| FR-S-6  | The streaming job MUST truncate-and-reload the last 60 1-minute windows of each aggregation into the corresponding `serving.*` table on every micro-batch. |
| FR-S-7  | The streaming job MUST log one structured log line per micro-batch with: batch id, input row count, output row counts per sink, drop counts by reason, processing time. |
| FR-S-8  | The streaming job MUST persist its checkpoint to a host-mounted volume so restarts are safe.                                                                |
| FR-S-9  | The streaming job MUST start automatically as part of `docker compose up -d`.                                                                              |

### Lakehouse

| ID      | Requirement                                                                                              |
|---------|----------------------------------------------------------------------------------------------------------|
| FR-L-1  | `lakehouse.web_events` MUST exist after the first successful micro-batch and be queryable via the Spark CLI. |
| FR-L-2  | `lakehouse.web_events` MUST be partitioned by `hours(event_ts)`.                                         |
| FR-L-3  | The Iceberg warehouse directory MUST be mounted to a host volume so it survives `docker compose down`.   |

### Serving DB

| ID      | Requirement                                                                                              |
|---------|----------------------------------------------------------------------------------------------------------|
| FR-D-1  | `sql/init.sql` MUST create a `serving` schema and the four serving tables on Postgres container startup.|
| FR-D-2  | Each serving table MUST be populated within 90 seconds of `docker compose up -d`.                        |
| FR-D-3  | Each serving table MUST hold at most 60 windows × cardinality rows at any time.                          |

### Dashboard

| ID      | Requirement                                                                                              |
|---------|----------------------------------------------------------------------------------------------------------|
| FR-V-1  | Grafana MUST auto-provision the Postgres datasource from a mounted YAML on startup.                      |
| FR-V-2  | Grafana MUST auto-provision a single dashboard `Operations` containing four panels: requests/sec by region, error rate by region/service, latency p50/p95/p99 by service, top-N hot paths. |
| FR-V-3  | All four panels MUST show live data within 2 minutes of `docker compose up -d`.                          |
| FR-V-4  | The Grafana admin password MUST be set from `.env`.                                                      |

---

## 10. Non-Functional Requirements

### Containerization (NFR-1)

| ID        | Requirement                                                                                              |
|-----------|----------------------------------------------------------------------------------------------------------|
| NFR-1.1   | The full stack MUST come up via `docker compose up -d` with no manual setup steps after the initial `cp .env.example .env`. |
| NFR-1.2   | Every service MUST define a `healthcheck` so `docker compose ps` shows accurate status.                  |
| NFR-1.3   | Postgres MUST initialize its schema via mounted `sql/init.sql`. Grafana MUST provision via mounted YAML. |
| NFR-1.4   | The Iceberg warehouse, Spark checkpoint, and Postgres data directory MUST be on named or host-mounted volumes. |
| NFR-1.5   | `docker compose down -v` MUST be sufficient to fully reset the stack.                                    |

### Testing (NFR-2)

| ID        | Requirement                                                                                              |
|-----------|----------------------------------------------------------------------------------------------------------|
| NFR-2.1   | Unit tests MUST cover every pure function in `src/common/transformations.py`. No SparkSession allowed.   |
| NFR-2.2   | Integration tests MUST cover the JDBC sink (real Postgres via testcontainers) and the Iceberg sink (real local SparkSession + temp warehouse). |
| NFR-2.3   | The integration suite MUST share a single SparkSession fixture per pytest session to amortize boot cost. |
| NFR-2.4   | `uv run pytest tests/unit -q` MUST complete in under 5 seconds on a cold cache.                          |
| NFR-2.5   | `uv run pytest tests/integration -q` MUST complete in under 5 minutes on a warm Docker cache.            |

### Code quality & docs (NFR-3)

| ID        | Requirement                                                                                              |
|-----------|----------------------------------------------------------------------------------------------------------|
| NFR-3.1   | The pure-vs-Spark-aware split is enforced: nothing under `src/common/transformations.py` may import `pyspark`. |
| NFR-3.2   | All config values MUST be read from environment variables via `src/common/config.py`. No hardcoded broker/JDBC URLs anywhere in `src/`. |
| NFR-3.3   | Every public function MUST have type hints. `uv run mypy src` MUST pass.                                 |
| NFR-3.4   | `uv run ruff check src tests` MUST pass.                                                                 |
| NFR-3.5   | Every non-obvious decision MUST have an entry in `DECISIONS.md`.                                         |

### Observability (NFR-4)

| ID        | Requirement                                                                                              |
|-----------|----------------------------------------------------------------------------------------------------------|
| NFR-4.1   | Structured logs only (key=value or JSON). One log line per micro-batch in `foreachBatch`.                |
| NFR-4.2   | Per-batch log line MUST include: batch id, input row count, output row counts per sink, drop counts by reason, processing time. |
| NFR-4.3   | Spark UI MUST be reachable at `http://localhost:4040`.                                                   |
| NFR-4.4   | Grafana MUST be reachable at `http://localhost:3000`.                                                    |

---

## 11. Project Structure

```
traffic-observability-pipeline/
├── docker-compose.yml             # full stack
├── .env.example                   # default credentials, broker, paths
├── pyproject.toml                 # uv-managed Python deps
├── docker/
│   ├── spark/Dockerfile           # apache/spark base + Iceberg/Kafka/JDBC JARs
│   ├── generator/Dockerfile       # python:3.11-slim + producer
│   └── kafka/                     # KRaft single-node config (if needed)
├── data/
│   └── servers.csv                # static server registry
├── sql/
│   └── init.sql                   # serving.* schema
├── grafana/
│   └── provisioning/
│       ├── datasources/postgres.yml
│       └── dashboards/operations.json
├── src/
│   ├── common/                    # PURE — must not import pyspark
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── schemas.py
│   │   └── transformations.py
│   ├── generator/
│   │   └── producer.py
│   └── streaming/                 # Spark-aware
│       ├── stream_processor.py
│       ├── iceberg_sink.py
│       └── postgres_sinks.py
├── tests/
│   ├── unit/                      # no SparkSession
│   └── integration/               # testcontainers + SparkSession fixture
├── DECISIONS.md
├── CLAUDE.md                      # filled-in version of CLAUDE-template.md
└── .claude/
    └── PRD.md                     # this file
```

The pure-vs-Spark-aware split is the structural rule of this repo:
- `src/common/transformations.py` is pure Python — no `pyspark` import — and is
  unit-tested without a SparkSession.
- `src/streaming/*.py` is Spark-aware and is exercised only by integration tests.

---

## 12. Execution Plan

> This project deliberately omits hour estimates per assistant convention.
> Sequencing and dependencies are the contract; per-slice time-boxing is decided
> when each slice enters `/plan-feature`.

| Block | Slice                          | Output                                                                                              | Depends on |
|-------|--------------------------------|-----------------------------------------------------------------------------------------------------|------------|
| B1    | Foundation                     | `CLAUDE.md`, `docker-compose.yml` skeleton with placeholder services, `.env.example`, `pyproject.toml`, `DECISIONS.md` shell | —          |
| B2    | Generator + Kafka              | KRaft Kafka container, generator container, `data/servers.csv`, `src/common/schemas.py`, `src/generator/producer.py`. Validated by `kafka-console-consumer`. | B1         |
| B3    | Spark + Iceberg                | Spark container with custom JARs, `src/streaming/stream_processor.py`, `src/streaming/iceberg_sink.py`, `src/common/transformations.py` (parse + enrich). Validated by `SELECT count(*) FROM lakehouse.web_events.snapshots`. | B2         |
| B4    | Postgres serving               | Postgres container, `sql/init.sql`, `src/streaming/postgres_sinks.py`, four aggregation functions in `transformations.py`. Validated by `SELECT * FROM serving.requests_per_minute LIMIT 5`. | B3         |
| B5    | Grafana                        | Grafana container, `grafana/provisioning/datasources/postgres.yml`, `grafana/provisioning/dashboards/operations.json` with 4 panels. Validated by `curl /api/health` + visual check. | B4         |
| B6    | Test hardening                 | Full unit test coverage (interleaved with B2–B5), integration suite with testcontainers Postgres + SparkSession fixture. | B5         |

**Where slack lives:** B3 (Spark + Iceberg) is the riskiest block. JAR version
verification, Iceberg catalog quirks, and Kafka connector classpath are all in this
block. Any timeline for the project should reserve its slack here. B5 (Grafana) and
B1 (foundation) are the shortest blocks and should compress under pressure.

---

## 13. Success Criteria

- ✅ `cp .env.example .env && docker compose up -d` brings the stack up cleanly.
- ✅ `docker compose ps` shows all six services healthy within 90 seconds.
- ✅ `kafka-console-consumer` shows JSON events on `web_events` within 30 seconds.
- ✅ `SELECT count(*) FROM lakehouse.web_events` returns a non-zero value within 90 seconds.
- ✅ All four `serving.*` tables hold rows within 90 seconds.
- ✅ `http://localhost:3000` shows the `Operations` dashboard with all four panels live.
- ✅ `uv run pytest tests/unit -q` passes in under 5 seconds.
- ✅ `uv run pytest tests/integration -q` passes in under 5 minutes.
- ✅ `uv run ruff check src tests` and `uv run mypy src` both pass.
- ✅ `docker compose down -v` is sufficient to fully reset the stack.

---

## 14. Risks & Mitigations

| Risk                                                                                                                              | Likelihood | Impact | Mitigation                                                                                                                    |
|-----------------------------------------------------------------------------------------------------------------------------------|------------|--------|-------------------------------------------------------------------------------------------------------------------------------|
| **Spark / Iceberg / Hadoop / Kafka-connector JAR version skew** crashes the Spark container in a restart loop.                    | High       | High   | Pin every JAR version explicitly in `docker/spark/Dockerfile`. Re-verify versions at scaffolding time. Document in `DECISIONS.md`. Reserve slack in B3. |
| Iceberg Hadoop catalog corrupts under concurrent writes.                                                                          | Low        | High   | Single-writer assumption: only the streaming job writes. No maintenance jobs run concurrently. Documented in `DECISIONS.md`.  |
| Grafana provisioning files break silently when versions move.                                                                     | Medium     | Medium | Validate provisioning files in B5 by `curl`-ing the Grafana API after startup. Pin Grafana image version.                     |
| Spark + Kafka + Postgres + Grafana + Spark UI together exceed 16 GB on a busy laptop, triggering OOM kills.                       | Medium     | High   | Cap Spark `driver.memory=2g` and `executor.memory=2g`. Document expected RSS for each container in `DECISIONS.md`.            |
| Testcontainers boot in the integration suite is slow enough that contributors stop running it.                                    | Medium     | Medium | Single SparkSession fixture per pytest session. Single Postgres container per pytest session. Documented in `DECISIONS.md`.   |

---

## 15. Out of Scope

| Item                                                              | Why deferred                                                                                          | Production alternative                                  |
|-------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------|---------------------------------------------------------|
| ❌ Multi-broker Kafka, replication, partitions > 1                | Single-laptop memory budget. Single partition is enough to validate the source path.                   | Multi-broker Kafka with `replication-factor=3`          |
| ❌ Schema registry (Confluent / Apicurio)                         | One more container; explicit `StructType` is sufficient at this scale.                                | Confluent Schema Registry + Avro                        |
| ❌ Exactly-once via Kafka transactions                            | At-least-once + idempotent sinks gets the same observable behavior with much less complexity.         | Kafka transactional producer + Spark exactly-once sink  |
| ❌ Iceberg REST or Hive Metastore catalog                         | Hadoop catalog on local FS removes a container. REST catalog is the right answer for production.      | Tabular / Polaris / Nessie REST catalog                 |
| ❌ Iceberg maintenance jobs (snapshot expiry, compaction)         | Single writer + short demo runs make accumulation a non-issue.                                        | Scheduled `expire_snapshots` + `rewrite_data_files`     |
| ❌ Dead-letter topic for malformed events                         | Per-batch drop count metric is sufficient at this scale.                                              | DLQ Kafka topic + replay job                            |
| ❌ MERGE-based Postgres serving sink                              | Truncate-and-reload is simpler and idempotent by construction. Acceptable at 60 windows × small cardinality. | `INSERT … ON CONFLICT … DO UPDATE` per window           |
| ❌ Cardinality limits / authoritative server registry refresh     | Static CSV is sufficient for a 50-row demo.                                                           | Reference data in a relational DB with CDC              |
| ❌ Auth on Kafka, Postgres, Grafana                               | Local laptop, no network exposure.                                                                    | mTLS / SASL / OAuth across the stack                    |
| ❌ Multi-tenancy (per-customer isolation)                         | Single-tenant scenario by design.                                                                     | Per-tenant Iceberg namespaces and Postgres schemas      |
| ❌ Backfill / replay tooling                                      | Replay from earliest is sufficient on a stateless local stack.                                        | Bounded backfill jobs reading historical Iceberg data   |
| ❌ Alerting on Grafana panels                                     | Visual demo is the goal; no on-call to page.                                                          | Grafana alerting → Slack / PagerDuty                    |
| ❌ Sort orders on the Iceberg fact table                          | Deferred — see DECISIONS.md `D-002`.                                                                  | `SORTED BY (region, service, event_ts)` for query speed |
| ❌ Stress testing (>1000 ev/s)                                    | Out of scope for the laptop demo; single-laptop memory budget is the constraint, not throughput.      | Load tests via k6 or Locust against the generator      |
| ❌ Production-grade observability (Prometheus, OpenTelemetry)     | Per-batch structured logs + Spark UI are sufficient for a demo.                                       | OTel exporters → Grafana + Prometheus                   |

---

## 16. Future Work

Prioritized roadmap from current state toward a production-shaped pipeline:

1. **Dead-letter topic** for malformed and unenriched events, replacing the
   silent-drop-with-counter pattern.
2. **MERGE-based Postgres serving sink** with `INSERT ... ON CONFLICT ... DO UPDATE`
   on `(window_start, ...keys)` instead of truncate-and-reload, so the dashboard can
   tolerate larger window history without per-batch write amplification.
3. **Schema registry** (Apicurio or Confluent) + Avro on the Kafka topic, with
   explicit schema evolution rules.
4. **Exactly-once via Kafka transactions** end-to-end.
5. **REST catalog** for Iceberg (Tabular / Polaris / Nessie) replacing the Hadoop
   catalog. Enables concurrent writers and metadata maintenance jobs.
6. **Iceberg maintenance** — scheduled `expire_snapshots`, `rewrite_data_files`,
   `rewrite_manifests`.
7. **Multi-tenancy** — per-tenant Iceberg namespaces and Postgres schemas.
8. **Production-grade observability** — OpenTelemetry exporters from the streaming
   job, Prometheus + Grafana for infra metrics.
9. **Backfill tooling** — bounded batch jobs reading historical Iceberg data into
   the same serving tables for replay scenarios.
10. **Stress test harness** to validate behavior at 100× and 1000× the demo rate.

---

## 17. Appendix

### Related documents

| Document                                       | Purpose                                                       |
|------------------------------------------------|---------------------------------------------------------------|
| `~/.claude/plans/cuddly-petting-goblet.md`     | Foundation plan from the `/plan` session that produced this PRD |
| `.claude/CLAUDE-template.md`                   | Project-rules template (becomes `CLAUDE.md` in B1)            |
| `.claude/commands/init-project.md`             | Bring-up checklist for the stack                              |
| `.claude/commands/plan-feature.md`             | Vertical-slice planning command for B2–B6                     |
| `.claude/commands/execute.md`                  | Execution command run after each `/plan-feature`              |
| `DECISIONS.md` (to be created in B1)           | Running log of non-obvious trade-offs                         |
