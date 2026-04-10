"""Smoke tests for src.common.config.

These exist primarily so `uv run pytest tests/unit -q` exits 0 (not exit 5
"no tests collected") on a fresh clone. They will be supplemented by real
config tests as later slices add config keys with non-trivial loading rules.
"""
from __future__ import annotations

import os
from unittest.mock import patch

from src.common.config import (
    load_generator_config,
    load_kafka_config,
    load_postgres_config,
    load_spark_config,
)


def test_kafka_config_uses_defaults_when_env_unset() -> None:
    with patch.dict(os.environ, {}, clear=True):
        cfg = load_kafka_config()
    assert cfg.bootstrap_servers == "kafka:9092"
    assert cfg.topic == "web_events"


def test_kafka_config_reads_env_overrides() -> None:
    with patch.dict(
        os.environ,
        {"KAFKA_BOOTSTRAP_SERVERS": "localhost:19092", "KAFKA_TOPIC": "test_topic"},
        clear=True,
    ):
        cfg = load_kafka_config()
    assert cfg.bootstrap_servers == "localhost:19092"
    assert cfg.topic == "test_topic"


def test_generator_config_coerces_int() -> None:
    with patch.dict(
        os.environ,
        {"GENERATOR_RATE_PER_SEC": "25", "GENERATOR_JITTER_SECONDS": "5"},
        clear=True,
    ):
        cfg = load_generator_config()
    assert cfg.rate_per_sec == 25
    assert cfg.jitter_seconds == 5


def test_postgres_config_jdbc_url() -> None:
    with patch.dict(
        os.environ,
        {
            "POSTGRES_HOST": "db",
            "POSTGRES_PORT": "5433",
            "POSTGRES_DB": "serving",
        },
        clear=True,
    ):
        cfg = load_postgres_config()
    assert cfg.jdbc_url == "jdbc:postgresql://db:5433/serving"


def test_spark_config_defaults_match_clauseMd() -> None:
    with patch.dict(os.environ, {}, clear=True):
        cfg = load_spark_config()
    assert cfg.driver_memory == "2g"
    assert cfg.executor_memory == "2g"
    assert cfg.watermark_duration == "2 minutes"
