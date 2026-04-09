# CLAUDE.md

This file gives Claude Code (claude.ai/code) the context it needs to be productive in
this repository without breaking the things that are easy to break in a
Spark/Iceberg/Kafka stack: classpath collisions, JAR version skew, broken
checkpoints, silent schema drift.

> **Status: bootstrap.** The repository is greenfield at the time of writing. This
> file documents the conventions the code WILL follow as each vertical slice lands.
> The PRD at `.claude/PRD.md` is the contract this file enforces.

---

## Project Overview

The **Traffic Observability Pipeline** is a self-contained streaming demonstration
that runs on a single developer laptop via `docker compose up -d`. A synthetic
generator emits HTTP access-log events to Kafka; a PySpark Structured Streaming job
running in local mode parses them with an explicit schema, broadcast-enriches them
against a static server registry (`data/servers.csv`), appends every enriched event
to an Apache Iceberg fact table on the local filesystem, and truncate-and-reloads
four rolling 1-minute aggregations into PostgreSQL. Grafana auto-provisions a
dashboard over those Postgres tables. The full scenario and data contract live in
`.claude/PRD.md`.

---

## Tech Stack

| Layer              | Technology                                                     | Version (pending Maven verify) | Pin lives in               |
| ------------------ | -------------------------------------------------------------- | ------------------------------ | -------------------------- |
| Stream ingestion   | Apache Kafka (KRaft mode)                                      | bundled in image               | `docker-compose.yml`       |
| Processing         | Apache Spark Structured Streaming (PySpark, local mode)        | 3.5.x (latest patch)           | `docker/spark/Dockerfile`  |
| Scala (under JVM)  | Scala 2.12                                                     | 2.12                           | `docker/spark/Dockerfile`  |
| JVM                | OpenJDK                                                        | 11                             | `docker/spark/Dockerfile`  |
| Hadoop             | bundled `hadoop3` distribution                                 | 3.3.x                          | `docker/spark/Dockerfile`  |
| Lakehouse format   | Apache Iceberg, Hadoop catalog on local FS                     | 1.10.x                         | `docker/spark/Dockerfile`  |
| Iceberg runtime    | `org.apache.iceberg:iceberg-spark-runtime-3.5_2.12`            | matches Iceberg ver            | `docker/spark/Dockerfile`  |
| Kafka connector    | `org.apache.spark:spark-sql-kafka-0-10_2.12`                   | matches Spark ver              | `docker/spark/Dockerfile`  |
| Serving DB         | PostgreSQL                                                     | 16                             | `docker-compose.yml`       |
| JDBC driver        | `org.postgresql:postgresql`                                    | 42.7.x                         | `docker/spark/Dockerfile`  |
| Dashboard          | Grafana OSS                                                    | pinned at image tag            | `docker-compose.yml`       |
| Containerization   | Docker Compose v2                                              | latest                         | n/a                        |
| Python             | CPython                                                        | 3.11                           | `pyproject.toml`           |
| Dep management     | `uv`                                                           | latest                         | `pyproject.toml`           |
| Lint / type        | `ruff`, `mypy`                                                 | latest                         | `pyproject.toml`           |
| Test runner        | `pytest`                                                       | latest                         | `pyproject.toml`           |
| Integration test   | `testcontainers-python`                                        | latest                         | `pyproject.toml`           |

**Hard rules on JAR versions:**
1. **Do not** pin `kafka-clients`, `commons-pool2`, or `commons-io` versions
   explicitly. Let `spark-sql-kafka-0-10` pull its own transitives. Manual overrides
   cause serialization errors at runtime.
2. **Do not** move Spark to 4.x. Iceberg support on Spark 4.x is still maturing;
   3.5.x is the boring, known-good path.
3. **Every version bump** requires a `DECISIONS.md` entry in the same commit.

---

## Commands

```bash
# Bring the full stack up (single command, no manual setup)
docker compose up -d

# Stack health check
docker compose ps

# Tail the streaming job
docker compose logs -f spark

# Tail the generator
docker compose logs -f generator

# Restart the streaming job (after editing src/streaming/*)
docker compose restart spark

# Run all tests
uv run pytest

# Fast feedback loop: pure-function unit tests only
uv run pytest tests/unit -q

# Slow loop: integration tests (testcontainers Postgres + local SparkSession)
uv run pytest tests/integration -q

# Lint + types
uv run ruff check src tests
uv run mypy src

# Full reset (wipe volumes: warehouse, checkpoint, Postgres data)
docker compose down -v
```

---

## Project Structure

```
traffic-observability-pipeline/
├── docker-compose.yml             # full local stack
├── .env.example                   # default config surface
├── pyproject.toml                 # uv-managed Python deps
├── docker/
│   ├── spark/Dockerfile           # apache/spark base + Iceberg/Kafka/JDBC JARs
│   ├── generator/Dockerfile       # python:3.11-slim + producer
│   └── kafka/                     # KRaft single-node config (if needed)
├── data/
│   └── servers.csv                # static server registry (broadcast-joined)
├── sql/
│   └── init.sql                   # serving.* schema, mounted into Postgres
├── grafana/
│   └── provisioning/
│       ├── datasources/postgres.yml
│       └── dashboards/operations.json
├── src/
│   ├── common/                    # PURE — MUST NOT import pyspark
│   │   ├── config.py              # env-var-driven config
│   │   ├── schemas.py              # explicit StructType for Kafka payload
│   │   └── transformations.py     # parse, enrich, aggregate — pure functions
│   ├── generator/
│   │   └── producer.py            # synthetic event emitter
│   └── streaming/                 # Spark-aware
│       ├── stream_processor.py    # entrypoint: source → enrich → sinks
│       ├── iceberg_sink.py
│       └── postgres_sinks.py      # foreachBatch for the four agg tables
├── tests/
│   ├── unit/                      # no SparkSession, no testcontainers
│   └── integration/               # testcontainers Postgres + SparkSession fixture
├── DECISIONS.md                   # non-obvious trade-offs log
├── CLAUDE.md                      # this file
└── .claude/
    ├── PRD.md                     # product requirements (source of truth)
    ├── CLAUDE-template.md         # original template this file was adapted from
    └── commands/                  # project slash commands
```

The **pure-vs-Spark-aware split** is the structural rule of this repo. It is not a
style preference; it is what keeps the unit suite sub-second and the integration
suite focused on real classpath risk.

---

## Architecture

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

- **Source semantics:** at-least-once from Kafka. Spark checkpoint holds offsets.
- **Enrichment:** broadcast join against the ~20–50 row server registry loaded once
  at job start.
- **Sink ownership:** the `spark` streaming application owns BOTH sinks. No other
  process writes to `lakehouse.web_events` or any `serving.*` table.
- **Iceberg idempotency:** snapshot isolation + checkpoint; replay is safe, at the
  cost of duplicate snapshots (at-least-once by design).
- **Postgres idempotency:** truncate + insert of the last 60 1-minute windows in
  one transaction, on every micro-batch. Replay re-truncates and re-inserts.
- **Watermark:** event-time, 2 minutes. Later events are dropped and counted in a
  per-batch metric.
- **Backpressure:** Kafka buffers; 10 ev/s leaves 1–2 orders of magnitude of
  headroom on a laptop.
- **Failure modes:** Spark restart is safe (both sinks idempotent). Malformed and
  unenriched events are dropped-with-counter, never fail the batch.

---

## Code Patterns

### Pure vs Spark-aware code

- **Pure transformation functions** live in `src/common/transformations.py` and
  **must not import** `pyspark`. They are unit-tested without a SparkSession.
- **Spark-aware code** (DataFrame ops, `foreachBatch`, sinks) lives in
  `src/streaming/` and is exercised only by integration tests.

This split is non-negotiable. A `pyspark` import under `src/common/` is a bug.

### Schemas

- The Kafka payload schema is declared **explicitly** in `src/common/schemas.py` as
  a `StructType`. Never rely on schema inference for streaming sources.
- Adding or changing a field requires: updating the schema, updating the
  transformation, updating unit tests, and logging the change in `DECISIONS.md`.

### Configuration

- All config goes through `src/common/config.py`, which reads environment variables.
- No hardcoded broker addresses, JDBC URLs, warehouse paths, or topic names anywhere
  in `src/`.
- `.env.example` is the authoritative list of the config surface.

### Logging

- Structured logging only (key=value or JSON). `print()` is banned in `src/`.
- **One log line per micro-batch** in `foreachBatch`, containing: batch id, input
  row count, output row counts per sink, drop counts by reason, processing time.

### Error handling

- Malformed events (bad JSON, missing required fields) are **dropped and counted**
  in the per-batch log metric, not failed-on.
- Unenriched events (unknown `server_id`) are **dropped and counted** in a separate
  metric, not failed-on.
- Late events past the 2-minute watermark are dropped by Spark and counted in the
  per-batch metric.
- Infrastructure failures (Postgres down, Iceberg write error) **do** fail the
  batch — Spark retries per its policy.

---

## Testing

- **Unit tests** (`tests/unit/`): pure functions only. No SparkSession, no
  testcontainers, sub-second feedback loop. Target: `pytest tests/unit -q` finishes
  in under 5 seconds cold.
- **Integration tests** (`tests/integration/`): real Postgres via testcontainers,
  real local SparkSession + temporary Iceberg warehouse. Single SparkSession fixture
  per pytest session to amortize boot cost. Target: under 5 minutes warm.
- **Do not** write Spark unit tests that boot a SparkSession per test. Push logic
  into pure functions in `src/common/transformations.py` instead.
- **Do not** mock Iceberg or JDBC in integration tests — the whole point of the
  integration suite is to catch classpath and sink-semantics bugs that mocks hide.

---

## Validation

```bash
# Lint + types
uv run ruff check src tests
uv run mypy src

# Tests
uv run pytest

# Stack health (after `docker compose up -d`)
docker compose ps
curl -fsS http://localhost:3000/api/health
docker compose exec postgres pg_isready

# Kafka topic + sample events
docker compose exec kafka kafka-topics.sh --bootstrap-server localhost:9092 --list
docker compose exec kafka kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 --topic web_events \
  --from-beginning --max-messages 3

# Iceberg table populated
docker compose exec spark python -c "
from pyspark.sql import SparkSession
spark = SparkSession.builder.getOrCreate()
spark.sql('SELECT count(*) FROM lakehouse.web_events').show()
spark.sql('SELECT * FROM lakehouse.web_events.snapshots ORDER BY committed_at DESC LIMIT 5').show()
"

# Postgres serving tables populated
docker compose exec postgres psql -U postgres -d serving -c "
  SELECT 'requests_per_minute' AS t, count(*) FROM serving.requests_per_minute
  UNION ALL SELECT 'error_rate_per_minute', count(*) FROM serving.error_rate_per_minute
  UNION ALL SELECT 'latency_per_minute', count(*) FROM serving.latency_per_minute
  UNION ALL SELECT 'top_paths_per_minute', count(*) FROM serving.top_paths_per_minute;
"
```

---

## Key Files

| File                                  | Purpose                                                          |
| ------------------------------------- | ---------------------------------------------------------------- |
| `.claude/PRD.md`                      | Product requirements — the source of truth for every FR/NFR      |
| `DECISIONS.md`                        | Running log of non-obvious trade-offs (created in foundation slice) |
| `src/common/schemas.py`               | Explicit StructType for Kafka payload                            |
| `src/common/transformations.py`       | Pure parse / enrich / aggregation functions                      |
| `src/common/config.py`                | Env-var-driven config                                            |
| `src/streaming/stream_processor.py`   | Streaming job entrypoint: source → enrich → sinks                |
| `src/streaming/iceberg_sink.py`       | Iceberg append writer                                            |
| `src/streaming/postgres_sinks.py`     | `foreachBatch` truncate-and-reload for the four serving tables  |
| `src/generator/producer.py`           | Synthetic event emitter                                          |
| `data/servers.csv`                    | Static server registry (20–50 rows)                              |
| `sql/init.sql`                        | Serving DB schema                                                |
| `docker/spark/Dockerfile`             | Spark image with pinned Iceberg/Kafka/JDBC JARs                  |
| `docker-compose.yml`                  | Full local stack                                                 |
| `grafana/provisioning/`               | Auto-provisioned datasource + dashboard                          |

---

## On-Demand Context

| Topic                          | File                                      |
| ------------------------------ | ----------------------------------------- |
| Product requirements           | `.claude/PRD.md`                          |
| Design decision log            | `DECISIONS.md`                            |
| Foundation plan                | `~/.claude/plans/cuddly-petting-goblet.md`|
| Stack bring-up checklist       | `.claude/commands/init-project.md`        |
| Vertical-slice planning        | `.claude/commands/plan-feature.md`        |
| Execution                      | `.claude/commands/execute.md`             |

---

## Working Conventions

1. **PRD-first.** Every non-trivial change starts from `.claude/PRD.md`. If the PRD
   does not justify it, either update the PRD or do not build it.
2. **Plan before code.** `/plan-feature` writes a vertical-slice plan before any
   code is written. Plans are reviewed before `/execute` runs.
3. **Decisions are artifacts.** Any non-obvious trade-off (sink choice, partition
   strategy, truncate-and-reload vs upsert, JAR bump, watermark duration, etc.)
   gets an entry in `DECISIONS.md` in the same commit that introduces it.
4. **Validation is non-negotiable.** Every plan ships with executable validation
   commands. `/execute` does not finish until they all pass.
5. **Human review on the risky bits.** Spark classpath, Iceberg catalog config,
   `foreachBatch` semantics, and `docker-compose.yml` are reviewed by hand.
6. **One writer per sink.** The Spark streaming application is the only writer to
   `lakehouse.web_events` and to every `serving.*` table. No ad-hoc `INSERT`s, no
   parallel maintenance jobs.
7. **Branch per slice.** Every vertical slice runs on its own branch off `main`.
   `/plan-feature` creates and switches to it as its first step; `/execute` refuses
   to run on `main`. One slice = one branch = one PR back to `main`, so each slice
   is a single reviewable unit and the matching `DECISIONS.md` entry sits inside it.
   - **Naming:** `slice/<id>-<kebab-summary>` where `<id>` is the PRD build-order id
     for foundation slices (`slice/B1-foundation`, `slice/B2-generator-kafka`,
     `slice/B3-spark-iceberg`, …). Post-foundation slices use a short kebab name
     (`slice/dlq-topic`, `slice/device-type-breakdown`).
   - **Enforcement is strict, not advisory.** `/plan-feature` and `/execute` STOP
     if the working tree is dirty or if the current branch is `main`.
   - **Merge style:** PR back to `main`. No direct commits to `main` after the
     foundation bootstrap.

---

## Notes

- **16 GB laptop is the binding constraint.** Cap Spark `driver.memory=2g` and
  `executor.memory=2g`. Kafka, Postgres, and Grafana eat the rest.
- **Java 11, not 17.** Fewer edge cases with Hadoop native libs on the official
  Spark image.
- **Iceberg Hadoop catalog is single-writer only.** Do not add maintenance jobs
  (`expire_snapshots`, `rewrite_data_files`) that would run concurrently with the
  streaming job — they will corrupt metadata on local FS.
- **Iceberg snapshot visibility lags one micro-batch.** Grafana reads from Postgres,
  not Iceberg, so this is invisible to the dashboard — but it would bite any code
  that tried to read the lakehouse from inside the same `foreachBatch`.
- **`docker compose down` keeps the warehouse, checkpoint, and Postgres data.**
  `docker compose down -v` wipes them. Prefer the former during development.
- **Version pins in this file are pending Maven Central verification** at the time
  the foundation slice lands. Re-verify before pinning into `docker/spark/Dockerfile`.
