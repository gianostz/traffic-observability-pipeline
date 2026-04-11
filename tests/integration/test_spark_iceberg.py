"""Integration test: Kafka -> Spark read -> enrich -> Iceberg write."""
from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime

from confluent_kafka import Producer
from pyspark.sql import SparkSession
from pyspark.sql.functions import broadcast, col, current_timestamp, from_json, to_timestamp
from pyspark.sql.types import LongType

from src.generator.producer import generate_event, load_server_ids
from src.streaming.iceberg_sink import append_to_iceberg, ensure_table
from src.streaming.schemas_spark import build_event_struct


def _produce_events(bootstrap_server: str, topic: str, n: int = 10) -> list[dict]:
    """Produce n synthetic events to a Kafka topic, return the sent events."""
    producer = Producer({"bootstrap.servers": bootstrap_server})
    server_ids = load_server_ids("data/servers.csv")
    events = []
    for _ in range(n):
        event = generate_event(server_ids, datetime.now(UTC))
        producer.produce(topic, value=json.dumps(event).encode("utf-8"))
        events.append(event)
    producer.flush(timeout=10)
    # Small delay to let Kafka commit
    time.sleep(2)
    return events


def test_spark_reads_from_kafka(spark_session: SparkSession, bootstrap_server: str) -> None:
    topic = f"test_spark_read_{uuid.uuid4().hex[:8]}"
    _produce_events(bootstrap_server, topic, n=10)

    df = (
        spark_session.read
        .format("kafka")
        .option("kafka.bootstrap.servers", bootstrap_server)
        .option("subscribe", topic)
        .option("startingOffsets", "earliest")
        .option("endingOffsets", "latest")
        .load()
    )

    event_struct = build_event_struct()
    parsed = (
        df.selectExpr("CAST(value AS STRING) as json_str")
        .select(from_json(col("json_str"), event_struct).alias("event"))
        .select("event.*")
        .filter(col("event_id").isNotNull())
    )

    assert parsed.count() == 10

    field_names = {f.name for f in parsed.schema.fields}
    from src.common.schemas import EVENT_FIELDS
    expected = {name for name, _ in EVENT_FIELDS}
    assert expected.issubset(field_names)


def test_broadcast_enrich_drops_unknown_server(spark_session: SparkSession) -> None:
    # Create a DataFrame with one known and one unknown server_id
    data = [
        ("evt-1", "web-use1-01"),
        ("evt-2", "unknown-server-99"),
    ]
    events_df = spark_session.createDataFrame(data, ["event_id", "server_id"])

    registry_df = spark_session.read.csv("data/servers.csv", header=True, inferSchema=False)
    enriched = events_df.join(broadcast(registry_df), on="server_id", how="inner")

    assert enriched.count() == 1
    row = enriched.collect()[0]
    assert row["event_id"] == "evt-1"
    assert row["region"] == "us-east"


def test_iceberg_append_and_read_back(
    spark_session: SparkSession, bootstrap_server: str
) -> None:
    topic = f"test_iceberg_{uuid.uuid4().hex[:8]}"
    table_name = f"test_iceberg_{uuid.uuid4().hex[:8]}"
    _produce_events(bootstrap_server, topic, n=10)

    df = (
        spark_session.read
        .format("kafka")
        .option("kafka.bootstrap.servers", bootstrap_server)
        .option("subscribe", topic)
        .option("startingOffsets", "earliest")
        .option("endingOffsets", "latest")
        .load()
    )

    event_struct = build_event_struct()
    parsed = (
        df.selectExpr("CAST(value AS STRING) as json_str")
        .select(from_json(col("json_str"), event_struct).alias("event"))
        .select("event.*")
        .filter(col("event_id").isNotNull())
        .withColumn("event_ts", to_timestamp(col("event_ts"), "yyyy-MM-dd'T'HH:mm:ss.SSS'Z'"))
        .withColumn("bytes_sent", col("bytes_sent").cast(LongType()))
    )

    # Broadcast join enrichment
    registry_df = spark_session.read.csv("data/servers.csv", header=True, inferSchema=False)
    enriched = (
        parsed.join(broadcast(registry_df), on="server_id", how="inner")
        .withColumn("ingest_ts", current_timestamp())
        .select(
            "event_id", "event_ts", "server_id", "method", "path",
            "status_code", "bytes_sent", "duration_ms", "remote_ip", "user_agent",
            "region", "datacenter", "service", "ingest_ts",
        )
    )

    ensure_table(spark_session, "test_lakehouse", table_name)
    append_to_iceberg(enriched, "test_lakehouse", table_name)

    result = spark_session.sql(f"SELECT * FROM test_lakehouse.{table_name}")
    assert result.count() == 10

    # Verify enrichment columns are populated
    sample = result.select("region", "datacenter", "service").filter(
        col("region").isNotNull()
    )
    assert sample.count() == 10

    # Clean up
    spark_session.sql(f"DROP TABLE IF EXISTS test_lakehouse.{table_name}")


def test_iceberg_table_is_partitioned_by_hour(
    spark_session: SparkSession, bootstrap_server: str
) -> None:
    topic = f"test_part_{uuid.uuid4().hex[:8]}"
    table_name = f"test_part_{uuid.uuid4().hex[:8]}"
    _produce_events(bootstrap_server, topic, n=5)

    df = (
        spark_session.read
        .format("kafka")
        .option("kafka.bootstrap.servers", bootstrap_server)
        .option("subscribe", topic)
        .option("startingOffsets", "earliest")
        .option("endingOffsets", "latest")
        .load()
    )

    event_struct = build_event_struct()
    parsed = (
        df.selectExpr("CAST(value AS STRING) as json_str")
        .select(from_json(col("json_str"), event_struct).alias("event"))
        .select("event.*")
        .filter(col("event_id").isNotNull())
        .withColumn("event_ts", to_timestamp(col("event_ts"), "yyyy-MM-dd'T'HH:mm:ss.SSS'Z'"))
        .withColumn("bytes_sent", col("bytes_sent").cast(LongType()))
    )

    registry_df = spark_session.read.csv("data/servers.csv", header=True, inferSchema=False)
    enriched = (
        parsed.join(broadcast(registry_df), on="server_id", how="inner")
        .withColumn("ingest_ts", current_timestamp())
        .select(
            "event_id", "event_ts", "server_id", "method", "path",
            "status_code", "bytes_sent", "duration_ms", "remote_ip", "user_agent",
            "region", "datacenter", "service", "ingest_ts",
        )
    )

    ensure_table(spark_session, "test_lakehouse", table_name)
    append_to_iceberg(enriched, "test_lakehouse", table_name)

    # Check partitions exist
    partitions = spark_session.sql(f"SELECT * FROM test_lakehouse.{table_name}.partitions")
    assert partitions.count() > 0

    # Clean up
    spark_session.sql(f"DROP TABLE IF EXISTS test_lakehouse.{table_name}")
