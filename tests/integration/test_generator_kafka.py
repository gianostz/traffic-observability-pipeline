"""Integration test: produce events to a real Kafka broker, consume back, assert schema."""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from confluent_kafka import Consumer, Producer

from src.common.schemas import EVENT_FIELDS, STATUS_CODE_WEIGHTS, USER_AGENTS
from src.generator.producer import generate_event, load_server_ids


def test_produce_and_consume_events(bootstrap_server: str) -> None:
    topic = f"test_web_events_{uuid.uuid4().hex[:8]}"
    server_ids = load_server_ids("data/servers.csv")
    valid_codes = {code for code, _ in STATUS_CODE_WEIGHTS}
    expected_fields = {name for name, _ in EVENT_FIELDS}

    producer = Producer({"bootstrap.servers": bootstrap_server})

    events_sent = []
    for _ in range(10):
        now = datetime.now(UTC)
        event = generate_event(server_ids, now)
        payload = json.dumps(event).encode("utf-8")
        producer.produce(topic, value=payload)
        events_sent.append(event)
    producer.flush(timeout=10)

    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap_server,
            "group.id": f"test-group-{uuid.uuid4().hex[:8]}",
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([topic])

    consumed = []
    deadline = 30  # seconds
    import time

    start = time.monotonic()
    while len(consumed) < 10 and (time.monotonic() - start) < deadline:
        msg = consumer.poll(timeout=1.0)
        if msg is None or msg.error():
            continue
        consumed.append(json.loads(msg.value().decode("utf-8")))
    consumer.close()

    assert len(consumed) == 10

    for event in consumed:
        assert set(event.keys()) == expected_fields
        assert isinstance(event["event_id"], str)
        assert isinstance(event["event_ts"], str)
        assert isinstance(event["server_id"], str)
        assert event["server_id"] in server_ids
        assert isinstance(event["method"], str)
        assert isinstance(event["path"], str)
        assert isinstance(event["status_code"], int)
        assert event["status_code"] in valid_codes
        assert isinstance(event["bytes_sent"], int)
        assert 100 <= event["bytes_sent"] <= 50_000
        assert isinstance(event["duration_ms"], int)
        assert 1 <= event["duration_ms"] <= 2000
        assert event["remote_ip"].startswith("192.0.2.")
        assert event["user_agent"] in USER_AGENTS


def test_event_json_is_valid_utf8(bootstrap_server: str) -> None:
    topic = f"test_utf8_{uuid.uuid4().hex[:8]}"
    server_ids = load_server_ids("data/servers.csv")

    producer = Producer({"bootstrap.servers": bootstrap_server})
    now = datetime.now(UTC)
    event = generate_event(server_ids, now)
    producer.produce(topic, value=json.dumps(event).encode("utf-8"))
    producer.flush(timeout=10)

    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap_server,
            "group.id": f"test-group-{uuid.uuid4().hex[:8]}",
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([topic])

    import time

    start = time.monotonic()
    msg = None
    while (time.monotonic() - start) < 15:
        msg = consumer.poll(timeout=1.0)
        if msg is not None and msg.error() is None:
            break
    consumer.close()

    assert msg is not None
    assert msg.error() is None
    decoded = msg.value().decode("utf-8")
    parsed = json.loads(decoded)
    assert isinstance(parsed, dict)
    assert len(parsed) == 10
