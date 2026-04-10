"""Unit tests for pure event-generation functions in src.generator.producer."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.common.schemas import STATUS_CODE_WEIGHTS, USER_AGENTS
from src.generator.producer import generate_event, load_server_ids


def test_load_server_ids() -> None:
    ids = load_server_ids("data/servers.csv")
    assert len(ids) > 0
    assert all(isinstance(sid, str) for sid in ids)


def test_load_server_ids_format() -> None:
    ids = load_server_ids("data/servers.csv")
    for sid in ids:
        parts = sid.split("-")
        assert len(parts) == 3, f"Unexpected server_id format: {sid}"


def test_generate_event_has_all_fields() -> None:
    ids = load_server_ids("data/servers.csv")
    now = datetime.now(UTC)
    event = generate_event(ids, now)
    expected_fields = {
        "event_id",
        "event_ts",
        "server_id",
        "method",
        "path",
        "status_code",
        "bytes_sent",
        "duration_ms",
        "remote_ip",
        "user_agent",
    }
    assert set(event.keys()) == expected_fields


def test_generate_event_field_types() -> None:
    ids = load_server_ids("data/servers.csv")
    now = datetime.now(UTC)
    event = generate_event(ids, now)
    assert isinstance(event["event_id"], str)
    assert isinstance(event["event_ts"], str)
    assert isinstance(event["server_id"], str)
    assert isinstance(event["method"], str)
    assert isinstance(event["path"], str)
    assert isinstance(event["status_code"], int)
    assert isinstance(event["bytes_sent"], int)
    assert isinstance(event["duration_ms"], int)
    assert isinstance(event["remote_ip"], str)
    assert isinstance(event["user_agent"], str)


def test_generate_event_server_id_from_pool() -> None:
    ids = load_server_ids("data/servers.csv")
    now = datetime.now(UTC)
    for _ in range(50):
        event = generate_event(ids, now)
        assert event["server_id"] in ids


def test_generate_event_timestamp_is_jittered() -> None:
    now = datetime(2026, 4, 10, 12, 0, 0, tzinfo=UTC)
    ids = ["web-use1-01"]
    for _ in range(100):
        event = generate_event(ids, now, jitter_seconds=30)
        ts = datetime.strptime(event["event_ts"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=UTC
        )
        assert ts <= now
        assert ts >= now - timedelta(seconds=30)


def test_generate_event_status_code_is_valid() -> None:
    valid_codes = {code for code, _ in STATUS_CODE_WEIGHTS}
    ids = ["web-use1-01"]
    now = datetime.now(UTC)
    for _ in range(200):
        event = generate_event(ids, now)
        assert event["status_code"] in valid_codes


def test_generate_event_ip_in_test_net() -> None:
    ids = ["web-use1-01"]
    now = datetime.now(UTC)
    for _ in range(100):
        event = generate_event(ids, now)
        assert event["remote_ip"].startswith("192.0.2.")
        octet = int(event["remote_ip"].split(".")[3])
        assert 1 <= octet <= 254


def test_generate_event_duration_clamped() -> None:
    ids = ["web-use1-01"]
    now = datetime.now(UTC)
    for _ in range(1000):
        event = generate_event(ids, now)
        assert 1 <= event["duration_ms"] <= 2000


def test_generate_event_bytes_sent_range() -> None:
    ids = ["web-use1-01"]
    now = datetime.now(UTC)
    for _ in range(100):
        event = generate_event(ids, now)
        assert 100 <= event["bytes_sent"] <= 50_000


def test_generate_event_user_agent_from_pool() -> None:
    ids = ["web-use1-01"]
    now = datetime.now(UTC)
    for _ in range(50):
        event = generate_event(ids, now)
        assert event["user_agent"] in USER_AGENTS
