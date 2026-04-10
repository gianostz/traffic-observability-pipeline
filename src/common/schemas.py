"""Pure Python event schema for the Traffic Observability Pipeline.

Defines field names, type labels, and domain constants (path templates,
status-code weights, HTTP method weights, user-agent pool) shared by the
generator and — in B3 — by the Spark consumer's StructType builder.

Pure stdlib. No pyspark, no third-party imports.
"""
from __future__ import annotations

# (field_name, type_label) — type labels are descriptive strings; the
# StructType mapping lives in src/streaming/ and is built in B3.
EVENT_FIELDS: tuple[tuple[str, str], ...] = (
    ("event_id", "string"),
    ("event_ts", "string"),
    ("server_id", "string"),
    ("method", "string"),
    ("path", "string"),
    ("status_code", "int"),
    ("bytes_sent", "int"),
    ("duration_ms", "int"),
    ("remote_ip", "string"),
    ("user_agent", "string"),
)

PATH_TEMPLATES: tuple[str, ...] = (
    "/api/users/:id",
    "/api/orders",
    "/api/products/:id",
    "/health",
    "/static/css/main.css",
    "/static/js/app.js",
    "/api/auth/login",
    "/api/search",
    "/api/cart",
    "/api/checkout",
)

# (status_code, weight) — weights sum to 1.0.
STATUS_CODE_WEIGHTS: tuple[tuple[int, float], ...] = (
    (200, 0.74),
    (201, 0.05),
    (204, 0.04),
    (301, 0.05),
    (304, 0.05),
    (400, 0.02),
    (401, 0.01),
    (403, 0.01),
    (404, 0.02),
    (500, 0.005),
    (502, 0.003),
    (503, 0.002),
)

# (method, weight) — weights sum to 1.0.
HTTP_METHODS: tuple[tuple[str, float], ...] = (
    ("GET", 0.70),
    ("POST", 0.15),
    ("PUT", 0.08),
    ("DELETE", 0.05),
    ("PATCH", 0.02),
)

USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "curl/8.4.0",
    "python-requests/2.31.0",
    "Apache-HttpClient/4.5.14",
)
