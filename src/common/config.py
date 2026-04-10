"""Env-var-driven configuration for the Traffic Observability Pipeline.

Pure stdlib. No pyspark, no pydantic, no third-party imports. Every value
has a sensible local-laptop default so unit tests can import this module
without an env file present.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _get(name: str, default: str) -> str:
    """Return the env var ``name`` or ``default`` if it is unset."""
    return os.environ.get(name, default)


def _get_int(name: str, default: int) -> int:
    """Return the env var ``name`` coerced to int, or ``default`` if it is unset."""
    raw = os.environ.get(name)
    return int(raw) if raw is not None else default


@dataclass(frozen=True)
class KafkaConfig:
    """Kafka connection settings used by the producer and the Spark consumer."""

    bootstrap_servers: str
    topic: str


@dataclass(frozen=True)
class GeneratorConfig:
    """Synthetic event generator settings."""

    rate_per_sec: int
    jitter_seconds: int
    server_registry_path: str


@dataclass(frozen=True)
class SparkConfig:
    """Spark + Iceberg runtime settings for the streaming job."""

    driver_memory: str
    executor_memory: str
    checkpoint_dir: str
    iceberg_warehouse_dir: str
    iceberg_catalog: str
    iceberg_table: str
    watermark_duration: str


@dataclass(frozen=True)
class PostgresConfig:
    """Serving Postgres connection settings."""

    host: str
    port: int
    database: str
    user: str
    password: str
    schema: str

    @property
    def jdbc_url(self) -> str:
        """Return the JDBC URL the Spark Postgres sink will connect with."""
        return f"jdbc:postgresql://{self.host}:{self.port}/{self.database}"


@dataclass(frozen=True)
class GrafanaConfig:
    """Grafana admin credentials surfaced via env."""

    admin_password: str


def load_kafka_config() -> KafkaConfig:
    """Load Kafka settings from the environment, falling back to local defaults."""
    return KafkaConfig(
        bootstrap_servers=_get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
        topic=_get("KAFKA_TOPIC", "web_events"),
    )


def load_generator_config() -> GeneratorConfig:
    """Load generator settings from the environment, falling back to local defaults."""
    return GeneratorConfig(
        rate_per_sec=_get_int("GENERATOR_RATE_PER_SEC", 10),
        jitter_seconds=_get_int("GENERATOR_JITTER_SECONDS", 30),
        server_registry_path=_get("SERVER_REGISTRY_PATH", "data/servers.csv"),
    )


def load_spark_config() -> SparkConfig:
    """Load Spark/Iceberg settings from the environment, falling back to local defaults."""
    return SparkConfig(
        driver_memory=_get("SPARK_DRIVER_MEMORY", "2g"),
        executor_memory=_get("SPARK_EXECUTOR_MEMORY", "2g"),
        checkpoint_dir=_get("SPARK_CHECKPOINT_DIR", "/opt/checkpoints/web_events"),
        iceberg_warehouse_dir=_get("ICEBERG_WAREHOUSE_DIR", "/opt/warehouse"),
        iceberg_catalog=_get("ICEBERG_CATALOG", "lakehouse"),
        iceberg_table=_get("ICEBERG_TABLE", "web_events"),
        watermark_duration=_get("WATERMARK_DURATION", "2 minutes"),
    )


def load_postgres_config() -> PostgresConfig:
    """Load Postgres settings from the environment, falling back to local defaults."""
    return PostgresConfig(
        host=_get("POSTGRES_HOST", "postgres"),
        port=_get_int("POSTGRES_PORT", 5432),
        database=_get("POSTGRES_DB", "serving"),
        user=_get("POSTGRES_USER", "serving"),
        password=_get("POSTGRES_PASSWORD", "serving"),
        schema=_get("POSTGRES_SCHEMA", "serving"),
    )


def load_grafana_config() -> GrafanaConfig:
    """Load Grafana settings from the environment, falling back to local defaults."""
    return GrafanaConfig(
        admin_password=_get("GRAFANA_ADMIN_PASSWORD", "admin"),
    )
