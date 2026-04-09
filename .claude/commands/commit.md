# Commit

Create an atomic commit for the current uncommitted changes.

## Steps

1. Inspect what is uncommitted:

```bash
git status
git diff HEAD
git status --porcelain
```

2. Decide whether the changes are atomic. If they span more than one logical concern,
   STOP and split into multiple commits — one logical change per commit. The point of
   atomic commits is that any single commit can be reverted without taking unrelated
   work with it.

3. If a non-obvious trade-off was made in this work, confirm `DECISIONS.md` has been
   updated **in the same commit**, not as a follow-up. The rule is: a `DECISIONS.md`
   entry and the code that implements its decision live in the same commit, always.
   If you find yourself committing code without the decision entry, stop and add it.

4. Stage and commit:

```bash
git add -A
git commit -m "<type>(<scope>): <one-line summary>

<optional body explaining the WHY, not the WHAT — the diff already shows the what>
"
```

## Conventional Commit Tags

Use one of:

| Tag        | When                                                                  |
| ---------- | --------------------------------------------------------------------- |
| `feat`     | New pipeline capability, new sink, new dashboard panel                |
| `fix`      | Bug fix in transformation, sink, generator, or stack config           |
| `refactor` | Code restructure with no behavior change (e.g. extracting a pure fn)  |
| `perf`     | Performance improvement (Spark tuning, partition strategy, etc.)      |
| `test`     | Adding or fixing tests, no production code change                     |
| `docs`     | README, CLAUDE.md, DECISIONS.md, or PRD updates only                  |
| `chore`    | Dependency bumps, Docker tweaks, CI plumbing                          |
| `build`    | Changes to Dockerfiles, docker-compose, or version pins               |

For Spark version bumps, JAR changes, or anything touching the Spark / Iceberg /
Hadoop version triangle, use `build` and write the commit body as a mini decision
entry — linking to the corresponding `DECISIONS.md` section.

## Scope examples

- `feat(streaming): add device_type breakdown to endpoint_stats`
- `fix(producer): correct status_code distribution to match PRD`
- `refactor(transformations): extract latency bucketing into pure function`
- `perf(streaming): broadcast server_registry instead of stream-stream join`
- `build(spark): pin Iceberg runtime to 1.4.3 (matches Spark 3.5)`
- `docs(decisions): log truncate-and-reload vs upsert trade-off`
