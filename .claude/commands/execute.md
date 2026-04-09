---
description: Execute a vertical-slice plan against the streaming pipeline
argument-hint: [path-to-plan]
---

# Execute: Implement from a Slice Plan

## Plan to Execute

Read plan file: `$ARGUMENTS`

## Execution Instructions

### 1. Read and Understand

- Read the ENTIRE plan carefully, including the "Notes" section.
- Read `CLAUDE.md` and `DECISIONS.md` before touching code.
- Understand the data contract impact: which schemas, tables, and panels change.
- Note the validation commands you will run at the end.
- Note the entries in "Decisions to Log" — they MUST be written to `DECISIONS.md` in
  the same commit as the implementation, not as a follow-up.

If anything in the plan looks wrong or has gone stale relative to the codebase, STOP
and flag it before making changes. Do not silently deviate.

### 2. Execute Tasks in Order

For EACH task in "Step-by-Step Tasks":

#### a. Navigate to the task
- Identify the file and the action keyword (CREATE / UPDATE / ADD / REMOVE / REFACTOR /
  MIRROR).
- Read existing related files before modifying — especially the file referenced in the
  task's PATTERN line.

#### b. Implement the task
- Follow the specifications exactly. Use the named pattern; do not invent new ones.
- Respect the pure-vs-Spark-aware split: anything that doesn't need a `SparkSession`
  goes in `src/common/transformations.py` and stays free of `pyspark` imports.
- Add type hints. Add a one-line docstring on every new public function.
- Add structured logging on the streaming-job side: one log line per micro-batch with
  batch id, input row count, output row count per sink, processing time.
- Read config from environment variables via `src/common/config.py`. No hardcoded
  broker addresses, paths, or DB URLs.

#### c. Verify as you go
- After each file change: imports correct, types resolved, no leftover stubs.
- After every transformation change: rerun the relevant unit test immediately.
  `uv run pytest tests/unit/test_transformations.py::test_<n> -q`.

### 3. Implement Tests

After completing implementation tasks:

- Write a unit test for every new pure function.
- Cover the edge cases listed in the plan's "Edge Cases" section.
- Update the integration test ONLY if the plan explicitly says so AND there is a
  matching `DECISIONS.md` entry.

### 4. Update DECISIONS.md

For each entry in the plan's "Decisions to Log" section, append an entry to
`DECISIONS.md` in this format:

```markdown
## YYYY-MM-DD — <decision title>

**Context**: <why this came up>

**Options considered**:
- <option A>
- <option B>

**Chosen**: <the choice>

**Rationale**: <why>

**Trade-offs accepted**: <what we are giving up>

**Revisit when**: <the condition under which we should reconsider>
```

If `DECISIONS.md` does not exist yet, create it with a one-line header at the top:

```markdown
# Design Decisions

A running log of non-obvious trade-offs. Each entry documents the reasoning behind
a choice so it can be revisited when the context changes.
```

### 5. Run Validation Commands

Execute every validation command in the plan, in order. Do not skip levels.

```bash
# Level 1: Syntax & Style
uv run ruff check src tests
uv run mypy src

# Level 2: Unit Tests
uv run pytest tests/unit -q

# Level 3: Integration Tests
uv run pytest tests/integration -q

# Level 4: Stack Smoke Test
docker compose up -d
sleep 30
docker compose ps
docker compose exec postgres pg_isready
curl -fsS http://localhost:3000/api/health
curl -fsS http://localhost:4040 > /dev/null

# Level 5: Slice-specific manual validation (per the plan)
```

If a command fails:
- Read the error carefully — Spark stack traces are long, but the actual cause is
  almost always in the first 5 frames or the very last.
- Fix the issue.
- Re-run the failing command.
- Re-run any earlier command that might be affected by the fix.
- Continue only when everything is green.

If you find yourself re-running the same fix-loop more than 3 times on the same error,
STOP and report — you are probably fighting a version-skew issue and a human should
look at it.

### 6. Final Verification

Before declaring the slice complete:

- ✅ All tasks from the plan completed in order
- ✅ All tests created and passing
- ✅ All validation commands pass at every level
- ✅ Code follows the pure-vs-Spark-aware split
- ✅ `DECISIONS.md` updated for every entry in the plan's Decisions section
- ✅ No new hardcoded broker addresses, DB URLs, or file paths in `src/`
- ✅ No new floating-version dependencies in `requirements.txt` or
  `docker/spark/Dockerfile`
- ✅ Manual smoke test confirms the slice works end-to-end in the browser

## Output Report

Provide a structured summary:

### Completed Tasks
- List of every task completed
- Files created (with paths)
- Files modified (with paths)

### Data Contract Changes
- Schemas changed (which fields, which types)
- Lakehouse table changes
- Serving table changes
- Generator changes
- Dashboard panels added or modified

### Tests
- New test files
- New test cases (with names)
- Pass/fail status for each level

### Decisions Logged
- Entries appended to `DECISIONS.md`, with their titles

### Validation Results
```bash
# Verbatim output of each level — abbreviated to the first error line if there are
# failures, otherwise just the summary line.
```

### Manual Smoke Test
- Steps performed
- Row counts / observed dashboard state

### Ready for Commit
- Confirm all changes are complete
- Confirm all validations pass
- Suggest the commit message: type, scope, summary line
- Ready for `/commit`

## Notes

- If the plan has gone stale relative to the codebase, document the deviation in the
  output report. Do not silently rewrite the plan.
- If you encounter an issue not addressed in the plan, document it as a new entry in
  `.agents/plans/` for follow-up rather than scope-creeping the current slice.
- If a test fails for a reason that looks unrelated to the slice, do NOT delete the
  test or skip it — flag it.
- If you need to bump a Spark / Iceberg / Hadoop version, STOP. That requires its own
  plan with its own `DECISIONS.md` entry.
