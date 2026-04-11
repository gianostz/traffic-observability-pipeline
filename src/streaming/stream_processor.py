"""Spark Structured Streaming job: Kafka source -> parse -> enrich -> Iceberg sink.

Entrypoint for the streaming container. Reads config from environment
variables via src.common.config, parses JSON events with an explicit
StructType, broadcast-joins against the server registry, and appends
enriched events to an Iceberg table via foreachBatch.
"""
from __future__ import annotations

import logging
import time

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql.functions import (
    broadcast,
    col,
    current_timestamp,
    from_json,
    to_timestamp,
)
from pyspark.sql.types import LongType

from src.common.config import load_kafka_config, load_spark_config
from src.streaming.iceberg_sink import append_to_iceberg, ensure_table
from src.streaming.schemas_spark import build_event_struct

logger = logging.getLogger(__name__)


def _build_spark_session(
    catalog: str, warehouse: str, driver_mem: str, executor_mem: str,
) -> SparkSession:
    """Build a SparkSession with Iceberg catalog configuration."""
    return (
        SparkSession.builder
        .appName("traffic-observability-pipeline")
        .config(f"spark.sql.catalog.{catalog}", "org.apache.iceberg.spark.SparkCatalog")
        .config(f"spark.sql.catalog.{catalog}.type", "hadoop")
        .config(f"spark.sql.catalog.{catalog}.warehouse", warehouse)
        .config(
            "spark.sql.extensions",
            "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
        )
        .config("spark.driver.memory", driver_mem)
        .config("spark.executor.memory", executor_mem)
        .getOrCreate()
    )


def main() -> None:
    """Entrypoint: load config, build SparkSession, run streaming pipeline."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    kafka_cfg = load_kafka_config()
    spark_cfg = load_spark_config()

    spark = _build_spark_session(
        catalog=spark_cfg.iceberg_catalog,
        warehouse=spark_cfg.iceberg_warehouse_dir,
        driver_mem=spark_cfg.driver_memory,
        executor_mem=spark_cfg.executor_memory,
    )
    logger.info("event=spark_session_created catalog=%s warehouse=%s",
                spark_cfg.iceberg_catalog, spark_cfg.iceberg_warehouse_dir)

    # Load server registry for broadcast join
    from src.common.config import load_generator_config  # noqa: PLC0415
    gen_cfg = load_generator_config()
    registry_df = spark.read.csv(gen_cfg.server_registry_path, header=True, inferSchema=False)
    logger.info("event=registry_loaded rows=%d path=%s",
                registry_df.count(), gen_cfg.server_registry_path)

    event_struct = build_event_struct()

    # Ensure Iceberg table exists
    ensure_table(spark, spark_cfg.iceberg_catalog, spark_cfg.iceberg_table)

    # Kafka source
    kafka_df = (
        spark.readStream
        .format("kafka")
        .option("kafka.bootstrap.servers", kafka_cfg.bootstrap_servers)
        .option("subscribe", kafka_cfg.topic)
        .option("startingOffsets", "earliest")
        .load()
    )

    # Parse: cast value to string, apply from_json with explicit schema
    parsed = (
        kafka_df
        .selectExpr("CAST(value AS STRING) as json_str")
        .select(from_json(col("json_str"), event_struct).alias("event"))
        .select("event.*")
        .filter(col("event_id").isNotNull())
        .filter(col("event_ts").isNotNull())
        .withColumn("event_ts", to_timestamp(col("event_ts"), "yyyy-MM-dd'T'HH:mm:ss.SSS'Z'"))
        .withColumn("bytes_sent", col("bytes_sent").cast(LongType()))
    )

    # Capture broadcast registry in closure for foreachBatch
    broadcast_registry = broadcast(registry_df)
    catalog = spark_cfg.iceberg_catalog
    table = spark_cfg.iceberg_table

    def process_batch(batch_df: DataFrame, batch_id: int) -> None:
        """Process a single micro-batch: enrich via broadcast join, append to Iceberg."""
        if batch_df.isEmpty():
            logger.info("event=batch_empty batch_id=%d", batch_id)
            return

        start = time.time()
        parsed_count = batch_df.count()

        # Broadcast join enrichment (inner join drops unknown server_ids)
        enriched = (
            batch_df
            .join(broadcast_registry, on="server_id", how="inner")
            .withColumn("ingest_ts", current_timestamp())
            .select(
                "event_id", "event_ts", "server_id", "method", "path",
                "status_code", "bytes_sent", "duration_ms", "remote_ip", "user_agent",
                "region", "datacenter", "service", "ingest_ts",
            )
        )

        enriched_count = enriched.count()
        unenriched_dropped = parsed_count - enriched_count

        # Append to Iceberg
        iceberg_rows = append_to_iceberg(enriched, catalog, table)

        elapsed = time.time() - start
        logger.info(
            "event=batch_complete batch_id=%d input_rows=%d iceberg_rows=%d "
            "unenriched_dropped=%d elapsed_sec=%.2f",
            batch_id, parsed_count, iceberg_rows, unenriched_dropped, elapsed,
        )

    # Start streaming query
    query = (
        parsed.writeStream
        .foreachBatch(process_batch)
        .option("checkpointLocation", spark_cfg.checkpoint_dir)
        .start()
    )

    logger.info("event=streaming_started topic=%s checkpoint=%s",
                kafka_cfg.topic, spark_cfg.checkpoint_dir)
    query.awaitTermination()


if __name__ == "__main__":
    main()
