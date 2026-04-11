"""Unit tests for src.common.schemas."""
from __future__ import annotations

from src.common.schemas import (
    EVENT_FIELDS,
    HTTP_METHODS,
    PATH_TEMPLATES,
    STATUS_CODE_WEIGHTS,
    USER_AGENTS,
)


def test_event_fields_has_ten_entries() -> None:
    assert len(EVENT_FIELDS) == 10


def test_event_field_names_match_prd() -> None:
    names = [name for name, _ in EVENT_FIELDS]
    expected = [
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
    ]
    assert names == expected


def test_no_duplicate_field_names() -> None:
    names = [name for name, _ in EVENT_FIELDS]
    assert len(names) == len(set(names))


def test_status_code_weights_sum_to_one() -> None:
    total = sum(w for _, w in STATUS_CODE_WEIGHTS)
    assert abs(total - 1.0) < 1e-9


def test_http_methods_weights_sum_to_one() -> None:
    total = sum(w for _, w in HTTP_METHODS)
    assert abs(total - 1.0) < 1e-9


def test_path_templates_has_at_least_eight() -> None:
    assert len(PATH_TEMPLATES) >= 8


def test_no_duplicate_paths() -> None:
    assert len(PATH_TEMPLATES) == len(set(PATH_TEMPLATES))


def test_user_agents_has_at_least_five() -> None:
    assert len(USER_AGENTS) >= 5
