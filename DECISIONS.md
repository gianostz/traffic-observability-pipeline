# DECISIONS.md

Running log of non-obvious trade-offs made in this project. Every entry here
corresponds to a choice that a future contributor (or future-you) might reasonably
question. If the answer is "because that is how I wrote it", the entry does not
belong here. If the answer is "because we tried the alternative and it bit us" or
"because the alternative is more expensive than it's worth at this scale", it does.

**Format:** lightweight ADR. Each entry has an ID (`D-NNN`), a title, a status,
a date, context, the decision, consequences, the alternatives considered and
rejected, and a concrete trigger for when to revisit.

**Convention:** new entries get a monotonically increasing ID. Amendments to an
existing decision are added as new entries that reference the superseded ID in
their status line, not by editing the original.

---

## Index

| ID    | Title                                                            | Status   |
|-------|------------------------------------------------------------------|----------|
| D-001 | One Spark application owns both sinks via `foreachBatch`         | Accepted |
| D-002 | Iceberg fact table partitioned by `hours(event_ts)`              | Accepted |
| D-003 | Postgres serving sinks are truncate-and-reload, not upsert       | Accepted |
| D-004 | PySpark, not Scala Spark                                         | Accepted |
| D-005 | Broadcast join for registry enrichment, not stream-stream        | Accepted |
| D-006 | Iceberg Hadoop catalog on local FS, not REST or Hive Metastore   | Accepted |
| D-007 | Kafka in KRaft mode, single broker, single partition             | Accepted |
| D-008 | Test split: unit (pure fns) + integration via testcontainers     | Accepted |
| D-009 | 2-minute event-time watermark, drop-and-count later events       | Accepted |
| D-010 | Grafana reads from Postgres, not directly from Iceberg           | Accepted |
| D-011 | Compose skeleton declares only kafka, postgres, grafana; spark and generator deferred | Accepted |
| D-012 | Grafana image is `grafana/grafana`, not `grafana/grafana-oss`    | Accepted |
| D-013 | Kafka image is `apache/kafka:4.0.2`, not Confluent or Bitnami   | Accepted |
| D-014 | `confluent-kafka` over `kafka-python` for the generator producer | Accepted |
| D-015 | `schemas.py` is pure Python; `StructType` construction deferred to `src/streaming/` | Accepted |
| D-016 | Generator reads `servers.csv` at startup, not from a config-provided list | Accepted |
| D-017 | Integration test for producer to Kafka via testcontainers          | Accepted |

---

## D-001 — One Spark application owns both sinks via `foreachBatch`

**Status:** Accepted
**Date:** 2026-04-08
**Tags:** architecture, spark, sinks

### Context

The pipeline writes to two destinations per micro-batch: the Iceberg fact table
(`lakehouse.web_events`) and four Postgres serving tables. The natural question is
whether these should live in one Spark application or two — splitting would let
each sink fail independently and be deployed independently.

### Decision

A single Spark Structured Streaming application owns both sinks. The streaming
query's `foreachBatch` callback receives the enriched DataFrame once per batch,
writes it to Iceberg, then recomputes and truncate-reloads the four aggregations
into Postgres.

### Consequences

- **Positive:** One Kafka consumer, one checkpoint, one classpath to worry about.
  The enriched DataFrame is computed exactly once and reused for both sinks. Fewer
  moving parts on a laptop where container count directly translates to memory
  pressure.
- **Negative:** A failure in the Postgres sink fails the whole batch and blocks
  Iceberg progress for that batch. The two sinks cannot scale independently.
- **Mitigation:** Both sinks are idempotent (see D-003 for Postgres, Iceberg's
  snapshot isolation for the lakehouse), so retrying the whole batch on failure is
  safe. At 10 ev/s there is nothing to scale independently.

### Alternatives considered

- **Two Spark applications sharing the Kafka topic.** Rejected: doubles container
  count, doubles checkpoint management, and would require two independent consumer
  groups reading the same topic, duplicating every parse + enrich step.
- **One Spark app for Iceberg + a separate downstream batch job reading Iceberg
  into Postgres.** Rejected: introduces a second execution schedule, a second
  failure mode, and breaks the "1-minute freshness" NFR unless the batch runs as
  frequently as the stream, at which point you have reinvented the `foreachBatch`
  approach with more parts.

### Revisit when

- The Postgres sink starts failing frequently enough to block Iceberg progress in
  a way that matters, OR
- The aggregation logic grows heavy enough that computing it inline with Iceberg
  writes impacts micro-batch latency, OR
- The project moves off a single laptop.

---

## D-002 — Iceberg fact table partitioned by `hours(event_ts)`

**Status:** Accepted
**Date:** 2026-04-08
**Tags:** iceberg, partitioning, lakehouse

### Context

`lakehouse.web_events` needs a partition spec. The generator emits ~10 events/sec
and is expected to run for tens of minutes to a few hours during a typical demo
session. Partition spec affects file count, metadata size, and how interesting
Iceberg's hidden partitioning looks in the demo.

### Decision

`PARTITIONED BY (hours(event_ts))`. No sort order — unsorted is the default and
explicit sorting is deferred.

### Consequences

- **Positive:** At 10 ev/s a demo run of 30–60 minutes produces one or two
  partitions, each with a small number of files — sane file counts. Iceberg's
  hidden partitioning is meaningfully exercised (queries filtering on `event_ts`
  get pruned). Demonstrates the feature without exploding metadata.
- **Negative:** For very short demo runs (under an hour) there is only one
  partition, which defeats the demo value. For very long runs there is no
  compaction story, so file count grows unbounded.
- **Mitigation:** Accept the lower bound as "long enough to run the demo"; accept
  the upper bound as "out of scope, compaction is in Future Work."

### Alternatives considered

- **`PARTITIONED BY (days(event_ts))`.** Rejected: on a laptop demo running for an
  hour there would only ever be one partition, defeating the purpose of showing
  partitioning at all.
- **Unpartitioned.** Rejected: wastes an opportunity to demonstrate Iceberg's
  hidden partitioning on a dataset that obviously benefits from it.
- **`PARTITIONED BY (days(event_ts), bucket(N, server_id))`.** Rejected as
  premature for the demo scale; would be appropriate in a production pipeline.

### Revisit when

- The demo runtime regularly exceeds a few hours, making a `days` partition
  meaningful again, OR
- A real workload lands on this table and the query patterns demand a different
  layout, OR
- File count grows unbounded and compaction becomes necessary.

---

## D-003 — Postgres serving sinks are truncate-and-reload, not upsert

**Status:** Accepted
**Date:** 2026-04-08
**Tags:** postgres, idempotency, sinks

### Context

Four Postgres serving tables receive rolling 1-minute-window aggregations from the
streaming job. The classic approaches are (a) `INSERT ... ON CONFLICT ... DO UPDATE`
keyed on the window, (b) `MERGE`, or (c) `TRUNCATE` + `INSERT` of the full rolling
window set. Each has different complexity and idempotency properties.

### Decision

Every micro-batch recomputes the last 60 1-minute windows from the streaming
state and does `TRUNCATE serving.<table>` followed by `INSERT` of those windows,
in a single transaction, via `foreachBatch`.

### Consequences

- **Positive:** Idempotent by construction. Replaying a batch from a Spark
  checkpoint re-truncates and re-inserts the same rows; no partial-write concerns,
  no conflict resolution logic. Retention is implicit — windows older than 60
  minutes simply do not get written, so no separate retention job is needed.
- **Negative:** Every batch writes `60 × cardinality` rows regardless of how many
  of them actually changed. At 10 ev/s and small cardinality this is trivial;
  at 1000× scale it becomes wasteful write amplification.
- **Mitigation:** The scale (10 ev/s, <1000 rows per table) makes the
  amplification irrelevant for the demo. The MERGE-based upgrade path is listed
  in PRD §16 Future Work.

### Alternatives considered

- **`INSERT ... ON CONFLICT ... DO UPDATE` on `(window_start, ...keys)`.**
  Rejected for the MVP: requires per-table conflict keys, per-table retention
  logic to remove windows older than 60 minutes, and a more subtle idempotency
  argument. Worth it in production; not worth it here.
- **Incremental append with a window column + `DELETE FROM ... WHERE window_start <
  now() - interval '60 minutes'`.** Rejected: same retention problem, and the
  `DELETE` path is slower than `TRUNCATE` on most Postgres versions for this
  access pattern.

### Revisit when

- Per-table row counts grow past low thousands and TRUNCATE + INSERT starts
  showing up as a cost in micro-batch latency, OR
- The dashboard needs more than 60 minutes of history and per-batch writes of the
  full history become wasteful.

---

## D-004 — PySpark, not Scala Spark

**Status:** Accepted
**Date:** 2026-04-08
**Tags:** spark, language, toolchain

### Context

The Spark streaming job could be written in either Scala or Python. The underlying
data plane is identical in both cases (JVM Spark). The choice affects build
tooling, testing ergonomics, and the mental context-switch cost in a repo that is
otherwise Python.

### Decision

PySpark. All streaming code lives in `src/streaming/` as Python.

### Consequences

- **Positive:** No Scala build toolchain (`sbt`, `maven`) on the laptop. Unit
  tests for pure functions are plain `pytest`. The generator, the Spark job, and
  the tests all share one language and one dep manager (`uv`).
- **Negative:** PySpark UDFs have a Python–JVM serialization cost — not relevant
  at 10 ev/s, but would be at 10k ev/s. The Scala API is slightly more ergonomic
  for window functions and typed aggregations.
- **Mitigation:** None needed at this scale. If performance becomes an issue the
  aggregation logic is small enough to be rewritten in Scala or moved to SQL.

### Alternatives considered

- **Scala Spark.** Rejected: adds a JVM build toolchain to a laptop project that
  otherwise needs only Python + Docker. The ergonomic wins do not justify the
  overhead at this scale.
- **Pure SQL via `spark.sql(...)`.** Rejected for the streaming topology itself
  (hard to express `foreachBatch` cleanly), though individual aggregations may
  end up expressed as SQL inside Python wrappers.

### Revisit when

- Per-event PySpark serialization cost becomes measurable in the Spark UI under
  the demo workload, OR
- The project grows a second Spark job that benefits from a typed API.

---

## D-005 — Broadcast join for registry enrichment, not stream-stream

**Status:** Accepted
**Date:** 2026-04-08
**Tags:** spark, joins, enrichment

### Context

Every event must be enriched with `region`, `datacenter`, `service`, and
`environment` from the server registry. The registry is a static ~20–50 row CSV
shipped in the repo. The obvious join choices are broadcast (load once, join
in-memory) or stream-stream (register the registry as a stream and join with
state).

### Decision

Load `data/servers.csv` once at job start via `spark.read.csv(...)`, wrap it in
`broadcast(...)`, and join the Kafka stream against the broadcast DataFrame.

### Consequences

- **Positive:** Zero state to manage, zero watermark complexity on the join side,
  trivial to reason about. The registry fits in a few KB so the broadcast is free.
- **Negative:** Registry updates require restarting the Spark job.
- **Mitigation:** The demo does not update the registry at runtime. A
  "hot-reload" story is not worth building for a 50-row CSV.

### Alternatives considered

- **Stream-stream join against a Kafka-backed registry topic.** Rejected:
  introduces stream state, watermark interactions, and an extra topic — all for a
  reference dataset that never changes during a demo run.
- **Per-row Postgres lookup.** Rejected: N round-trips per batch instead of one
  broadcast, and adds a hard dependency from the Spark enrichment step on the
  Postgres container being up.

### Revisit when

- The registry starts changing at runtime, OR
- The registry grows past a few thousand rows (broadcast footprint matters).

---

## D-006 — Iceberg Hadoop catalog on local FS, not REST or Hive Metastore

**Status:** Accepted
**Date:** 2026-04-08
**Tags:** iceberg, catalog, infrastructure

### Context

Iceberg supports multiple catalog implementations: Hadoop (metadata files on a
filesystem), Hive Metastore (requires a standalone HMS + backing DB), REST
(Tabular / Polaris / Nessie). Each is a trade-off between container count and
production fidelity.

### Decision

Hadoop catalog on the local filesystem. The warehouse is rooted at `/opt/warehouse`
inside the Spark container and mounted to a host volume.

### Consequences

- **Positive:** Zero additional containers. No HMS, no backing MySQL, no REST
  catalog service. Works offline. Survives `docker compose down` (but not `-v`).
- **Negative:** Single-writer assumption. Concurrent writers (e.g. a maintenance
  job alongside the streaming job) will corrupt metadata. No production-grade
  features like branching or tagging governance.
- **Mitigation:** The streaming job is the **only** writer to
  `lakehouse.web_events`. No maintenance jobs. This is documented in CLAUDE.md
  and in the PRD as a hard rule.

### Alternatives considered

- **Iceberg REST catalog (e.g. Tabular, Polaris, Nessie).** Rejected for the MVP:
  one more container, one more set of JARs, one more service to health-check —
  for a single-writer laptop demo. Listed in PRD §16 Future Work as the
  production-shaped upgrade.
- **Hive Metastore.** Rejected: requires a standalone HMS plus a backing database
  (typically MySQL or Postgres). Heaviest option. Not worth it for a laptop.

### Revisit when

- A second writer to the lakehouse becomes necessary (maintenance jobs,
  backfills, analysts writing through Spark SQL), OR
- The project is redeployed anywhere other than a single laptop.

---

## D-007 — Kafka in KRaft mode, single broker, single partition

**Status:** Accepted
**Date:** 2026-04-08
**Tags:** kafka, infrastructure

### Context

The pipeline needs a Kafka broker to buffer events between the generator and
Spark. Kafka can run in KRaft mode (no ZooKeeper) or classic mode (with
ZooKeeper), and the topic can have any number of partitions. Each choice affects
container count, startup time, and the memory footprint on the laptop.

### Decision

KRaft mode, single broker, single partition on the `web_events` topic, no
replication.

### Consequences

- **Positive:** Removes the ZooKeeper container (container count and memory
  win). Single partition means no rebalance logic to reason about, no ordering
  surprises, and the simplest possible Spark consumer story. No replication means
  no data redundancy cost.
- **Negative:** No fault tolerance — if the Kafka container crashes, events in
  flight are lost. No parallelism on the consumer side.
- **Mitigation:** Fault tolerance is out of scope for a laptop demo. At 10 ev/s
  a single consumer is 2+ orders of magnitude over-provisioned.

### Alternatives considered

- **Multi-broker Kafka with replication.** Rejected: doubles or triples container
  count and memory usage for zero demo value.
- **Classic Kafka with ZooKeeper.** Rejected: KRaft is the modern default;
  ZooKeeper is deprecated and adds a container.
- **Redpanda.** Rejected: would work, but adds a non-standard component that
  makes the demo less recognizable to readers coming from mainstream Kafka.
- **Multi-partition topic.** Rejected: no value at 10 ev/s and complicates the
  Spark consumer story.

### Revisit when

- Throughput requirements move past what a single broker comfortably handles, OR
- The demo becomes a staging environment where data loss on container crash is
  unacceptable.

---

## D-008 — Test split: unit (pure fns) + integration via testcontainers

**Status:** Accepted
**Date:** 2026-04-08
**Tags:** testing

### Context

Spark projects have a long-standing temptation to write "unit tests" that boot a
SparkSession per test. This produces a test suite that is slow, flaky, and has
the worst properties of both unit and integration tests. The alternative is a
strict split: pure-function tests with no SparkSession, plus a small integration
suite that boots a real SparkSession once and exercises the real sinks.

### Decision

- `tests/unit/`: pure functions from `src/common/transformations.py`. No
  SparkSession. No testcontainers. No I/O.
- `tests/integration/`: real SparkSession (single fixture per pytest session),
  real Postgres via testcontainers, real Iceberg write to a temp warehouse. Used
  to catch classpath and sink-semantics bugs.
- Target: `pytest tests/unit -q` finishes under 5 seconds cold; `pytest
  tests/integration -q` finishes under 5 minutes warm.

### Consequences

- **Positive:** Sub-second unit feedback loop. Integration suite is focused on
  the highest-risk parts of the stack (JAR classpath, Iceberg writes, JDBC) and
  does not waste time re-testing pure logic. The SparkSession fixture is booted
  once per pytest session, not per test.
- **Negative:** Requires discipline — any pure logic that accidentally imports
  `pyspark` breaks the "no SparkSession in unit tests" rule. Integration tests
  require Docker to be running locally.
- **Mitigation:** The pure-vs-Spark-aware split in `src/` is the structural
  guarantee. A lint check for `pyspark` imports under `src/common/` is on the
  roadmap.

### Alternatives considered

- **Unit tests only.** Rejected: the riskiest parts of a Spark stack (classpath,
  sinks) would be validated only by `docker compose up` and manual checks. Too
  easy to ship a broken sink.
- **SparkSession in every test.** Rejected: slow, flaky, and produces the worst
  properties of both test types.
- **A single end-to-end smoke test against the running compose stack instead of
  testcontainers.** Rejected: ties test lifecycle to `docker compose` state and
  makes CI harder.

### Revisit when

- The integration suite runtime creeps past 5 minutes warm, OR
- A pattern of bugs appears that is caught by neither the unit nor the
  integration suite, indicating a gap.

---

## D-009 — 2-minute event-time watermark, drop-and-count later events

**Status:** Accepted
**Date:** 2026-04-08
**Tags:** spark, streaming, watermark

### Context

The four serving aggregations use 1-minute tumbling event-time windows, which
requires a watermark. Choosing the watermark duration trades state retention cost
against tolerance for out-of-order events. The generator introduces ~30 seconds
of backward jitter on `event_ts` to exercise the watermark.

### Decision

Event-time watermark of 2 minutes. Events arriving more than 2 minutes after the
watermark are dropped during windowed aggregation. The drop is logged as a
per-batch metric (`late_events_dropped`).

### Consequences

- **Positive:** The 2-minute watermark comfortably covers the generator's 30s
  jitter, so normal operation never breaches it. State retention is bounded
  (Spark can close and release windows older than 2 minutes past the watermark).
  Late events that do occur are visible as a metric rather than silently lost.
- **Negative:** Spark holds 2 minutes of windowed state in memory per aggregation.
  At 10 ev/s this is trivial; at 10k ev/s it would matter.
- **Mitigation:** None needed at this scale.

### Alternatives considered

- **Tighter watermark (e.g. 30 seconds).** Rejected: too close to the generator's
  jitter budget; one stall in the generator would start dropping legitimate
  events.
- **Looser watermark (e.g. 10 minutes).** Rejected: bloats Spark state for no
  benefit, since the generator never produces events more than ~30s out of order.
- **No watermark.** Rejected: unbounded Spark state, not viable for a demo that
  runs longer than a few minutes.

### Revisit when

- Measured generator jitter or upstream lag starts approaching 2 minutes, OR
- A real upstream replaces the synthetic generator with different arrival
  characteristics.

---

## D-010 — Grafana reads from Postgres, not directly from Iceberg

**Status:** Accepted
**Date:** 2026-04-08
**Tags:** grafana, serving, architecture

### Context

Grafana could in principle read from Iceberg (via Trino, DuckDB, or a Spark
Thrift server) or from the Postgres serving tables. The choice affects how many
containers the laptop needs to run and how fresh the dashboard is.

### Decision

Grafana reads from PostgreSQL only. Iceberg is the historical store; Postgres is
the dashboard store. The streaming job writes both.

### Consequences

- **Positive:** No Trino, no Thrift server, no DuckDB-on-Iceberg container.
  Grafana ships with a first-class Postgres datasource that is trivially
  auto-provisioned. Dashboard freshness is bounded by the Spark micro-batch
  interval (typically a few seconds).
- **Negative:** The dashboard cannot show arbitrary ad-hoc queries against the
  full history — it is limited to whatever the streaming job pre-aggregates into
  Postgres.
- **Mitigation:** Iceberg remains queryable from the Spark shell for ad-hoc
  analysis. The dashboard is deliberately scoped to the four pre-aggregated
  panels defined in the PRD.

Also: Iceberg snapshot visibility lags one micro-batch. A dashboard reading
Iceberg directly would see stale data relative to what the streaming job has
"finished" processing. Reading Postgres avoids this entirely because the
Postgres write happens inside the same `foreachBatch` as the Iceberg write.

### Alternatives considered

- **Trino + Iceberg connector → Grafana Trino datasource.** Rejected: adds a
  significant container (Trino is not small), and makes the dashboard subject to
  Iceberg's one-batch visibility lag.
- **DuckDB reading Iceberg from disk, queried by Grafana.** Rejected: would work
  but is non-standard, and the laptop already has Postgres running for serving.
- **Skip Postgres entirely and have Grafana read Iceberg directly.** Rejected
  for the reasons above.

### Revisit when

- The dashboard needs to support ad-hoc historical queries that are not
  pre-aggregated, OR
- Postgres becomes a bottleneck in a way Iceberg-backed serving would solve.

---

## D-011 — Compose skeleton declares only kafka, postgres, grafana; spark and generator deferred

**Status:** Accepted
**Date:** 2026-04-10
**Tags:** docker-compose, infrastructure, slicing

### Context

PRD §12 calls B1 a "skeleton with placeholder services". The obvious read is
"declare all six services with TODO config". But the `spark` service needs a custom
Dockerfile with Iceberg/Kafka/JDBC JARs (owned by B3) and the `generator` needs its
own image (owned by B2). Neither can run on a stock image today.

### Decision

Declare only kafka, postgres, and grafana — the three services that can run on
stock upstream images with full healthchecks, named volumes, and env-var
substitution. Add spark in B3 and generator in B2, each in the slice that builds
the custom image.

### Consequences

- **Positive:** `docker compose up -d kafka postgres grafana` works from day 1.
  Healthchecks are live so future slices can use `depends_on ... service_healthy`.
  Slice ownership is crisp: each service is introduced by the slice that owns its
  image and code.
- **Negative:** The compose file is not "complete" in B1 — a reader seeing it for
  the first time may wonder where Spark and the generator are.
- **Mitigation:** The PRD's "skeleton with placeholder services" wording is loose
  enough to accommodate this reading, and the running skeleton is more valuable than
  a complete but broken one.

### Alternatives considered

- **Declare all six services with `image:` placeholders for spark/generator.**
  Rejected: there is no upstream image for the generator, and the official Spark
  image needs a custom layer for Iceberg+Kafka+JDBC JARs that B3 owns.
- **Declare all six with empty `build:` directives.** Rejected: `docker compose
  config` fails because the Dockerfile paths do not exist.

### Revisit when

- All five building-block slices (B1–B5) have landed and the compose file is
  complete, making this decision historical context only.

---

## D-012 — Grafana image is `grafana/grafana`, not `grafana/grafana-oss`

**Status:** Accepted
**Date:** 2026-04-10
**Tags:** grafana, docker, infrastructure

### Context

CLAUDE.md and PRD §8 both say "Grafana OSS". The `grafana/grafana-oss` Docker Hub
repository is being EOL'd starting with the 12.4.0 release; Grafana Labs now
publishes the same OSS binary under the `grafana/grafana` image name. The choice of
*Grafana OSS* (vs Grafana Enterprise / Cloud) is unchanged — only the image name is.

### Decision

Pin `grafana/grafana:12.4.2` in `docker-compose.yml`. This is the actively
maintained image that ships the same OSS binary previously found under
`grafana/grafana-oss`.

### Consequences

- **Positive:** We pin to an actively maintained image. No risk of the image name
  going stale.
- **Negative:** None — the OSS binary, the license, and the demo behavior are
  identical.

### Alternatives considered

- **Pin `grafana/grafana-oss:12.4.2`.** Rejected: the repo is being deprecated
  and will stop receiving updates. Pinning a tag in a deprecated repo at bootstrap
  invites a forced migration later.

### Revisit when

- The `grafana/grafana` image changes its licensing or binary in a way that
  matters for this demo.

---

## D-013 — Kafka image is `apache/kafka:4.0.2`, not Confluent or Bitnami

**Status:** Accepted
**Date:** 2026-04-10
**Tags:** kafka, docker, infrastructure

### Context

D-007 already locks in "KRaft mode, single broker, single partition". The remaining
choice is *which* Docker image to run. The three plausible options are the official
Apache image (`apache/kafka`), Confluent's image (`confluentinc/cp-kafka`), and
Bitnami's image (`bitnami/kafka`).

### Decision

`apache/kafka:4.0.2`. The official upstream Apache Kafka image (since KIP-975).
Kafka 4.x is KRaft-only by design (ZooKeeper removed entirely), which hard-enforces
D-007 at the image level.

### Consequences

- **Positive:** Official upstream — no third-party packaging in the dependency
  graph. KRaft-only means zero chance of accidentally misconfiguring ZooKeeper mode.
  The 4.x client protocol is wire-compatible with Spark 3.5's `spark-sql-kafka`
  connector (Kafka protocol versioning guarantees this).
- **Negative:** Kafka 4.x is newer than the Confluent/Bitnami images most tutorials
  reference, so some Stack Overflow answers may not apply directly.
- **Mitigation:** The KRaft env-var surface is documented in the official quickstart
  and is straightforward for a single-broker setup.

### Alternatives considered

- **`confluentinc/cp-kafka`.** Rejected: bundles Confluent-specific config
  conventions and a heavier base layer. Unnecessary for a single-broker laptop demo.
- **`bitnami/kafka`.** Rejected: well-maintained but a third-party packaging that
  adds a dependency on Bitnami's release cadence.

### Revisit when

- The Spark Kafka connector breaks compatibility with Kafka 4.x (unlikely given
  protocol versioning), OR
- A Confluent-specific feature (Schema Registry, etc.) becomes needed.

---

## D-014 — `confluent-kafka` over `kafka-python` for the generator producer

**Status:** Accepted
**Date:** 2026-04-10
**Tags:** generator, kafka, dependencies

### Context

The generator needs a Python Kafka client to produce events. PRD §6 lists both
`confluent-kafka` (librdkafka-based, pre-built wheels) and `kafka-python`
(pure Python) as options.

### Decision

Use `confluent-kafka`. Pinned at `==2.14.0` in the generator Docker image
(`docker/generator/requirements.txt`) and `>=2.14` as a dev dependency in
`pyproject.toml` for the integration test and mypy.

### Consequences

- **Positive:** Actively maintained (latest release April 2026). Pre-built
  manylinux wheels bundle librdkafka — no system-level C deps at install time
  on `python:3.11-slim`. Compatible with Kafka 4.x via protocol versioning.
  Significantly higher throughput than `kafka-python` (irrelevant at 10 ev/s
  but removes a future concern).
- **Negative:** The C extension makes cross-compilation harder if the project
  ever targets non-x86 architectures.

### Alternatives considered

- **`kafka-python`.** Rejected: effectively unmaintained since late 2023. Last
  PyPI release predates Kafka 3.7. Risk of silent incompatibility with Kafka
  4.x protocol changes.

### Revisit when

- `confluent-kafka` introduces a breaking change in its Producer API, OR
- The project needs to run on an architecture without pre-built wheels.

---

## D-015 — `schemas.py` is pure Python; `StructType` construction deferred to `src/streaming/`

**Status:** Accepted
**Date:** 2026-04-10
**Tags:** architecture, schemas, pure-vs-spark

### Context

`src/common/schemas.py` is listed in the PRD as holding the explicit
`StructType` for the Kafka payload. But `src/common/` must not import `pyspark`
(CLAUDE.md structural rule, NFR-3.1). A `StructType` requires
`from pyspark.sql.types import ...`.

### Decision

Define the event schema as pure Python in `src/common/schemas.py` — field names
and type labels as tuples, plus domain constants (path templates, status-code
weights, HTTP methods, user-agent pool). The `StructType` builder will live in
`src/streaming/` and will be built in B3.

### Consequences

- **Positive:** Preserves the structural rule without exception. The generator
  imports the field names but not the `StructType`. The pure schema is
  unit-testable without a SparkSession. Domain constants are shared between
  the generator and future transformation tests.
- **Negative:** The schema is "split" across two files — pure definitions in
  `src/common/schemas.py` and the Spark type mapping in `src/streaming/`.

### Alternatives considered

- **Make `schemas.py` the exception to the pyspark ban.** Rejected: one
  exception invites more; the sub-second unit test guarantee depends on no
  Spark imports under `src/common/`.
- **Move `schemas.py` to `src/streaming/`.** Rejected: the generator needs the
  field names and constants, and `src/generator/` should not import from
  `src/streaming/`.

### Revisit when

- The schema split causes confusion or duplication bugs across more than two
  consumers.

---

## D-016 — Generator reads `servers.csv` at startup, not from a config-provided list

**Status:** Accepted
**Date:** 2026-04-10
**Tags:** generator, configuration, data

### Context

The generator needs valid `server_id` values. Options are (a) read
`data/servers.csv` at startup, (b) hardcode a list in the generator, (c) accept
a comma-separated env var.

### Decision

Read `data/servers.csv` at startup. The file path is configurable via the
`SERVER_REGISTRY_PATH` environment variable (default: `data/servers.csv`).

### Consequences

- **Positive:** Single source of truth. The same file is broadcast-joined in B3.
  If the registry changes, both the generator and the enrichment join see the
  same data. No synchronization burden.
- **Negative:** The generator Docker image must include the CSV file (via
  `COPY data/ data/` in the Dockerfile). Changes to the registry require
  rebuilding the image.
- **Mitigation:** `docker compose up -d --build` rebuilds automatically.
  The registry is expected to be static during a demo run.

### Alternatives considered

- **Hardcode a list in the generator.** Rejected: creates a second source of
  truth that will drift from `data/servers.csv`.
- **Comma-separated env var.** Rejected: fragile for 30+ server IDs and does
  not carry the region/datacenter/service metadata that B3 needs for enrichment.

### Revisit when

- The registry needs to be updated without rebuilding the generator image.

---

## D-017 — Integration test for producer to Kafka via testcontainers

**Status:** Accepted
**Date:** 2026-04-10
**Tags:** testing, generator, kafka

### Context

Unit tests validate the pure event-generation functions but do not exercise the
serialization path (JSON encoding) or the actual Kafka produce/consume
round-trip. A broken serialization or a field-name typo would only surface after
a full `docker compose up -d` + manual `kafka-console-consumer` check.

### Decision

Add a testcontainers-based integration test that produces events to a real Kafka
broker, consumes them back, and asserts schema conformance (all 10 fields
present, correct types, valid UTF-8 JSON).

### Consequences

- **Positive:** Catches serialization bugs and field-name mismatches
  automatically, without requiring the full stack. Lightweight (~15–20 s,
  just a Kafka container). Complements the manual smoke test.
- **Negative:** Adds `confluent-kafka` and `testcontainers[kafka]` to the host
  dev dependencies. Requires Docker to be running for the integration test suite.
- **Mitigation:** Both dependencies are already budgeted for B3+. Docker is
  already a requirement for `docker compose up -d`.

### Alternatives considered

- **No integration test — validate only via manual kafka-console-consumer.**
  Rejected: manual validation is fragile, not repeatable, and not CI-friendly.

### Revisit when

- The integration test runtime becomes a bottleneck in the test suite, OR
- A different serialization format (Avro, Protobuf) replaces JSON and requires
  a different validation approach.
