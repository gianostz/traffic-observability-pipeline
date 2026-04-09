---
description: Prime agent with codebase understanding for the streaming pipeline
---

# Prime: Load Project Context

## Objective

Build comprehensive understanding of the streaming pipeline by analyzing structure,
documentation, schemas, and the streaming job. The goal is to be productive on a
Spark/Iceberg/Kafka codebase without breaking the things that are easy to break in
this stack: classpath skew, broken checkpoints, silent schema drift.

## Process

### 1. Analyze Project Structure

List all tracked files:
!`git ls-files`

Show directory structure:
On Linux, run: `tree -L 3 -I '__pycache__|.git|.venv|node_modules|spark-warehouse|checkpoints'`

### 2. Read Core Documentation

In this order — earlier files give the "why" that explains the later files:

1. `.claude/PRD.md` — what we are building and why
2. `CLAUDE.md` — project conventions and working rules
3. `DECISIONS.md` — running log of non-obvious trade-offs (read this BEFORE proposing
   any architectural change — most "obvious improvements" have already been considered
   and rejected for documented reasons)
4. `README.md`

### 3. Identify Key Files

Read these to understand the actual data flow:

- **Schemas (the data contract)**: `src/common/schemas.py`
- **Pure transformations (the business rules)**: `src/common/transformations.py`
- **The streaming job (the topology)**: `src/streaming/stream_processor.py`
- **The producer (what enters the system)**: `src/generator/producer.py`
- **Reference data**: `data/server_registry.json`
- **Serving DB schema**: `sql/init.sql`
- **Local stack definition**: `docker-compose.yml`
- **Spark image — version pins live here**: `docker/spark/Dockerfile`
- **Dashboard provisioning**: `grafana/provisioning/dashboards/`

Also skim:
- `tests/unit/test_transformations.py` — shows how the pure-function split is enforced
- `tests/integration/test_iceberg_write.py` — shows the integration test scope

If any of these files do not exist yet, that is fine — note which ones are missing so
you know which parts of the pipeline have not been built.

### 4. Understand Current State

Check recent activity:
!`git log -10 --oneline`

Check current branch and status:
!`git status`

Check active plans:
!`ls -la .agents/plans/ 2>/dev/null || echo "No plans yet"`

## Output Report

Provide a concise summary covering:

### Project Overview
- One-line purpose (what the pipeline does end-to-end)
- Where this sits in the build timeline
- What is intentionally out of scope (per `DECISIONS.md`)

### Architecture
- Data flow: producer → Kafka → Spark → {lakehouse, serving DB} → dashboard
- Source semantics (at-least-once / watermark / late-data policy)
- Which sink owns which tables
- Idempotency story for each sink

### Tech Stack
- Language and major library versions (especially Spark, Iceberg, Kafka client)
- Pinned vs floating versions — flag any drift risk
- Test framework split (unit vs integration)

### Code Patterns
- The pure-vs-Spark-aware split — confirm `src/common/transformations.py` does NOT
  import `pyspark`
- Schema declaration style (explicit `StructType`, no inference)
- Config through `src/common/config.py`, no hardcoded URLs in `src/`

### Current State
- Active branch
- Last few commits
- Any active plan files in `.agents/plans/`
- Any uncommitted changes that look in-progress

### Risks & Watch-outs
- Any version skew you can see between `docker/spark/Dockerfile` and `requirements.txt`
- Any place where pure functions accidentally import `pyspark`
- Any decision in `DECISIONS.md` that the current code appears to violate
- Any file referenced in the PRD that does not exist yet

**Make this summary easy to scan — bullet points and clear headers. Flag risks in bold.**