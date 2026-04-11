"""Unit tests for pure parse/enrich functions in src.common.transformations."""
from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime

from src.common.schemas import EVENT_FIELDS
from src.common.transformations import enrich_event, load_server_registry, parse_event_json
from src.generator.producer import generate_event, load_server_ids

# ---------------------------------------------------------------------------
# load_server_registry
# ---------------------------------------------------------------------------


def test_load_server_registry_returns_all_servers() -> None:
    registry = load_server_registry("data/servers.csv")
    assert len(registry) == 30


def test_load_server_registry_keys_match_csv() -> None:
    registry = load_server_registry("data/servers.csv")
    assert "web-use1-01" in registry
    entry = registry["web-use1-01"]
    assert entry["region"] == "us-east"
    assert entry["datacenter"] == "us-east-1a"
    assert entry["service"] == "web"
    assert entry["environment"] == "prod"


def test_load_server_registry_empty_file_raises() -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("server_id,region,datacenter,service,environment\n")
        f.flush()
        import pytest

        with pytest.raises(ValueError, match="No servers found"):
            load_server_registry(f.name)


# ---------------------------------------------------------------------------
# parse_event_json
# ---------------------------------------------------------------------------


def _sample_event() -> dict:
    server_ids = load_server_ids("data/servers.csv")
    return generate_event(server_ids, datetime.now(UTC))


def test_parse_event_json_valid() -> None:
    event = _sample_event()
    raw = json.dumps(event)
    parsed = parse_event_json(raw)
    assert parsed is not None
    assert parsed["event_id"] == event["event_id"]


def test_parse_event_json_malformed() -> None:
    assert parse_event_json("{bad json") is None


def test_parse_event_json_missing_field() -> None:
    event = _sample_event()
    del event["server_id"]
    assert parse_event_json(json.dumps(event)) is None


def test_parse_event_json_wrong_type() -> None:
    event = _sample_event()
    event["status_code"] = "not_an_int"
    assert parse_event_json(json.dumps(event)) is None


def test_parse_event_json_preserves_all_fields() -> None:
    event = _sample_event()
    raw = json.dumps(event)
    parsed = parse_event_json(raw)
    assert parsed is not None
    expected_fields = {name for name, _ in EVENT_FIELDS}
    assert set(parsed.keys()) == expected_fields


# ---------------------------------------------------------------------------
# enrich_event
# ---------------------------------------------------------------------------


def test_enrich_event_known_server() -> None:
    registry = load_server_registry("data/servers.csv")
    event = _sample_event()
    enriched = enrich_event(event, registry)
    assert enriched is not None
    assert "region" in enriched
    assert "datacenter" in enriched
    assert "service" in enriched
    assert "environment" in enriched


def test_enrich_event_unknown_server() -> None:
    registry = load_server_registry("data/servers.csv")
    event = _sample_event()
    event["server_id"] = "unknown-server-99"
    assert enrich_event(event, registry) is None


def test_enrich_event_preserves_all_original_fields() -> None:
    registry = load_server_registry("data/servers.csv")
    event = _sample_event()
    enriched = enrich_event(event, registry)
    assert enriched is not None
    for key in event:
        assert enriched[key] == event[key]
