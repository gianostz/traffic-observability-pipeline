# Slice: B1 Foundation

The following plan should be complete, but it is important to validate documentation
and codebase patterns before implementing.

Pay special attention to: image tags pinned in `docker-compose.yml`, the env-var
contract in `.env.example`, and the pure-vs-Spark-aware split that this slice
establishes structurally for every subsequent slice.

## Slice Description

Bootstrap the working development environment for the Traffic Observability
Pipeline. After B1 lands, a contributor can clone the repo, run `cp .env.example
.env`, run `uv sync`, run `uv run pytest`, and `docker compose up -d kafka postgres
grafana` and have a clean green baseline. **B1 does not yet bring up a working
end-to-end pipeline** — that is the cumulative work of B2–B5. B1 only establishes
the directory layout, dependency manifests, container orchestration skeleton,
config surface, and validation toolchain that every subsequent slice depends on.

The bootstrap commits already produced `CLAUDE.md`, `DECISIONS.md` (with D-001
through D-010), `.claude/PRD.md`, and the slash command set. B1 produces the
*runnable* skeleton that those documents describe.

## User Story

As a **contributor about to start B2 (Generator + Kafka)**
I want to **clone the repo, run one config copy and one `uv sync`, and have a
working dev loop with linters, type checker, and test runner**
So that **I can write generator and schema code on day 1 of B2 without spending
the first hour scaffolding directories, picking dependency versions, debating
image tags, or arguing with `pytest` exit code 5**.

## Problem Statement

The repo currently has only documentation. Every executable artifact CLAUDE.md and
the PRD describe (`docker-compose.yml`, `.env.example`, `pyproject.toml`, `src/`
tree, `tests/` tree, `src/common/config.py`) is missing. As a result:

- `uv run pytest`, `uv run ruff check src tests`, and `uv run mypy src` all fail
  because there is no `pyproject.toml` and no source tree.
- `docker compose up -d` fails because there is no compose file.
- Every subsequent slice (B2–B5) would have to bikeshed dependency choices,
  directory layout, env-var naming, and image tags before writing a single line of
  pipeline code.
- The pure-vs-Spark-aware structural rule (CLAUDE.md, NFR-3.1) cannot be enforced
  on a tree that does not exist.

## Solution Statement

Land the runnable skeleton in one slice:

1. **Repo layout**: create the directory tree the PRD §11 describes, with
   `__init__.py` files where Python expects them and `.gitkeep` placeholders where
   later slices will add real artifacts.
2. **Tooling baseline**: `pyproject.toml` managed by `uv`, with `ruff`, `mypy`,
   and `pytest` as dev deps. No runtime deps yet — those land slice by slice as
   each owning slice introduces them. **Do not preinstall `pyspark`,
   `confluent-kafka`, or `psycopg`** — each is owned by a later slice.
3. **Config surface**: `.env.example` lists every env var the PRD names across all
   five blocks (kafka broker, topic, postgres credentials, warehouse path,
   checkpoint path, grafana admin password, generator rate). `src/common/config.py`
   loads them with type coercion via `os.environ` — pure stdlib, no `pyspark`,
   no `pydantic`, so the file is unit-testable on day 1.
4. **Compose skeleton**: `docker-compose.yml` declares the three services that can
   run on stock images today — `kafka` (KRaft), `postgres`, `grafana` — with
   healthchecks, named volumes, a single user-defined network, and env-var
   substitution from `.env`. **`spark` and `generator` are deliberately deferred
   to B3 and B2 respectively** so this slice does not ship a half-broken Spark
   image; see decision `D-011` below.
5. **Test smoke**: one trivial unit test that imports `src.common.config` and
   asserts a default value, so `uv run pytest tests/unit -q` exits 0 (not exit 5
   "no tests collected") on a fresh clone.
6. **Linter clean**: ruff and mypy pass on the empty-but-valid src tree.

The slice ships with three new `DECISIONS.md` entries (`D-011`, `D-012`, `D-013`)
that document the non-obvious choices below.

## Slice Metadata

**Slice Type**: New Pipeline Capability (foundation / scaffold)
**Estimated Complexity**: Low–Medium. The work is mechanical but the consequences
are far-reaching: every subsequent slice inherits the choices made here, and
fixing them later means touching every file.
**Components Touched**: repo skeleton, dependency manifest, env-var contract,
container orchestration (partial), config module. **Does NOT touch**: schemas,
transformations, streaming job, lakehouse, serving DB schema, dashboard, generator
code.
**Touches version triangle (Spark / Iceberg / Hadoop)**: **No**. B1 deliberately
ships zero JVM/JAR work. The Spark+Iceberg version triangle is owned by B3.

---

## DATA CONTRACT IMPACT

### Event Schema (`src/common/schemas.py`)
**No change.** This file does not exist yet and will be created in B2 when the
generator and schema land in the same slice. B1 must NOT pre-stub it, because
declaring an empty `StructType` would either type-check as `Any` (mypy noise) or
require a placeholder field that B2 would have to immediately delete.

### Lakehouse Table
**No change.** `lakehouse.web_events` is created by Spark on first write, in B3.

### Serving Tables (`sql/init.sql`)
**No change.** `sql/init.sql` is owned by B4. B1 ships a `sql/.gitkeep` placeholder
so the directory exists in the repo but the file is absent.

### Generator (`src/generator/producer.py`)
**No change.** Owned by B2. B1 creates `src/generator/__init__.py` so the package
exists, but `producer.py` is absent.

### Dashboard
**No change.** Grafana provisioning lands in B5. B1 creates `grafana/.gitkeep` so
the directory exists.

---

## DECISIONS TO LOG

Three entries to be appended to `DECISIONS.md` during `/execute`, in the same
commit as the implementation.

- **D-011 — `docker-compose.yml` skeleton declares only kafka, postgres, grafana; spark and generator deferred to their owning slices**
  - **Context**: PRD §12 calls B1 a "skeleton with placeholder services". The
    obvious read is "declare all six services with TODO config". The alternative
    is "declare only the three that can run on stock images today, defer the
    other two to the slices that will build their custom images".
  - **Options considered**:
    1. Declare all six in B1 with `image:` placeholders for spark/generator
       (problem: there is no upstream image for the generator, and the official
       Spark image needs a custom layer for Iceberg+Kafka+JDBC JARs that B3 owns).
    2. Declare all six with empty `build:` directives (problem: `docker compose
       config` fails because the Dockerfile paths do not exist).
    3. Declare only kafka, postgres, grafana (the three that need no custom
       image), with full healthchecks, named volumes, env substitution. Add spark
       in B3 and generator in B2.
  - **Chosen**: Option 3.
  - **Rationale**: B1 ships a compose file that is *useful* (`docker compose up
    -d kafka postgres grafana` works) instead of one that is *complete but
    broken*. B2 and B3 each own one new service, which keeps slice ownership
    crisp. The PRD's "skeleton with placeholder services" wording is loose enough
    to accommodate either reading; this one is the reading where the skeleton
    actually runs.

- **D-012 — Grafana image is `grafana/grafana`, not `grafana/grafana-oss`**
  - **Context**: CLAUDE.md and PRD §8 both say "Grafana OSS". The
    `grafana/grafana-oss` Docker Hub repository is being EOL'd starting with the
    12.4.0 release; Grafana Labs now publishes the same OSS binary under the
    `grafana/grafana` image name. The choice of *Grafana OSS* (vs Grafana
    Enterprise / Cloud) is unchanged — only the image name is.
  - **Options considered**:
    1. Pin `grafana/grafana-oss:12.4.2` (works today, but the tag will go stale
       when the repo stops receiving updates).
    2. Pin `grafana/grafana:12.4.2` (the actively-maintained image, same OSS
       binary).
  - **Chosen**: Option 2.
  - **Rationale**: We do not want to pin a tag in a deprecated repo at the
    moment of bootstrap. The license, the binary, and the demo behavior are
    identical. The PRD wording ("Grafana OSS") is correct as a *product* choice
    and stays correct; only the image string changes.

- **D-013 — Kafka image is `apache/kafka:4.0.2`, not Confluent or Bitnami**
  - **Context**: D-007 already locks in "KRaft mode, single broker". The
    remaining choice is *which* Docker image. The three plausible options are
    the official Apache image (`apache/kafka`), Confluent's image
    (`confluentinc/cp-kafka`), and Bitnami's image (`bitnami/kafka`).
  - **Options considered**:
    1. `confluentinc/cp-kafka` — most widely used in tutorials, but bundles
       Confluent-specific config conventions and a heavier base layer.
    2. `bitnami/kafka` — well-maintained, but a third-party packaging.
    3. `apache/kafka:4.0.2` — the official upstream Apache image (since KIP-975).
       Kafka 4.x is KRaft-only by design (ZooKeeper removed entirely), which
       hard-enforces the D-007 decision at the image level.
  - **Chosen**: Option 3.
  - **Rationale**: Picking the official upstream image keeps third-party
    packaging out of the dependency graph. Kafka 4.x being KRaft-only means
    there is literally no way to misconfigure this back into ZooKeeper mode,
    which is exactly what we want from a single-laptop demo where we will not
    revisit broker config. The 4.x bump is independent of the Spark 3.5.x pin
    in CLAUDE.md — those two version triangles do not interact.

---

## CONTEXT REFERENCES

### Relevant Codebase Files — READ BEFORE IMPLEMENTING

- `CLAUDE.md` (§Tech Stack, §Project Structure, §Notes) — the source of truth
  for the directory tree, dependency choices, and JAR rules. The directory tree
  in B1 must match `## Project Structure` exactly.
- `.claude/PRD.md` §5.5 (serving tables — names that B1's `.env.example` must
  reference indirectly via PG_DATABASE), §6 (architecture — names that map to
  compose service names), §11 (project structure — must match), §10 (NFRs —
  NFR-1, NFR-2, NFR-3 are validated by B1's tooling).
- `DECISIONS.md` — D-006 (single-writer Iceberg implies one Spark service in
  compose), D-007 (KRaft single-broker forces one kafka service), D-010
  (Grafana reads Postgres only, no Trino/DuckDB to declare).

### New Files to Create

- `.gitignore` — Python + uv + Spark/checkpoint + IDE noise.
- `.env.example` — full env-var contract; the authoritative list of config.
- `pyproject.toml` — `uv`-managed; only `ruff`, `mypy`, `pytest` as dev deps.
- `docker-compose.yml` — declares `kafka`, `postgres`, `grafana` services with
  healthchecks, named volumes, `web_events` network, and env substitution.
- `src/__init__.py` — empty.
- `src/common/__init__.py` — empty.
- `src/common/config.py` — env-var loader, stdlib only, no `pyspark` import.
- `src/generator/__init__.py` — empty (package created so B2 can drop
  `producer.py` in without scaffolding).
- `src/streaming/__init__.py` — empty (same reason for B3+B4).
- `tests/__init__.py` — empty.
- `tests/unit/__init__.py` — empty.
- `tests/unit/test_config.py` — one trivial test that imports `src.common.config`
  and asserts a default value, so `pytest` exits 0.
- `tests/integration/__init__.py` — empty.
- `data/.gitkeep` — placeholder; `servers.csv` lands in B2.
- `sql/.gitkeep` — placeholder; `init.sql` lands in B4.
- `grafana/.gitkeep` — placeholder; provisioning lands in B5.
- `docker/.gitkeep` — placeholder; service Dockerfiles land in B2 (generator) and
  B3 (spark).

### Relevant Documentation — READ BEFORE IMPLEMENTING

- [uv: Project structure and pyproject.toml](https://docs.astral.sh/uv/concepts/projects/)
  — confirms the `[project]` + `[tool.uv]` layout and how dev deps are declared.
- [Compose file specification: healthcheck](https://docs.docker.com/reference/compose-file/services/#healthcheck)
  — confirms healthcheck syntax we will use for kafka, postgres, grafana.
- [Compose file specification: depends_on with condition](https://docs.docker.com/reference/compose-file/services/#depends_on)
  — `condition: service_healthy` is the right gate for B2/B3 to wait on kafka and
  postgres later; we need the healthchecks defined now so those slices can rely
  on them.
- [Apache Kafka 4.0 Docker quickstart](https://kafka.apache.org/40/getting-started/docker/)
  — confirms env-var names for KRaft single-broker mode (`KAFKA_NODE_ID`,
  `KAFKA_PROCESS_ROLES`, `KAFKA_CONTROLLER_QUORUM_VOTERS`, etc.).
- [PostgreSQL official Docker image](https://hub.docker.com/_/postgres)
  — confirms `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, and
  `/docker-entrypoint-initdb.d/` mount semantics.
- [Grafana: Run Grafana via Docker](https://grafana.com/docs/grafana/latest/setup-grafana/installation/docker/)
  — confirms `GF_SECURITY_ADMIN_PASSWORD` env var and `/etc/grafana/provisioning`
  mount semantics that B5 will use.

### Patterns to Follow

**Naming**: snake_case for Python; kebab-case for compose service names where
multi-word; lowercase for lakehouse identifiers; snake_case for serving DB tables.

**Pure-vs-Spark-aware split**: `src/common/config.py` is the first concrete file
under `src/common/`. It MUST NOT import `pyspark`. Use stdlib `os` + type hints
only. This sets the precedent for `schemas.py` and `transformations.py` later.

**Schema declaration**: N/A in B1 (no schemas yet).

**foreachBatch**: N/A in B1 (no streaming code yet).

**Config**: every key in `.env.example` MUST have a corresponding loader in
`src/common/config.py`. Loaders return concrete typed values with sensible
defaults so unit tests don't need a `.env` file present.

**No hardcoded URLs**: nothing in `src/` may hardcode a broker address, JDBC URL,
warehouse path, or topic name. All come from `config.py`.

---

## IMPLEMENTATION PLAN

### Phase 1: Repo skeleton + tooling

Lay down directories, `__init__.py` stubs, `.gitkeep` placeholders, and
`.gitignore`. Establish the structural rule before any code is written.

### Phase 2: Dependency manifest + lockfile

Write `pyproject.toml` with the minimum dev-dep set and run `uv sync` to produce
`uv.lock`. Confirm `uv run ruff --version` and `uv run mypy --version` resolve.

### Phase 3: Config surface

Write `.env.example` (the env-var contract) and `src/common/config.py` (the
loader). One trivial unit test to assert pytest collects something.

### Phase 4: Compose skeleton

Write `docker-compose.yml` with kafka + postgres + grafana, healthchecks,
volumes, network, env substitution. Validate via `docker compose config`.

### Phase 5: Validation + DECISIONS.md update

Run the full validation suite. Append D-011, D-012, D-013 to `DECISIONS.md`.
Cross-check that the index table at the top of `DECISIONS.md` is updated.

---

## STEP-BY-STEP TASKS

Execute every task in order, top to bottom. Each task is atomic and validates
immediately.

### CREATE `.gitignore`

- **IMPLEMENT**: Python (`__pycache__/`, `*.pyc`, `*.pyo`, `.pytest_cache/`,
  `.mypy_cache/`, `.ruff_cache/`), uv (`.venv/`, `uv.lock` is NOT ignored),
  Spark+Iceberg local artifacts (`spark-warehouse/`, `checkpoints/`, `metastore_db/`,
  `derby.log`), env (`.env`, but NOT `.env.example`), IDE (`.idea/`, `.vscode/`,
  `*.swp`, `.DS_Store`), build artifacts (`dist/`, `build/`, `*.egg-info/`).
- **PATTERN**: Standard Python+uv project ignore. No code reference yet.
- **IMPORTS**: n/a
- **GOTCHA**: Do NOT ignore `uv.lock` — uv lockfiles MUST be checked in. Do NOT
  ignore `.env.example` — only `.env`. Do NOT add `data/`, `sql/`, `grafana/`,
  `docker/` to the ignore list — those directories are checked in even if their
  contents are slice-by-slice.
- **VALIDATE**: `cat .gitignore | head` (confirm presence) — manual eyeball.

### CREATE `pyproject.toml`

- **IMPLEMENT**: `[project]` block with name `traffic-observability-pipeline`,
  version `0.1.0`, requires-python `>=3.11,<3.12`, empty `dependencies = []`.
  `[tool.uv]` block with `dev-dependencies = ["ruff>=0.6", "mypy>=1.10",
  "pytest>=8.0"]`. `[tool.ruff]` with `line-length = 100`, `target-version =
  "py311"`, `[tool.ruff.lint]` with `select = ["E", "F", "I", "W", "UP", "B"]`.
  `[tool.mypy]` with `python_version = "3.11"`, `strict = true`, `files = ["src"]`.
  `[tool.pytest.ini_options]` with `testpaths = ["tests"]`, `addopts = "-ra
  --strict-markers"`.
- **PATTERN**: Standard uv-managed pyproject.toml. No code reference yet.
- **IMPORTS**: n/a
- **GOTCHA**: Do NOT add `pyspark`, `confluent-kafka`, `kafka-python`, `psycopg`,
  `psycopg2`, `sqlalchemy`, `testcontainers`, or any other runtime dep here. Each
  is owned by a later slice. Adding them now would violate "dependencies are
  introduced by the slice that uses them".
  Pin Python to `<3.12` because PySpark 3.5 historically struggles on 3.12+ and
  we want to lock the Python interpreter to what the (future) Spark image ships.
- **VALIDATE**: `uv sync && uv run ruff --version && uv run mypy --version && uv run pytest --version`

### CREATE `.env.example`

- **IMPLEMENT**: Document every env var the pipeline will need across all five
  blocks, grouped by component, with a comment per group:

  ```
  # ---------- Kafka ----------
  KAFKA_BOOTSTRAP_SERVERS=kafka:9092
  KAFKA_TOPIC=web_events

  # ---------- Generator ----------
  GENERATOR_RATE_PER_SEC=10
  GENERATOR_JITTER_SECONDS=30

  # ---------- Spark ----------
  SPARK_DRIVER_MEMORY=2g
  SPARK_EXECUTOR_MEMORY=2g
  SPARK_CHECKPOINT_DIR=/opt/checkpoints/web_events
  ICEBERG_WAREHOUSE_DIR=/opt/warehouse
  ICEBERG_CATALOG=lakehouse
  ICEBERG_TABLE=web_events
  WATERMARK_DURATION=2 minutes

  # ---------- Postgres ----------
  POSTGRES_HOST=postgres
  POSTGRES_PORT=5432
  POSTGRES_DB=serving
  POSTGRES_USER=serving
  POSTGRES_PASSWORD=serving
  POSTGRES_SCHEMA=serving

  # ---------- Grafana ----------
  GRAFANA_ADMIN_PASSWORD=admin
  ```

  All values are local-laptop defaults. Production deployments would override
  POSTGRES_PASSWORD and GRAFANA_ADMIN_PASSWORD via a real `.env`.
- **PATTERN**: PRD §5.5 dictates the postgres schema name; D-007 dictates kafka
  topic semantics; CLAUDE.md "Notes" dictates the 2g/2g memory cap; D-009
  dictates the 2-minute watermark.
- **IMPORTS**: n/a
- **GOTCHA**: `KAFKA_BOOTSTRAP_SERVERS=kafka:9092` is the *intra-compose* address.
  When B2 lands and the generator container connects, it will use this. The
  *host-side* address (for `kafka-console-consumer` from the dev shell) will be
  exposed in compose as `localhost:9092` and `kafka:9092` simultaneously via dual
  listener config in B2's compose update — that complexity stays in B2's plan.
- **VALIDATE**: `grep -c "=" .env.example` — confirm at least 15 env vars
  present.

### CREATE `src/__init__.py`, `src/common/__init__.py`, `src/generator/__init__.py`, `src/streaming/__init__.py`

- **IMPLEMENT**: Empty files. Each is exactly zero bytes.
- **PATTERN**: Standard Python package marker.
- **IMPORTS**: n/a
- **GOTCHA**: Make sure they are empty. Even a docstring would be noise here.
  These exist purely so Python can find the packages and so the directories can
  be checked into git.
- **VALIDATE**: `find src -name "__init__.py" -size 0 | wc -l` should print `4`.

### CREATE `src/common/config.py`

- **IMPLEMENT**:
  ```python
  """Env-var-driven configuration for the Traffic Observability Pipeline.

  Pure stdlib. No pyspark, no pydantic, no third-party imports. Every value
  has a sensible local-laptop default so unit tests can import this module
  without an env file present.
  """
  from __future__ import annotations

  import os
  from dataclasses import dataclass


  def _get(name: str, default: str) -> str:
      return os.environ.get(name, default)


  def _get_int(name: str, default: int) -> int:
      raw = os.environ.get(name)
      return int(raw) if raw is not None else default


  @dataclass(frozen=True)
  class KafkaConfig:
      bootstrap_servers: str
      topic: str


  @dataclass(frozen=True)
  class GeneratorConfig:
      rate_per_sec: int
      jitter_seconds: int


  @dataclass(frozen=True)
  class SparkConfig:
      driver_memory: str
      executor_memory: str
      checkpoint_dir: str
      iceberg_warehouse_dir: str
      iceberg_catalog: str
      iceberg_table: str
      watermark_duration: str


  @dataclass(frozen=True)
  class PostgresConfig:
      host: str
      port: int
      database: str
      user: str
      password: str
      schema: str

      @property
      def jdbc_url(self) -> str:
          return f"jdbc:postgresql://{self.host}:{self.port}/{self.database}"


  @dataclass(frozen=True)
  class GrafanaConfig:
      admin_password: str


  def load_kafka_config() -> KafkaConfig:
      return KafkaConfig(
          bootstrap_servers=_get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
          topic=_get("KAFKA_TOPIC", "web_events"),
      )


  def load_generator_config() -> GeneratorConfig:
      return GeneratorConfig(
          rate_per_sec=_get_int("GENERATOR_RATE_PER_SEC", 10),
          jitter_seconds=_get_int("GENERATOR_JITTER_SECONDS", 30),
      )


  def load_spark_config() -> SparkConfig:
      return SparkConfig(
          driver_memory=_get("SPARK_DRIVER_MEMORY", "2g"),
          executor_memory=_get("SPARK_EXECUTOR_MEMORY", "2g"),
          checkpoint_dir=_get("SPARK_CHECKPOINT_DIR", "/opt/checkpoints/web_events"),
          iceberg_warehouse_dir=_get("ICEBERG_WAREHOUSE_DIR", "/opt/warehouse"),
          iceberg_catalog=_get("ICEBERG_CATALOG", "lakehouse"),
          iceberg_table=_get("ICEBERG_TABLE", "web_events"),
          watermark_duration=_get("WATERMARK_DURATION", "2 minutes"),
      )


  def load_postgres_config() -> PostgresConfig:
      return PostgresConfig(
          host=_get("POSTGRES_HOST", "postgres"),
          port=_get_int("POSTGRES_PORT", 5432),
          database=_get("POSTGRES_DB", "serving"),
          user=_get("POSTGRES_USER", "serving"),
          password=_get("POSTGRES_PASSWORD", "serving"),
          schema=_get("POSTGRES_SCHEMA", "serving"),
      )


  def load_grafana_config() -> GrafanaConfig:
      return GrafanaConfig(
          admin_password=_get("GRAFANA_ADMIN_PASSWORD", "admin"),
      )
  ```
- **PATTERN**: PRD §10 NFR-3.2; CLAUDE.md "Configuration" rules.
- **IMPORTS**: stdlib only — `os`, `dataclasses`, `__future__.annotations`.
- **GOTCHA**: Do NOT use `pydantic.BaseSettings` — adds a runtime dep that B1
  does not need. Do NOT import `pyspark` (banned per CLAUDE.md NFR-3.1). The
  `jdbc_url` property on `PostgresConfig` is the *only* place that knows the
  postgres URL shape — keep it there so B4 can change it without grepping.
- **VALIDATE**: `uv run python -c "from src.common.config import load_kafka_config; print(load_kafka_config())"`

### CREATE `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py`

- **IMPLEMENT**: Empty files.
- **PATTERN**: Same as `src/__init__.py`.
- **IMPORTS**: n/a
- **GOTCHA**: `tests/integration/__init__.py` exists even though there are no
  integration tests yet — B3 will add them and we want the package present.
- **VALIDATE**: `find tests -name "__init__.py" -size 0 | wc -l` should print `3`.

### CREATE `tests/unit/test_config.py`

- **IMPLEMENT**:
  ```python
  """Smoke tests for src.common.config.

  These exist primarily so `uv run pytest tests/unit -q` exits 0 (not exit 5
  "no tests collected") on a fresh clone. They will be supplemented by real
  config tests as later slices add config keys with non-trivial loading rules.
  """
  from __future__ import annotations

  import os
  from unittest.mock import patch

  from src.common.config import (
      load_generator_config,
      load_kafka_config,
      load_postgres_config,
      load_spark_config,
  )


  def test_kafka_config_uses_defaults_when_env_unset() -> None:
      with patch.dict(os.environ, {}, clear=True):
          cfg = load_kafka_config()
      assert cfg.bootstrap_servers == "kafka:9092"
      assert cfg.topic == "web_events"


  def test_kafka_config_reads_env_overrides() -> None:
      with patch.dict(
          os.environ,
          {"KAFKA_BOOTSTRAP_SERVERS": "localhost:19092", "KAFKA_TOPIC": "test_topic"},
          clear=True,
      ):
          cfg = load_kafka_config()
      assert cfg.bootstrap_servers == "localhost:19092"
      assert cfg.topic == "test_topic"


  def test_generator_config_coerces_int() -> None:
      with patch.dict(
          os.environ,
          {"GENERATOR_RATE_PER_SEC": "25", "GENERATOR_JITTER_SECONDS": "5"},
          clear=True,
      ):
          cfg = load_generator_config()
      assert cfg.rate_per_sec == 25
      assert cfg.jitter_seconds == 5


  def test_postgres_config_jdbc_url() -> None:
      with patch.dict(
          os.environ,
          {
              "POSTGRES_HOST": "db",
              "POSTGRES_PORT": "5433",
              "POSTGRES_DB": "serving",
          },
          clear=True,
      ):
          cfg = load_postgres_config()
      assert cfg.jdbc_url == "jdbc:postgresql://db:5433/serving"


  def test_spark_config_defaults_match_clauseMd() -> None:
      with patch.dict(os.environ, {}, clear=True):
          cfg = load_spark_config()
      assert cfg.driver_memory == "2g"
      assert cfg.executor_memory == "2g"
      assert cfg.watermark_duration == "2 minutes"
  ```
- **PATTERN**: Pytest + stdlib `unittest.mock.patch.dict`. No conftest needed.
- **IMPORTS**: stdlib only.
- **GOTCHA**: `clear=True` on `patch.dict` is essential — without it the host
  developer's `KAFKA_BOOTSTRAP_SERVERS` (if set) would leak into the test and
  break the default-value assertion. Tests MUST be hermetic.
- **VALIDATE**: `uv run pytest tests/unit -q` — should report 5 passed.

### CREATE `data/.gitkeep`, `sql/.gitkeep`, `grafana/.gitkeep`, `docker/.gitkeep`

- **IMPLEMENT**: Empty files at each path.
- **PATTERN**: Standard git placeholder convention.
- **IMPORTS**: n/a
- **GOTCHA**: Do NOT create `docker/spark/.gitkeep` or `docker/generator/.gitkeep`
  — those subdirectories are owned by B3 and B2. B1's `docker/.gitkeep` is enough
  to put the parent directory in git history.
- **VALIDATE**: `find data sql grafana docker -name .gitkeep` should print 4
  paths.

### CREATE `docker-compose.yml`

- **IMPLEMENT**:
  ```yaml
  name: traffic-observability-pipeline

  services:
    kafka:
      image: apache/kafka:4.0.2
      container_name: top-kafka
      hostname: kafka
      ports:
        - "9092:9092"
      environment:
        KAFKA_NODE_ID: 1
        KAFKA_PROCESS_ROLES: broker,controller
        KAFKA_LISTENERS: PLAINTEXT://:9092,CONTROLLER://:9093
        KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:9092
        KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: PLAINTEXT:PLAINTEXT,CONTROLLER:PLAINTEXT
        KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER
        KAFKA_CONTROLLER_QUORUM_VOTERS: 1@kafka:9093
        KAFKA_INTER_BROKER_LISTENER_NAME: PLAINTEXT
        KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
        KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR: 1
        KAFKA_TRANSACTION_STATE_LOG_MIN_ISR: 1
      healthcheck:
        test: ["CMD-SHELL", "/opt/kafka/bin/kafka-broker-api-versions.sh --bootstrap-server localhost:9092 >/dev/null 2>&1"]
        interval: 10s
        timeout: 5s
        retries: 10
        start_period: 30s
      networks:
        - top-net
      volumes:
        - kafka_data:/var/lib/kafka/data

    postgres:
      image: postgres:16.13
      container_name: top-postgres
      hostname: postgres
      ports:
        - "5432:5432"
      environment:
        POSTGRES_USER: ${POSTGRES_USER:-serving}
        POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-serving}
        POSTGRES_DB: ${POSTGRES_DB:-serving}
      healthcheck:
        test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-serving} -d ${POSTGRES_DB:-serving}"]
        interval: 5s
        timeout: 5s
        retries: 10
      networks:
        - top-net
      volumes:
        - postgres_data:/var/lib/postgresql/data

    grafana:
      image: grafana/grafana:12.4.2
      container_name: top-grafana
      hostname: grafana
      ports:
        - "3000:3000"
      environment:
        GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:-admin}
        GF_USERS_ALLOW_SIGN_UP: "false"
      depends_on:
        postgres:
          condition: service_healthy
      healthcheck:
        test: ["CMD-SHELL", "wget -q --spider http://localhost:3000/api/health || exit 1"]
        interval: 10s
        timeout: 5s
        retries: 10
        start_period: 15s
      networks:
        - top-net
      volumes:
        - grafana_data:/var/lib/grafana

  volumes:
    kafka_data:
    postgres_data:
    grafana_data:

  networks:
    top-net:
      driver: bridge
  ```
- **PATTERN**: Compose v2 spec; the kafka env-var block is straight from the
  Apache Kafka 4.0 quickstart referenced in "Relevant Documentation".
- **IMPORTS**: n/a
- **GOTCHA**: 
  - `KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:9092` is the *intra-compose*
    address. B2 will need a second listener for host-side `kafka-console-consumer`
    access. **Defer that to B2** — adding it now without a generator to test it
    invites silent breakage. The host port 9092 is published so B2 can add the
    second listener without changing the published port.
  - The `KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1` (and its two siblings) are
    REQUIRED for a single-broker setup. Without them, internal topics fail to
    create on first startup with replication-factor errors.
  - Volumes use plain names (`kafka_data`, not `top_kafka_data`) — Compose v2
    auto-prefixes with the project name (`name: traffic-observability-pipeline`)
    so the on-disk volume is unambiguously namespaced.
  - `depends_on` with `condition: service_healthy` only works because postgres
    has a healthcheck — if B1 forgets the postgres healthcheck, grafana will
    start before postgres is ready and Grafana datasource provisioning will fail
    in B5.
  - **Do NOT** use `version: "3.8"` at the top of the file — Compose v2 has
    deprecated the `version` key, and including it produces a warning on every
    invocation.
- **VALIDATE**: `docker compose config -q` (must exit 0 with no warnings).

### UPDATE `DECISIONS.md`

- **IMPLEMENT**: Append three new entries `D-011`, `D-012`, `D-013` (full text in
  the "Decisions to Log" section above). Update the index table at the top of
  the file with three new rows. Use the same lightweight ADR format as D-001
  through D-010.
- **PATTERN**: `DECISIONS.md` lines 36–86 (D-001 entry) is the canonical example
  of the format.
- **IMPORTS**: n/a
- **GOTCHA**: The index table is sorted by ID, not by date. Append rows in
  ID order. Date for all three entries is the date `/execute` runs (use
  `2026-04-09` per the system date today).
- **VALIDATE**: `grep -c "^## D-" DECISIONS.md` should print `13` (was `10`).

---

## TESTING STRATEGY

### Unit Tests

`tests/unit/test_config.py` exercises every loader in `src.common.config`:
default values, env-var overrides, int coercion, and the `jdbc_url` derived
property. The test count is 5. The bar is "pytest exits 0 on a fresh clone";
extensive edge-case coverage of config loading is unwarranted at this scale.

### Integration Test

**No change.** B1 does not add an integration test. B3 will add the first one
when there is something Spark-related to integration-test.

### Manual Smoke Test

```bash
# Fresh clone simulation
cp .env.example .env
uv sync
uv run pytest tests/unit -q
uv run ruff check src tests
uv run mypy src
docker compose config -q
docker compose up -d kafka postgres grafana
sleep 30
docker compose ps   # all three should be (healthy)
docker compose down
```

After this sequence, the next contributor (or future-you) starting B2 should
have zero "wait, how do I…" friction.

### Edge Cases

- **Fresh clone, no `.env` file**: `uv run pytest tests/unit -q` MUST still
  pass because every config loader has a default. The test file uses
  `patch.dict(..., clear=True)` to confirm this.
- **Host port 9092 already in use**: compose will fail to start kafka with a
  clear "port already allocated" error. This is expected and not B1's problem
  to fix; the contributor will free the port.
- **Existing `.env` from a future slice**: B1's `.env.example` is a strict
  subset of any future `.env` (B2/B3/B4/B5 only ADD keys, never rename), so an
  existing `.env` is forward-compatible.

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
# B1 ships no integration tests. The directory exists but is empty.
# Skipping this level is correct in B1.
```

### Level 4: Stack Smoke Test
```bash
cp -n .env.example .env || true
docker compose config -q
docker compose up -d kafka postgres grafana
sleep 30
docker compose ps
docker compose exec postgres pg_isready -U serving -d serving
curl -fsS http://localhost:3000/api/health
docker compose down
```

### Level 5: Slice-Specific Manual Validation

```bash
# Confirm directory tree matches PRD §11
find . -type d -not -path './.git*' -not -path './.venv*' -not -path './.agents*' -not -path './.claude*'

# Confirm DECISIONS.md grew by exactly 3 entries
grep -c "^## D-" DECISIONS.md   # 13

# Confirm .env.example covers every key src/common/config.py reads
uv run python -c "
import re
keys_env = set()
with open('.env.example') as f:
    for line in f:
        m = re.match(r'^([A-Z][A-Z0-9_]+)=', line.strip())
        if m:
            keys_env.add(m.group(1))
keys_code = set()
with open('src/common/config.py') as f:
    for line in f:
        m = re.search(r'_get(?:_int)?\(\"([A-Z][A-Z0-9_]+)\"', line)
        if m:
            keys_code.add(m.group(1))
print('only in .env.example:', sorted(keys_env - keys_code))
print('only in config.py:   ', sorted(keys_code - keys_env))
assert keys_env == keys_code, 'env contract drift'
print('OK')
"
```

---

## ACCEPTANCE CRITERIA

- [ ] `slice/B1-foundation` branch exists and the working tree is clean before commit
- [ ] `uv sync` succeeds and produces `uv.lock`
- [ ] `uv run ruff check src tests` exits 0 with zero warnings
- [ ] `uv run mypy src` exits 0 with zero errors
- [ ] `uv run pytest tests/unit -q` reports 5 passed, exit 0
- [ ] `docker compose config -q` exits 0 with zero warnings (no `version:` key, no
      env substitution warnings)
- [ ] `docker compose up -d kafka postgres grafana` brings all three services to
      `(healthy)` within 60 seconds on a warm Docker cache
- [ ] `curl -fsS http://localhost:3000/api/health` returns 200 OK
- [ ] `docker compose down` (without `-v`) leaves named volumes intact
- [ ] `DECISIONS.md` contains entries D-011, D-012, D-013, and the index table
      lists all 13 decisions
- [ ] No file under `src/common/` imports `pyspark` (verified by `grep -r "import
      pyspark" src/common/`)
- [ ] No file under `src/` hardcodes a broker address, JDBC URL, or warehouse
      path (verified by `grep -rE "kafka:9092|jdbc:postgresql" src/` returning
      only `src/common/config.py`)
- [ ] `pyproject.toml` declares zero runtime dependencies (only dev-dependencies)
- [ ] Single PR `slice/B1-foundation → main` is the unit of review

---

## COMPLETION CHECKLIST

- [ ] All tasks completed in order
- [ ] Each task validation passed before moving to the next
- [ ] Full validation suite green (Levels 1, 2, 4, 5)
- [ ] Manual smoke test confirmed (`docker compose ps` shows three healthy)
- [ ] `DECISIONS.md` updated with D-011, D-012, D-013 in the same commit as the
      implementation
- [ ] Plan annotated as complete in `.agents/plans/B1-foundation.md` (add a
      `## Status: Complete` line at the top after merge)
- [ ] PR merged to `main`; `slice/B1-foundation` branch can be deleted

---

## NOTES

**Why no Spark or generator service in B1?** See decision `D-011`. Briefly:
those services require custom Dockerfiles whose work belongs to B3 and B2
respectively, and the PRD's "skeleton with placeholder services" wording is
loose enough to defer them. Shipping a compose file that *runs* (3 services
healthy) is more valuable than shipping one that *enumerates everything* but
breaks on `up -d`.

**Why pin Python `<3.12`?** PySpark 3.5 has had wobbles on Python 3.12+
historically, and the (future) Spark 3.5 image will ship Python 3.11. We pin
Python 3.11 in `pyproject.toml` so the dev environment matches the
(future) container environment, removing one class of "works on my laptop"
failure before B3 even starts.

**Why no `pyspark` in `pyproject.toml` yet?** B1 has no Spark code to lint, no
SparkSession to import, no integration test to boot. Adding the dep now would
force `uv sync` to download the ~300 MB pyspark wheel for zero benefit. B3 adds
it as a dev-dep when it adds the integration test.

**Forward-compat note for B2:** B2 will need to add a second Kafka listener so
host-side tools (`kafka-console-consumer`) can connect from `localhost:9092`.
The published port is already exposed in B1, and the listener-name conventions
in this compose file (`PLAINTEXT://...`) are designed to be extended without a
breaking change. B2's plan should reference `D-007` and this note.

**Forward-compat note for B5:** Grafana already has `depends_on: postgres
condition: service_healthy`, so B5's provisioning files (which need postgres
schema present) will Just Work as long as B4 lands postgres init via
`/docker-entrypoint-initdb.d/`. The mount of `sql/init.sql` into postgres is
B4's responsibility, not B1's.

**Things considered and rejected for B1 scope:**

- A `Makefile` or `justfile` wrapping the common commands. Rejected: every
  command in CLAUDE.md is already short. A wrapper adds a file to maintain.
- A pre-commit hook config. Rejected: not in the PRD's NFR list and adds setup
  friction for new contributors.
- A `README.md`. Rejected: CLAUDE.md is the entry point and the PRD does not
  require a separate README. Adding one would duplicate content.
- An `__about__.py` or version constant. Rejected: `pyproject.toml` is the
  single source of truth for the version.
- `pytest-cov`. Rejected: coverage is not in the PRD's NFR list, and the
  pure-vs-Spark-aware split makes coverage trivially high on the unit suite by
  construction.

**Confidence: 9/10.** The slice is mechanical and well-defined. The 1-point
reservation is for unexpected `apache/kafka:4.0.2` env-var quirks on a fresh
KRaft single-broker bring-up — that is the only step that touches a
not-yet-validated container image, and the listener config is the most likely
place for a small surprise. Mitigation: the kafka healthcheck will fail loudly
within 30 seconds if the broker can't reach itself, so any breakage is
diagnosed immediately rather than masked.
