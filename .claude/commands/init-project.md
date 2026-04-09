# Initialize Project

Bring the full streaming pipeline stack up locally. Per the project NFRs, this should
be a single `docker compose up -d` with no manual setup steps. The commands below are
sanity checks, not setup steps — if any of them fail, that is a bug and not a "you
forgot to do something" situation.

## 1. Create environment file (first time only)

```bash
cp .env.example .env
```

The defaults are wired for local development; you do not need to edit anything to get
a working stack.

## 2. Bring the stack up

```bash
docker compose up -d
```

This starts:
- `kafka` — KRaft single-node, with the event topic auto-created on startup
- `postgres` — initialized via the mounted `sql/init.sql`
- `spark` — runs the streaming job in local mode
- `grafana` — auto-provisions the Postgres datasource and the operations dashboard
- `generator` — starts emitting synthetic events at the configured rate

Wait ~30 seconds for everything to come up healthy:

```bash
docker compose ps
```

Every service should show `healthy`. If any are not, check its logs:

```bash
docker compose logs <service-name>
```

## 3. Validate the data flow

### Kafka — topic exists and has data

```bash
docker compose exec kafka kafka-topics.sh \
  --bootstrap-server localhost:9092 --list

docker compose exec kafka kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 \
  --topic <event-topic> \
  --from-beginning --max-messages 3
```

You should see sample JSON events.

### Spark — streaming job is running

```bash
# Spark UI
curl -fsS http://localhost:4040 > /dev/null && echo "Spark UI OK"

# Streaming job logs (look for "Batch X completed" lines)
docker compose logs spark | tail -20
```

### Postgres — serving tables are populated

```bash
docker compose exec postgres psql -U postgres -d <db-name> -c "
  SELECT table_name,
         (xpath('/row/cnt/text()',
            query_to_xml(format('select count(*) as cnt from %I', table_name),
                         false, true, '')))[1]::text::int AS row_count
  FROM information_schema.tables
  WHERE table_schema = 'public';
"
```

After ~1 minute, serving tables should have rows (the truncate-and-reload sink writes
a partial window every micro-batch).

### Lakehouse — table exists and is being appended to

```bash
docker compose exec spark python -c "
from pyspark.sql import SparkSession
spark = SparkSession.builder.getOrCreate()
spark.sql('SELECT count(*) AS row_count FROM <lakehouse>.<table>').show()
spark.sql('SELECT * FROM <lakehouse>.<table>.snapshots ORDER BY committed_at DESC LIMIT 5').show()
"
```

You should see a non-zero row count and at least one snapshot per micro-batch.

### Grafana — dashboard is live

```bash
curl -fsS http://localhost:3000/api/health
```

Then open http://localhost:3000 (default credentials in `.env.example`) and confirm
the dashboard shows live data on all panels.

## 4. Run the test suite

```bash
# Fast loop
uv run pytest tests/unit -q

# Integration tests (slow — boot Spark via testcontainers)
uv run pytest tests/integration -q
```

## Access Points

| What           | URL                       |
| -------------- | ------------------------- |
| Grafana        | http://localhost:3000     |
| Spark UI       | http://localhost:4040     |
| Postgres       | localhost:5432            |
| Kafka          | localhost:9092            |

## Cleanup

```bash
# Stop services, keep volumes (checkpoint, lakehouse warehouse, Postgres data preserved)
docker compose down

# Stop services AND wipe volumes (full reset)
docker compose down -v
```

## Troubleshooting

- **Spark container restarts in a loop**: almost always a JAR version mismatch in
  `docker/spark/Dockerfile`. Check the Spark / Iceberg / Hadoop version triangle in
  `DECISIONS.md`. Do not bump versions without a corresponding decision entry.
- **Generator runs but Postgres tables stay empty**: check Spark logs for the
  `foreachBatch` log line. If it is not appearing, the streaming job is consuming
  Kafka but failing to write to Postgres — check the JDBC URL in `.env`.
- **Grafana shows "no data"**: verify the datasource in
  `grafana/provisioning/datasources/postgres.yml` matches the Postgres credentials
  in `.env`, then restart the Grafana container.
- **`pytest tests/integration` hangs**: testcontainers is pulling the Spark image.
  First run can take several minutes. Subsequent runs are fast.
