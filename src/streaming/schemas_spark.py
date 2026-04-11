"""PySpark StructType builders mapping pure-Python schema to Spark types.

Reads EVENT_FIELDS from src.common.schemas and maps type labels to PySpark
DataTypes. Lives in src/streaming/ per D-015 (no pyspark under src/common/).
"""
from __future__ import annotations

from pyspark.sql.types import (
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

from src.common.schemas import EVENT_FIELDS

_TYPE_MAP: dict[str, type] = {
    "string": StringType,
    "int": IntegerType,
}

# bytes_sent is "int" in schemas.py but PRD §5.4 says bigint -> LongType
_OVERRIDES: dict[str, type] = {
    "bytes_sent": LongType,
}


def build_event_struct() -> StructType:
    """Build the StructType for raw Kafka event payloads."""
    fields = []
    for name, type_label in EVENT_FIELDS:
        if name in _OVERRIDES:
            spark_type = _OVERRIDES[name]()
        else:
            spark_type = _TYPE_MAP[type_label]()
        fields.append(StructField(name, spark_type, nullable=True))
    return StructType(fields)


def build_enriched_struct() -> StructType:
    """Build the StructType for enriched events (event + registry columns + ingest_ts)."""
    fields = list(build_event_struct().fields)
    fields.append(StructField("region", StringType(), nullable=True))
    fields.append(StructField("datacenter", StringType(), nullable=True))
    fields.append(StructField("service", StringType(), nullable=True))
    fields.append(StructField("ingest_ts", TimestampType(), nullable=True))
    return StructType(fields)
