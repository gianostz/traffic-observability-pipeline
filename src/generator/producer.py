"""Synthetic HTTP access-log event emitter for the Traffic Observability Pipeline.

Pure event-generation functions (load_server_ids, generate_event) are at the
top and do NOT import confluent_kafka — they are unit-testable on the host
venv. Kafka-dependent code lives below and is only exercised inside the
Docker container or in integration tests.
"""
from __future__ import annotations

import csv
import json
import logging
import random
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from src.common.schemas import (
    HTTP_METHODS,
    PATH_TEMPLATES,
    STATUS_CODE_WEIGHTS,
    USER_AGENTS,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure functions — no confluent_kafka dependency
# ---------------------------------------------------------------------------


def load_server_ids(path: str) -> list[str]:
    """Read the server registry CSV and return a list of server_id values."""
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        ids = [row["server_id"] for row in reader]
    if not ids:
        raise ValueError(f"No server IDs found in {path}")
    return ids


def generate_event(
    server_ids: list[str],
    now: datetime,
    *,
    jitter_seconds: int = 30,
) -> dict[str, Any]:
    """Produce a single synthetic event dict conforming to the PRD schema."""
    jitter = timedelta(seconds=random.uniform(0, jitter_seconds))
    event_time = now - jitter
    ts_str = (
        event_time.strftime("%Y-%m-%dT%H:%M:%S.")
        + f"{event_time.microsecond // 1000:03d}Z"
    )

    status_codes, status_weights = zip(*STATUS_CODE_WEIGHTS, strict=True)
    methods, method_weights = zip(*HTTP_METHODS, strict=True)

    raw_duration = int(random.paretovariate(1.5) * 10)
    duration_ms = max(1, min(raw_duration, 2000))

    return {
        "event_id": str(uuid.uuid4()),
        "event_ts": ts_str,
        "server_id": random.choice(server_ids),
        "method": random.choices(methods, weights=method_weights, k=1)[0],
        "path": random.choice(PATH_TEMPLATES),
        "status_code": random.choices(status_codes, weights=status_weights, k=1)[0],
        "bytes_sent": random.randint(100, 50_000),
        "duration_ms": duration_ms,
        "remote_ip": f"192.0.2.{random.randint(1, 254)}",
        "user_agent": random.choice(USER_AGENTS),
    }


# ---------------------------------------------------------------------------
# Kafka-dependent code — only imported when actually running the producer
# ---------------------------------------------------------------------------


def _delivery_callback(err: Any, msg: Any) -> None:
    """Log Kafka delivery results."""
    if err is not None:
        logger.warning("event=delivery_failed error=%s", err)
    else:
        logger.debug(
            "event=delivery_ok topic=%s partition=%s offset=%s",
            msg.topic(),
            msg.partition(),
            msg.offset(),
        )


def run(
    kafka_bootstrap_servers: str,
    topic: str,
    rate_per_sec: int,
    jitter_seconds: int,
    server_registry_path: str,
) -> None:
    """Main producer loop — load registry, create Kafka producer, emit events."""
    import confluent_kafka  # noqa: PLC0415 — deferred import

    server_ids = load_server_ids(server_registry_path)
    logger.info(
        "event=generator_started servers_loaded=%d rate_per_sec=%d jitter_seconds=%d topic=%s",
        len(server_ids),
        rate_per_sec,
        jitter_seconds,
        topic,
    )

    producer = confluent_kafka.Producer(
        {"bootstrap.servers": kafka_bootstrap_servers}
    )

    interval = 1.0 / rate_per_sec
    try:
        while True:
            now = datetime.now(UTC)
            event = generate_event(server_ids, now, jitter_seconds=jitter_seconds)
            producer.produce(
                topic,
                value=json.dumps(event).encode("utf-8"),
                callback=_delivery_callback,
            )
            producer.poll(0)
            time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("event=generator_stopping reason=keyboard_interrupt")
    finally:
        remaining = producer.flush(timeout=5)
        logger.info("event=generator_stopped unflushed_messages=%d", remaining)


def main() -> None:
    """Entrypoint: load config, configure logging, run the producer loop."""
    from src.common.config import load_generator_config, load_kafka_config  # noqa: PLC0415

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    kafka_cfg = load_kafka_config()
    gen_cfg = load_generator_config()

    run(
        kafka_bootstrap_servers=kafka_cfg.bootstrap_servers,
        topic=kafka_cfg.topic,
        rate_per_sec=gen_cfg.rate_per_sec,
        jitter_seconds=gen_cfg.jitter_seconds,
        server_registry_path=gen_cfg.server_registry_path,
    )


if __name__ == "__main__":
    main()
