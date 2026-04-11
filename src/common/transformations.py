"""Pure Python parse and enrich functions for the Traffic Observability Pipeline.

These functions serve as the unit-tested specification of the business logic
that the Spark streaming job implements via DataFrame API. They are used in
unit tests to validate parsing and enrichment rules without a SparkSession.

Pure stdlib. No pyspark, no third-party imports.
"""
from __future__ import annotations

import csv
import json
import logging
from typing import Any

from src.common.schemas import EVENT_FIELDS

logger = logging.getLogger(__name__)

_REQUIRED_FIELDS: set[str] = {name for name, _ in EVENT_FIELDS}
_INT_FIELDS: set[str] = {name for name, typ in EVENT_FIELDS if typ == "int"}


def load_server_registry(path: str) -> dict[str, dict[str, str]]:
    """Read the server registry CSV and return a lookup keyed by server_id."""
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        registry: dict[str, dict[str, str]] = {}
        for row in reader:
            registry[row["server_id"]] = {
                "region": row["region"],
                "datacenter": row["datacenter"],
                "service": row["service"],
                "environment": row["environment"],
            }
    if not registry:
        raise ValueError(f"No servers found in {path}")
    return registry


def parse_event_json(raw: str) -> dict[str, Any] | None:
    """Parse a JSON string into an event dict, validating all required fields."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(data, dict):
        return None

    if not _REQUIRED_FIELDS.issubset(data.keys()):
        return None

    for field in _INT_FIELDS:
        if not isinstance(data[field], int):
            return None

    return data


def enrich_event(
    event: dict[str, Any],
    registry: dict[str, dict[str, str]],
) -> dict[str, Any] | None:
    """Add region, datacenter, service, environment from registry lookup."""
    server_id = event.get("server_id")
    if server_id is None or server_id not in registry:
        return None
    return {**event, **registry[server_id]}
