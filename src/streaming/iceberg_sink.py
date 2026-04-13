"""Iceberg table creation and append-write functions.

Uses the DataFrameWriterV2 API (writeTo / append) per Iceberg Spark docs.
"""
from __future__ import annotations

import logging

from pyspark.sql import DataFrame, SparkSession

logger = logging.getLogger(__name__)


def ensure_table(spark: SparkSession, catalog: str, table: str) -> None:
    """Create the Iceberg fact table if it does not already exist."""
    fqn = f"{catalog}.{table}"
    spark.sql(f"""
        CREATE TABLE IF NOT EXISTS {fqn} (
            event_id STRING,
            event_ts TIMESTAMP,
            server_id STRING,
            method STRING,
            path STRING,
            status_code INT,
            bytes_sent BIGINT,
            duration_ms INT,
            remote_ip STRING,
            user_agent STRING,
            region STRING,
            datacenter STRING,
            service STRING,
            ingest_ts TIMESTAMP
        ) USING iceberg
        PARTITIONED BY (hours(event_ts))
    """)
    logger.info("event=iceberg_table_ensured table=%s", fqn)


def append_to_iceberg(df: DataFrame, catalog: str, table: str) -> int:
    """Append a DataFrame to the Iceberg table, return row count."""
    fqn = f"{catalog}.{table}"
    row_count = df.count()
    df.writeTo(fqn).append()
    return row_count
