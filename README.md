# Web Traffic Observability Pipeline

> **A personal lakehouse project built AI-natively, running entirely on a laptop.**

## Project Mission

This is a personal learning project that connects four core data engineering technologies — Kafka, Spark, Iceberg, and Postgres — into a single end-to-end streaming pipeline. A synthetic generator emits fake HTTP access-log events, a Spark job reads them, enriches them, and writes every event to an Iceberg table while simultaneously pushing rolling aggregations to Grafana. The **entire stack boots with one command** and runs on 16 GB of RAM with no cloud account required.

---

## The AI-Native Workflow

- **PRD-first development.** Every slice started from `.claude/PRD.md` — Claude Code read the requirements contract before writing a line of code, preventing scope creep and ensuring every decision traces back to a functional requirement.
- **Vertical-slice execution.** A `plan-feature` → `execute` workflow forced each build slice (foundation → generator → Spark/Iceberg → dashboard) to ship as a complete, reviewable unit with passing tests and a `DECISIONS.md` entry in the same commit.
- **Decisions as artifacts.** Claude Code maintained a running ADR log (`DECISIONS.md`) with 20 entries covering every non-obvious trade-off — JAR pinning, sink idempotency, watermark strategy — so no rationale lives only in chat history.

---

## Architecture

```
┌─────────────────┐     ┌───────────────┐     ┌──────────────────────────────────────┐
│   Generator     │────▶│  Kafka        │────▶│  Spark Structured Streaming          │
│  (Python)       │     │  (KRaft,      │     │  (local mode, 2g driver + executor)  │
│  ~10 ev/s       │     │   1 broker)   │     │                                      │
└─────────────────┘     └───────────────┘     │  parse (explicit StructType)         │
                                              │     ↓                                │
                                              │  broadcast-enrich (servers.csv)      │
                                              │     ↓                                │
                                              │  foreachBatch                        │
                                              │   ├─▶ Iceberg append (fact table)    │
                                              │   └─▶ Postgres truncate+reload ×4   │
                                              └──────────────────────────────────────┘
                                                        │                  │
                                               ┌────────┘                  └──────────┐
                                               ▼                                      ▼
                                        ┌────────────┐                        ┌─────────────┐
                                        │  Iceberg   │                        │  PostgreSQL │────▶ Grafana
                                        │  Hadoop FS │                        │  serving.*  │      dashboard
                                        └────────────┘                        └─────────────┘
```

---

## Components

### Generator (`src/generator/producer.py`)
A Python process that continuously emits synthetic HTTP access-log events at ~10 events/second. Each event mimics a real web server log line: a timestamp, a server ID drawn from `data/servers.csv`, an HTTP method, a URL path, a status code, and a response latency. Events are serialised as JSON and published to the `web_events` Kafka topic. The generator deliberately produces a small fraction of malformed events and unknown server IDs to exercise the pipeline's error-handling paths.

### Kafka Broker (`apache/kafka:4.0.2`, KRaft mode)
A single-node Kafka broker running in **KRaft mode** — no ZooKeeper required. KRaft is Kafka's built-in consensus protocol; for a single-laptop project it eliminates an entire container and halves the coordination complexity. The broker holds one topic (`web_events`) with one partition. The single partition is intentional: it keeps offset tracking trivial and removes any concern about partition ordering while still exercising the full Kafka → Spark consumer path.

### Spark Streaming Engine (`src/streaming/`)
A PySpark Structured Streaming job running in **local mode** (no cluster needed). It does three things per micro-batch:

1. **Parse** — deserialises each Kafka message using an explicit `StructType` declared in `src/common/schemas.py`. Malformed records are dropped and counted; the job never crashes on bad data.
2. **Enrich** — broadcast-joins the parsed events against the server registry (`data/servers.csv`) loaded once at startup. Unknown server IDs are dropped and counted. The broadcast join is the right tool here: the registry is ~20–50 rows and never changes during a run, so replicating it to every executor is free.
3. **Write** — a single `foreachBatch` callback writes to both sinks. The enriched DataFrame is computed once and reused: appended row-by-row to the Iceberg fact table, and aggregated into four 1-minute windows that truncate-and-reload four Postgres tables.

The job uses a **2-minute event-time watermark**: events that arrive more than 2 minutes late are dropped, which keeps the aggregation state bounded in memory.

### Iceberg Table (lakehouse)
Apache Iceberg is the storage layer for the raw enriched fact table (`lakehouse.web_events`). Each micro-batch appends new rows as an **atomic Iceberg snapshot** — if the write fails halfway, the snapshot is not committed and the checkpoint does not advance, so replaying the batch is safe. The table is **partitioned by hour** (`hours(event_ts)`), which means queries filtered by time range skip entire partitions without a full scan. The catalog is the Iceberg **Hadoop catalog**, which stores all metadata as plain files on the local filesystem — no external metastore service needed.

---

## Tech Stack

| Layer        | Technology                                   | Version |
|--------------|----------------------------------------------|---------|
| Ingestion    | Apache Kafka (KRaft, single broker)          | 4.0.2   |
| Processing   | PySpark Structured Streaming                 | 3.5.8   |
| Lakehouse    | Apache Iceberg (Hadoop catalog, local FS)    | 1.10.1  |
| Serving DB   | PostgreSQL                                   | 16      |
| Dashboard    | Grafana OSS                                  | latest  |
| Kafka JAR    | spark-sql-kafka-0-10_2.12                    | 3.5.8   |
| JDBC driver  | org.postgresql:postgresql                    | 42.7.10 |

---

## Key Design Decisions

**Why PySpark, not Scala?** Iteration speed. Pure transformation functions live in `src/common/` with no PySpark import — the unit suite runs sub-second without booting a SparkSession. Scala would add a compile loop with no throughput benefit at 10 ev/s (D-004).

**Why Iceberg, not Delta or raw Parquet?** ACID isolation for the streaming append, hidden partitioning (`hours(event_ts)`) without rewriting queries, and schema evolution without touching existing files. The Hadoop catalog is the simplest catalog that works fully offline (D-002, D-006).

**Why truncate-and-reload for Postgres, not upsert?** The four serving tables always hold the last 60 one-minute windows. Truncating and reloading them in a single transaction on every micro-batch is simpler than tracking which windows changed, and replay is idempotent by construction (D-003).

---

## Quick Start

```bash
docker compose up -d
```

Stack health: `docker compose ps` — all five services (`kafka`, `postgres`, `grafana`, `spark`, `generator`) should show `running`.

Grafana dashboard: `http://localhost:3000` (admin / admin)
