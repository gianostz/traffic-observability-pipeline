---
description: "Plan a vertical slice through the streaming pipeline with deep codebase analysis"
argument-hint: [feature description]
---

# Plan a Vertical Slice

## Slice: $ARGUMENTS

## Mission

Transform a feature request into a comprehensive implementation plan for a vertical
slice through the streaming pipeline — generator → Kafka → Spark enrichment →
{lakehouse sink, serving sink} → dashboard panel — through systematic codebase
analysis, external research, and strategic planning.

**Core Principle**: We do NOT write code in this phase. The goal is to create a
context-rich implementation plan that enables one-pass implementation success.

**Vertical-slice rule**: Plans should deliver something demonstrable end-to-end. A
plan that adds a column to the schema but does not surface it anywhere is rarely
useful; prefer "add `device_type` to events, surface it in the endpoint stats serving
table, add a dashboard breakdown" as a single slice.

**Decisions discipline**: Every plan that introduces a non-obvious trade-off MUST
list the decision in its "Decisions to Log" section. The execute step will then
write the entry to `DECISIONS.md` in the same commit as the implementation.

## Planning Process

### Phase 1: Slice Understanding

**Deep Slice Analysis:**

- Extract the core problem being solved (correctness, observability, performance, scope).
- Identify the user value: who benefits from this slice and how do they notice?
- Determine slice type: New Pipeline Capability / Schema Evolution / Sink Addition /
  Performance Optimization / Observability Improvement / Bug Fix.
- Assess complexity: Low / Medium / High.
- Map affected components: generator, schemas, transformations, streaming job,
  lakehouse table, serving DB, dashboard.

**Create User Story format (or refine if one was provided):**

```
As a <type of user — operator, analyst, on-call engineer, etc.>
I want to <action / capability>
So that <benefit / value>
```

### Phase 2: Codebase Intelligence Gathering

**1. Project Structure Refresher**

- Confirm the pure-vs-Spark-aware split is intact in `src/common/transformations.py`.
- Map which files this slice will touch.
- Identify config keys that need to be added to `src/common/config.py`.

**2. Pattern Recognition**

- Search the codebase for similar transformations / sinks / panels you can mirror.
- Extract conventions:
  - schema declaration style in `src/common/schemas.py`
  - transformation function signatures in `src/common/transformations.py`
  - `foreachBatch` body patterns in `src/streaming/stream_processor.py`
  - JDBC write patterns
  - dashboard panel JSON shape in `grafana/provisioning/dashboards/`
- Document anti-patterns: anything that imports `pyspark` from `src/common/`, anything
  that hardcodes a broker address, anything that bypasses the schema in `schemas.py`.
- **Read CLAUDE.md and DECISIONS.md.** Most "obvious improvements" have already been
  considered and rejected for documented reasons.

**3. Dependency Analysis**

- Are any new libraries needed? If yes, which version and why?
- Does the slice touch the Spark / Iceberg / Hadoop version triangle? If yes, treat
  as HIGH risk and put extra slack in the execution plan.
- Check `docker/spark/Dockerfile` for the exact pinned versions before assuming
  compatibility.

**4. Testing Patterns**

- Identify which pure functions in this slice can be unit-tested without Spark.
- Decide whether the slice warrants extending the integration test or not. The bar
  is high — the project budgets for a small number of integration tests. Adding one
  needs a `DECISIONS.md` entry.

**5. Integration Points**

- Schemas: does the event schema change?
- Lakehouse: does the table schema change? Is partitioning affected?
- Serving DB: does any serving table need a new column? Does `sql/init.sql` need
  updating?
- Dashboard: does any panel need updating, or do we add a new one?
- Generator: does the producer need to emit a new field or new traffic pattern?

**Clarify Ambiguities:**

- If requirements are unclear, ASK the user before continuing. Do not guess on schemas.

### Phase 3: External Research & Documentation

Use targeted research, not a doc dump. For Spark/Iceberg/Kafka the canonical sources
are:

- Apache Spark Structured Streaming Programming Guide (with exact section anchor)
- Apache Iceberg "Spark Writes" and "Spark Configuration" pages (with exact section
  anchor)
- Kafka client library docs for the language we are using
- The exact PostgreSQL JDBC sink behavior for the write mode being chosen

**Compile Research References:**

```markdown
## Relevant Documentation

- [Spark Structured Streaming: foreachBatch](https://spark.apache.org/docs/latest/structured-streaming-programming-guide.html#using-foreach-and-foreachbatch)
  - Section: Using foreachBatch
  - Why: Confirms the idempotency contract for the serving sink
- [Iceberg: Spark Writes](https://iceberg.apache.org/docs/latest/spark-writes/)
  - Section: Writing with DataFrames
  - Why: Confirms append vs overwrite semantics for the lakehouse table
```

### Phase 4: Deep Strategic Thinking

Think harder about:

- **Data contract impact**: does this slice break any existing consumer of the schema?
- **Backfill story**: if the schema changes, what happens to data already in the
  lakehouse?
- **Idempotency**: if Spark restarts mid-batch, does the slice still produce a
  correct result on replay?
- **Watermark / late data**: does this slice depend on event-time ordering?
- **Performance implications**: does this slice change the partitioning or shuffle
  profile?
- **Observability**: how will we know it is working in production?

### Phase 5: Plan Structure

**Filename**: `.agents/plans/{kebab-case-slice-name}.md`

Examples: `add-device-type-breakdown.md`, `add-recent-errors-table.md`,
`switch-postgres-sink-to-upsert.md`

**Template (fill it in completely):**

```markdown
# Slice: <slice-name>

The following plan should be complete, but it is important to validate documentation
and codebase patterns before implementing.

Pay special attention to: schema field names, transformation function signatures, and
the pinned versions in `docker/spark/Dockerfile`.

## Slice Description

<Detailed description of the slice and its end-to-end value>

## User Story

As a <user type>
I want to <action>
So that <benefit>

## Problem Statement

<What is currently missing or broken>

## Solution Statement

<The proposed slice, end-to-end>

## Slice Metadata

**Slice Type**: [New Pipeline Capability / Schema Evolution / Sink Addition /
Performance Optimization / Observability Improvement / Bug Fix]
**Estimated Complexity**: [Low / Medium / High]
**Components Touched**: [generator, schemas, transformations, streaming job,
lakehouse, serving DB, dashboard — list only what applies]
**Touches version triangle**: [Yes / No] — if Yes, double the slack budget

---

## DATA CONTRACT IMPACT

### Event Schema (`src/common/schemas.py`)
<Fields added / removed / changed, with types. "No change" is a valid answer.>

### Lakehouse Table
<Columns added / removed / changed. Partition strategy impact. Backfill story.>

### Serving Tables (`sql/init.sql`)
<For each table: columns added / removed / changed, refresh strategy impact.>

### Generator (`src/generator/producer.py`)
<New fields to emit, new traffic patterns to simulate.>

### Dashboard
<Panels added / modified / removed.>

---

## DECISIONS TO LOG

For each non-obvious trade-off in this slice, an entry will be written to
`DECISIONS.md` during /execute. List them here so the execute step does not miss them.

- **Decision**: <one-line summary>
  - **Context**: <why this came up>
  - **Options considered**: <alternatives>
  - **Chosen**: <the choice>
  - **Rationale**: <why>

---

## CONTEXT REFERENCES

### Relevant Codebase Files — READ BEFORE IMPLEMENTING

- `src/common/schemas.py` (lines X-Y) — pattern for declaring StructType
- `src/common/transformations.py` (lines X-Y) — pure function pattern to mirror
- `src/streaming/stream_processor.py` (lines X-Y) — foreachBatch body pattern
- `tests/unit/test_transformations.py` (lines X-Y) — unit test pattern
- `DECISIONS.md` — relevant prior decisions to respect

### New Files to Create

<Path + one-line purpose for each>

### Relevant Documentation — READ BEFORE IMPLEMENTING

<URLs with section anchors and a "Why" line for each>

### Patterns to Follow

**Naming**: snake_case for Python, lowercase for lakehouse identifiers, snake_case
for serving DB tables.

**Pure-vs-Spark-aware split**: anything that doesn't need a SparkSession lives in
`src/common/transformations.py` and is unit-tested. Anything that needs a SparkSession
lives in `src/streaming/`.

**Schema declaration**: explicit `StructType`, no inference, no `from_json` without a
schema argument.

**foreachBatch**: idempotent, structured logging once per batch, no per-row Python.

**Config**: every new config value reads from an env var via `src/common/config.py`.

---

## IMPLEMENTATION PLAN

### Phase 1: Schemas & Pure Functions

<What schema and transformation work happens first. This phase has zero Spark
dependencies and gets a fast unit-test feedback loop.>

### Phase 2: Streaming Job

<Wire the pure functions into the streaming job, update the lakehouse writer if
needed, update the foreachBatch body for the serving sink.>

### Phase 3: Serving DB & Generator

<Update sql/init.sql, update the producer if it needs to emit new fields or new
traffic.>

### Phase 4: Dashboard

<Update or add the dashboard panel JSON.>

### Phase 5: Tests & Validation

<Unit tests on every new pure function. Decide whether the integration test needs
to change — default is NO; changing it requires justification.>

---

## STEP-BY-STEP TASKS

Execute every task in order, top to bottom. Each task is atomic and validates
immediately.

Action keywords: **CREATE**, **UPDATE**, **ADD**, **REMOVE**, **REFACTOR**, **MIRROR**.

### {ACTION} {target_file}

- **IMPLEMENT**: <specific change>
- **PATTERN**: <file:line reference to mirror>
- **IMPORTS**: <required imports>
- **GOTCHA**: <known issue — JAR version, encoding, off-by-one, etc.>
- **VALIDATE**: `<executable command>`

<Continue in dependency order…>

---

## TESTING STRATEGY

### Unit Tests
<Which pure functions, which edge cases, which fixtures.>

### Integration Test
<Default: no change. If changing it, justify here AND log a `DECISIONS.md` entry.>

### Manual Smoke Test
<docker compose up, generator running, check dashboard panel, check serving DB row
counts, check lakehouse snapshot count.>

### Edge Cases
<Late events, malformed events, schema-incompatible events, generator at 100x rate,
Spark restart mid-batch.>

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
docker compose up -d
sleep 30
docker compose ps
docker compose exec postgres pg_isready
curl -fsS http://localhost:3000/api/health
curl -fsS http://localhost:4040 > /dev/null
```

### Level 5: Slice-Specific Manual Validation
<Open the dashboard URL, point at the new panel, confirm it shows the expected data.>

---

## ACCEPTANCE CRITERIA

- [ ] Slice works end-to-end on a fresh `docker compose up`
- [ ] All validation commands pass with zero errors and zero linter warnings
- [ ] Unit tests cover every new pure function, including edge cases
- [ ] Integration test still passes (or has been updated with a `DECISIONS.md` entry)
- [ ] Code follows the pure-vs-Spark-aware split
- [ ] Every non-obvious trade-off has a `DECISIONS.md` entry in the same commit
- [ ] No regressions in existing serving tables, dashboard panels, or lakehouse schema
- [ ] No new floating-version dependencies

---

## COMPLETION CHECKLIST

- [ ] All tasks completed in order
- [ ] Each task validation passed before moving to the next
- [ ] Full validation suite green
- [ ] Manual smoke test confirmed in the browser
- [ ] `DECISIONS.md` updated where required
- [ ] Slice plan annotated as complete in `.agents/plans/`

---

## NOTES

<Trade-offs, alternatives considered, follow-up ideas.>
```

## Quality Criteria

### Context Completeness ✓
- All relevant patterns identified with file:line references
- Spark/Iceberg/Kafka docs linked with section anchors
- The Data Contract Impact section is filled in completely (no "TBD")
- The Decisions to Log section exists, even if empty

### Implementation Ready ✓
- Tasks ordered by dependency, top-to-bottom
- Each task is atomic and independently validatable
- Validation commands are non-interactive and copy-pasteable

### Pattern Consistency ✓
- Pure-vs-Spark-aware split respected
- Schemas declared explicitly
- No new hardcoded URLs or addresses
- New config goes through `src/common/config.py`

### Information Density ✓
- No generic references — every reference is specific
- No "TBD" or "investigate later" in the implementation phase
- Each task uses information-dense action keywords

## Success Metrics

**One-Pass Implementation**: Execution agent can complete the slice without additional
research or clarification.

**Validation Complete**: Every task has at least one working, non-interactive
validation command.

**Context Rich**: The plan passes the "No Prior Knowledge Test" — someone unfamiliar
with the codebase can implement the slice using only the plan.

**Confidence Score**: #/10 that execution will succeed on first attempt. If <7, ask
the user before invoking /execute.

## Report

After creating the plan, provide:

- One-paragraph summary of the slice and approach
- Full path to the plan file
- Complexity assessment
- Whether it touches the Spark / Iceberg / Hadoop version triangle
- Decisions that will need to be logged
- Confidence score for one-pass success
