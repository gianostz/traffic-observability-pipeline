---
description: Create a Product Requirements Document for a streaming-data project
argument-hint: [output-filename]
---

# Create PRD: Generate Product Requirements Document

## Overview

Generate a comprehensive PRD for a streaming / lakehouse / data-engineering project,
based on the current conversation context. The structure below is opinionated for data
pipelines: data contracts, semantics, and trade-offs are first-class sections, not
afterthoughts.

If you are tempted to drop one of the data-specific sections ("we don't need
partitioning strategy yet"), do not — leave it in and write *"deferred — see
DECISIONS.md"*. For a data project, the things you decided NOT to do are as important
as the things you did.

## Output File

Write the PRD to: `$ARGUMENTS` (default: `.claude/PRD.md`)

## PRD Structure

### Required Sections

**1. Executive Summary**
- Two or three paragraphs.
- What the pipeline ingests, what it produces, who consumes the output.
- The MVP goal in one sentence.
- The single most important constraint (time budget, throughput target, correctness
  guarantee, etc.).

**2. Mission & Principles**
- Mission statement.
- 3–5 core principles. For a data project these usually include things like:
  *correctness over throughput*, *idempotent sinks*, *explicit schemas*,
  *fail loud, never silent*, *constraints are documented, not hidden*.

**3. Scenario & Domain**
- The business / operational scenario the data describes.
- Why this scenario was chosen (what it lets us demonstrate or validate).
- Universally-understood domain summary so the reader does not need prior context.

**4. Scope & Trade-offs**
- The most important section in a data PRD. List every non-obvious trade-off
  deliberately made and the reasoning.
- Examples: single Spark application vs split jobs, one Iceberg table vs many,
  truncate-and-reload vs upsert, PySpark vs Scala, broadcast join vs stream-stream
  join, scope of integration testing.
- Each trade-off references the corresponding entry in `DECISIONS.md` (or notes it as
  "to be added").

**5. Data Model**
- **Event schema(s)**: every field with type, description, example.
- **Reference data**: schemas, source, refresh strategy.
- **Enrichment fields**: every derived field with the rule that derives it.
- **Lakehouse schema**: table name, columns, partition strategy, sort order.
- **Serving schema**: each serving table with columns, refresh strategy, owner sink.

This section is the data contract. If two readers disagree on any field, the PRD has
failed its job.

**6. Architecture**
- ASCII diagram of the data flow, source → sinks.
- One paragraph per component covering: responsibility, technology, scaling assumption.
- Explicit statement of which component owns which sink.

**7. Semantics & Guarantees**
- Delivery semantics for each source (at-least-once / exactly-once / at-most-once).
- Watermark / late-data policy.
- Idempotency strategy for each sink, with the exact mechanism (Iceberg snapshot
  isolation, JDBC truncate-and-reload, MERGE on a key, etc.).
- Failure-recovery story: what happens on Spark restart, on Kafka rebalance, on
  schema drift, on a malformed event.
- Backpressure story: what happens when the producer outpaces the consumer.

**8. Technology Stack**
- Every component with a **pinned version**. Floating versions are a red flag in a
  Spark project and must be justified.
- Why each technology was chosen over the alternative the reader is most likely to
  ask about.

**9. Functional Requirements**
- Numbered (FR-1, FR-2, …) and grouped by component (generator, streaming job,
  serving DB, lakehouse, dashboard).
- Each requirement is testable. "Must be fast" is not a requirement; "must process
  10 events/sec sustained on a single Spark local-mode JVM" is.

**10. Non-Functional Requirements**
- Containerization (NFR-1.x): no manual setup steps, health checks, init scripts.
- Testing (NFR-2.x): unit vs integration split, what is in scope.
- Code quality & docs (NFR-3.x): structure, type hints, where decisions live.
- Observability (NFR-4.x): logs, metrics, dashboards, Spark UI.

**11. Project Structure**
- Directory tree with one-line purpose for each top-level directory.
- Highlight the pure-vs-Spark-aware split if it exists in the project.

**12. Execution Plan**
- Time-boxed table: block, task, hours.
- Where the slack is, and which task it is reserved for. (For Spark projects, slack
  almost always belongs to classpath / JAR version issues.)

**13. Success Criteria**
- A short, testable checklist. "`docker compose up` brings the stack up with no manual
  steps." "All unit and integration tests pass via `pytest`."

**14. Risks & Mitigations**
- 3–5 specific risks with concrete mitigations.
- For a Spark project, at least one risk should be about the version triangle.

**15. Out of Scope**
- Explicit list of what is NOT in this build, with the reason and the production
  alternative.
- This section is typically as long as the in-scope sections — it shows the difference
  between the current build and the production target.

**16. Future Work**
- Prioritized roadmap from current state to production.
- Dead-letter topics, MERGE-based serving sinks, schema registry, exactly-once via
  Kafka transactions, REST catalog, multi-tenancy, etc.

**17. Appendix** (if applicable)
- Related documents, links to external references, source of any reference data.

## Instructions

### 1. Extract Requirements

- Review the entire conversation history.
- Read any existing project brief.
- Identify explicit requirements and implicit constraints.

### 2. Synthesize

- Organize requirements into the sections above.
- Where details are missing, make a reasonable assumption AND flag it in §15 (Out of
  Scope) or §14 (Risks).
- Maintain one consistent set of names across schemas, tables, and code paths.

### 3. Write

- Clear, professional, declarative.
- Tables for schemas, FR/NFR lists, execution plans.
- ASCII diagrams for data flow.
- ✅ for in-scope, ❌ for out-of-scope.
- No marketing language. No "leverage", no "robust", no "scalable" without a number
  attached.

### 4. Quality Checks

- ✅ Every schema field has type + description.
- ✅ Every functional requirement is testable.
- ✅ Every sink has an idempotency story.
- ✅ Every non-obvious choice has a reason or a `DECISIONS.md` reference.
- ✅ The "Out of Scope" section is at least as detailed as the "In Scope" sections.
- ✅ The Execution Plan accounts for slack on the riskiest task.
- ✅ The PRD reads end-to-end without contradicting itself.

## Style Guidelines

- **Tone**: declarative, specific, opinionated. No hedging.
- **Format**: heavy use of markdown tables, ASCII diagrams, numbered FR/NFR.
- **Specificity**: concrete numbers over adjectives. "5 minute tumbling window" not
  "frequent updates". "10 events/sec default" not "configurable throughput".

## Output Confirmation

After creating the PRD:

1. Confirm the file path.
2. List every assumption made due to missing information.
3. List every section that is intentionally short and why.
4. Suggest the first 2–3 plans to feed into `/plan-feature`.
