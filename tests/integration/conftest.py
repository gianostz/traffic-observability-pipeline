"""Shared session-scoped fixtures for integration tests."""
from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from testcontainers.kafka import KafkaContainer


@pytest.fixture(scope="session")
def kafka_container() -> Generator[KafkaContainer, None, None]:
    """Start a Kafka container for the test session."""
    container = KafkaContainer()
    container.start()
    yield container
    container.stop()


@pytest.fixture(scope="session")
def bootstrap_server(kafka_container: KafkaContainer) -> str:
    """Return the bootstrap server address for the running Kafka container."""
    return kafka_container.get_bootstrap_server()


@pytest.fixture(scope="session")
def iceberg_warehouse(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Return a temporary directory for the Iceberg warehouse."""
    return str(tmp_path_factory.mktemp("iceberg_warehouse"))


@pytest.fixture(scope="session")
def spark_session(iceberg_warehouse: str) -> Generator:
    """Build a SparkSession with Iceberg + Kafka JARs for integration tests."""
    # Iceberg 1.10.1 requires Java 11+; use temurin-11 if the default is older
    _java11 = os.path.expanduser("~/.jdks/temurin-11.0.27")
    if os.path.isdir(_java11):
        os.environ["JAVA_HOME"] = _java11

    # Ensure PySpark uses its bundled Spark, not a stale host SPARK_HOME
    os.environ.pop("SPARK_HOME", None)

    # Point PySpark to the venv Python to avoid worker socket issues on Windows
    import sys

    os.environ["PYSPARK_PYTHON"] = sys.executable
    os.environ["PYSPARK_DRIVER_PYTHON"] = sys.executable

    from pyspark.sql import SparkSession

    spark = (
        SparkSession.builder
        .master("local[1]")
        .appName("integration-tests")
        .config(
            "spark.jars.packages",
            "org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.10.1,"
            "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.8",
        )
        .config("spark.jars.repositories", "https://repo1.maven.org/maven2/")
        .config("spark.sql.catalog.test_lakehouse", "org.apache.iceberg.spark.SparkCatalog")
        .config("spark.sql.catalog.test_lakehouse.type", "hadoop")
        .config("spark.sql.catalog.test_lakehouse.warehouse", iceberg_warehouse)
        .config(
            "spark.sql.extensions",
            "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
        )
        .config("spark.driver.memory", "1g")
        .config("spark.driver.host", "127.0.0.1")
        .config("spark.driver.bindAddress", "127.0.0.1")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "2")
        .getOrCreate()
    )
    yield spark
    spark.stop()
