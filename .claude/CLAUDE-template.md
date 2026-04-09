# CLAUDE.md Template — Data / Streaming Project

A flexible template for creating project-level rules for a Spark / lakehouse / streaming
codebase. Adapt sections based on the specific project; remove what does not apply.

---

# CLAUDE.md

This file gives Claude Code (claude.ai/code) the context it needs to be productive in
this repository without breaking the things that are easy to break in a Spark/Iceberg/
Kafka stack: classpath collisions, JAR version skew, broken checkpoints, silent schema
drift.

## Project Overview

{One paragraph: what this pipeline does, what it ingests, where it lands data, who
consumes it.}

---

## Tech Stack

| Layer              | Technology                                              |
| ------------------ | ------------------------------------------------------- |
| Stream ingestion   | {e.g. Apache Kafka (KRaft)}                             |
| Processing         | {e.g. Apache Spark Structured Streaming, PySpark}       |
| Lakehouse storage  | {e.g. Apache Iceberg, Hadoop catalog}                   |
| Serving database   | {e.g. PostgreSQL via JDBC sink}                         |
| Observability      | {e.g. Grafana + Spark UI}                               |
| Containerization   | {e.g. Docker Compose}                                   |
| Testing            | {e.g. pytest, testcontainers}                           |

Pin every JAR / library version explicitly. Drift here is the #1 cause of "works on my
machine" failures in Spark projects.

---

## Commands

```bash
# Bring the full stack up
docker compose up -d

# Run the data generator
docker compose logs -f generator

# Submit / restart the streaming job
docker compose restart spark

# Run all tests (unit + integration)
uv run pytest

# Fast feedback loop: unit tests only
uv run pytest tests/unit -q

# Slow loop: integration tests (boot Spark + Iceberg via testcontainers)
uv run pytest tests/integration -q
```

---

## Project Structure

```
{root}/
├── docker-compose.yml
├── docker/                    # Service Dockerfiles
├── data/                      # Static reference data
├── sql/                       # Schema init scripts for the serving DB
├── grafana/provisioning/      # Auto-provisioned dashboards + datasources
├── src/
│   ├── common/                # schemas, transformations, config (PURE functions)
│   ├── generator/             # synthetic event producer
│   └── streaming/             # Spark Structured Streaming job
└── tests/
    ├── unit/                  # Pure-function tests, no Spark session
    └── integration/           # testcontainers-based Spark + sink tests
```

---

## Architecture

{Describe the data flow end-to-end. For a streaming pipeline, always cover:}

- **Source semantics**: at-least-once vs exactly-once, watermarks, late-data policy
- **Enrichment**: where reference data lives, broadcast vs stream-stream join
- **Sinks**: which sink owns which tables, idempotency strategy, checkpoint location
- **Failure modes**: what happens on Kafka backpressure, on Spark restart, on schema drift

---

## Code Patterns

### Pure vs Spark-aware code

- **Pure transformation functions** live in `src/common/transformations.py` and **must
  not import** `pyspark`. They are unit-tested without a Spark session.
- **Spark-aware code** (DataFrame ops, `foreachBatch`, sinks) lives in `src/streaming/`
  and is exercised by integration tests.

This split is non-negotiable: it is what keeps the unit test suite fast and the
integration suite focused on the things that actually need a Spark session.

### Schemas

- All Kafka payload schemas are declared **explicitly** in `src/common/schemas.py` as
  `StructType`. Never rely on schema inference for streaming sources.
- Adding or changing a field requires: updating the schema, updating the transformation,
  updating the unit tests, and logging the change in `DECISIONS.md`.

### Configuration

- All config goes through `src/common/config.py`, which reads environment variables.
- No hardcoded broker addresses, paths, or DB URLs anywhere in `src/`.

### Logging

- Structured logging only (key=value or JSON). One log line per batch in `foreachBatch`
  with: batch id, input row count, output row count per sink, processing time.

### Error handling

- Malformed events are logged and dropped, not failed-on. Drop count is exposed as a
  log metric per batch.

---

## Testing

- **Unit tests**: pure functions in `src/common/transformations.py`. Sub-second
  feedback loop, run on every save.
- **Integration tests**: end-to-end tests via testcontainers, focused on the highest-
  risk dependencies (typically Iceberg and JDBC sinks).
- Do not write Spark unit tests that boot a `SparkSession` per test. Push logic into
  pure functions instead.

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
docker compose exec kafka kafka-topics.sh --bootstrap-server localhost:9092 --list
```

---

## Key Files

| File                                  | Purpose                                                  |
| ------------------------------------- | -------------------------------------------------------- |
| `src/common/schemas.py`               | Explicit StructType for event payloads                   |
| `src/common/transformations.py`       | Pure enrichment functions                                |
| `src/streaming/stream_processor.py`   | Streaming job: source → enrich → sinks                   |
| `src/generator/producer.py`           | Synthetic event producer                                 |
| `sql/init.sql`                        | Serving DB schema                                        |
| `docker-compose.yml`                  | Full local stack                                         |
| `DECISIONS.md`                        | Running log of non-obvious trade-offs                    |
| `.claude/PRD.md`                      | Product requirements                                     |

---

## On-Demand Context

| Topic                          | File                                      |
| ------------------------------ | ----------------------------------------- |
| Product requirements           | `.claude/PRD.md`                          |
| Design decision log            | `DECISIONS.md`                            |
| Active implementation plans    | `.agents/plans/`                          |

---

## Working Conventions

1. **PRD-first.** Every non-trivial change starts from `.claude/PRD.md`. If the PRD
   does not justify it, either update the PRD or do not build it.
2. **Plan before code.** `/plan-feature` writes a vertical-slice plan to
   `.agents/plans/`. Plans are reviewed before `/execute` runs.
3. **Decisions are artifacts.** Any non-obvious trade-off (sink choice, partition
   strategy, truncate-and-reload vs upsert, etc.) gets an entry in `DECISIONS.md` in
   the same commit that introduces it.
4. **Validation is non-negotiable.** Every plan ships with executable validation
   commands. `/execute` does not finish until they all pass.
5. **Human review on the risky bits.** Spark classpath, Iceberg catalog config, and
   `foreachBatch` semantics are reviewed by hand, not delegated wholesale to the agent.

---

## Notes

- {Any project-specific gotchas — known JAR version constraints, OS-specific issues, etc.}
