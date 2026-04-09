---
description: Create global rules (CLAUDE.md) from a data-pipeline codebase
---

# Create Global Rules

Generate a `CLAUDE.md` file by analyzing a data / streaming / lakehouse codebase and
extracting patterns.

---

## Objective

Create project-specific global rules that give Claude context about:
- What this pipeline does end-to-end
- Which technologies are pinned to which versions (and where the pin lives)
- How the code is organized — especially the pure-vs-Spark-aware split
- Conventions for schemas, sinks, error handling, and config
- How to build, test, validate, and bring the local stack up

---

## Phase 1: DISCOVER

### Identify Project Type

Determine what kind of data project this is:

| Type                          | Indicators                                                            |
| ----------------------------- | --------------------------------------------------------------------- |
| Streaming pipeline            | Kafka / Pulsar / Kinesis client deps, Spark Structured Streaming      |
| Batch ETL                     | Airflow DAGs, scheduled Spark jobs, no streaming sources              |
| Lakehouse compute             | Iceberg / Delta / Hudi tables, catalog config (Hadoop / REST / Glue)  |
| Serving / API on top of data  | FastAPI/Flask + DB driver, no Spark                                   |
| Lambda architecture           | Both batch and streaming jobs in the same repo                        |
| Notebook-driven analysis      | `notebooks/` dominant, little or no `src/` structure                  |
| Library / shared utilities    | `pyproject.toml` with `[project]` packaging, no entry-point job       |
| ML pipeline                   | feature stores, model registry, training/serving split                |

### Analyze Configuration

Look at root configuration files:

```
pyproject.toml / requirements.txt   → Python deps, pin discipline
docker-compose.yml                  → local stack components
docker/*/Dockerfile                 → JAR / Spark / Iceberg version pins
spark-defaults.conf                 → Spark config, catalog config
sql/*.sql                           → serving DB schemas
grafana/provisioning/               → dashboards, datasources
.env.example                        → config surface area
```

The Dockerfiles and `spark-defaults.conf` are usually where the **real** version pins
live for a Spark project — not `requirements.txt`. Read them.

### Map Directory Structure

Where does each kind of code live?
- Pure functions (no Spark dependency)
- Spark job definitions
- Producers / consumers / generators
- Schemas / data contracts
- Tests (unit vs integration split)
- Reference data
- Migrations / DDL
- Dashboards / observability config

---

## Phase 2: ANALYZE

### Extract Tech Stack

From config files, identify and **pin**:
- Python version
- Spark version + Scala version (Spark JARs are Scala-version-specific)
- Iceberg version + the Spark Runtime JAR version that matches it
- Hadoop version
- Kafka client version
- JDBC driver version
- Test framework versions (pytest, testcontainers)

### Identify Patterns

Study existing code for:
- **Schema declaration**: explicit `StructType` vs inference
- **Pure-vs-Spark split**: do `src/common/` files import `pyspark`? They shouldn't.
- **Sink patterns**: how are lakehouse writes done? How is `foreachBatch` structured?
- **Idempotency**: how does each sink handle Spark restart / replay?
- **Config**: env-driven, hardcoded, or hybrid?
- **Logging**: structured (key=value, JSON) or print-statement-driven?
- **Error handling**: malformed events dropped / dead-lettered / failed-on?
- **Test split**: what is unit, what is integration, what is the integration budget?

### Find Key Files

The files a new contributor would need to read first:
- The data contract (`schemas.py` or equivalent)
- The pure transformations (the business rules)
- The streaming job (the topology)
- The producer / source
- The serving DB DDL
- The Docker stack definition
- The decisions log

---

## Phase 3: GENERATE

### Create CLAUDE.md

Use the template at `.agents/CLAUDE-template.md` as a starting point.

**Output path**: `CLAUDE.md` (project root)

**Adapt to the project:**
- Remove sections that don't apply
- Add sections specific to this project's data flow
- Pin versions explicitly in the Tech Stack table
- Document the pure-vs-Spark-aware split if it exists

**Required sections for a data project:**

1. **Project Overview** — what the pipeline does end-to-end, in one paragraph
2. **Tech Stack** — every component, with **pinned versions** and the file the pin
   lives in
3. **Commands** — `docker compose up`, `pytest` (unit + integration), validation
4. **Project Structure** — directory tree, with the pure-vs-Spark split annotated
5. **Architecture** — ASCII data flow, source semantics, sink ownership, idempotency
   story
6. **Code Patterns** — pure-vs-Spark split, schema discipline, config discipline,
   logging discipline, error handling discipline
7. **Testing** — unit vs integration split, integration test budget
8. **Validation** — every command needed to confirm a green build
9. **Key Files** — table of must-read files
10. **Working Conventions** — PRD-first, plan before code, decisions are artifacts,
    validation is non-negotiable

**Optional sections (add if relevant):**
- Schema evolution policy
- Backfill / replay procedures
- Dead-letter handling
- Multi-environment config (dev / staging / prod)

---

## Phase 4: OUTPUT

```markdown
## Global Rules Created

**File**: `CLAUDE.md`

### Project Type
{Detected project type}

### Tech Stack Summary
{Key technologies with pinned versions}

### Pure-vs-Spark-aware split
{Detected: yes/no/partial. If partial, list the violations.}

### Structure
{Brief structure overview}

### Decisions log
{Exists / does not exist. If it does not exist, recommend creating one.}

### Next Steps
1. Review the generated `CLAUDE.md`
2. Confirm the version pins are correct (check `docker/spark/Dockerfile`)
3. Add any project-specific gotchas to the Notes section
4. If `DECISIONS.md` does not exist, create it with the first 3-5 decisions extracted
   from the codebase
5. Optionally add reference docs in `.agents/reference/` for tricky topics (Iceberg
   catalog config, JDBC sink semantics, etc.)
```

---

## Tips

- Keep CLAUDE.md focused and scannable. A new contributor should be able to read it
  in 5 minutes and know where to put their first change.
- Don't duplicate documentation that lives elsewhere — link instead.
- Focus on **conventions and constraints**, not exhaustive API documentation.
- Pin versions. Floating versions in a Spark project are the #1 cause of "works on my
  machine" failures.
- Update `CLAUDE.md` whenever a `DECISIONS.md` entry changes a convention.
