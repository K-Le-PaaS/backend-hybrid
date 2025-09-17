from __future__ import annotations

from prometheus_client import Counter, Histogram, Gauge


MCP_EXTERNAL_REQUESTS = Counter(
    "mcp_external_requests_total",
    "Total requests to external MCP servers",
    labelnames=("provider", "operation", "result"),
)

MCP_EXTERNAL_LATENCY = Histogram(
    "mcp_external_request_latency_seconds",
    "Latency for external MCP requests",
    labelnames=("provider", "operation"),
    buckets=(0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0),
)

MCP_EXTERNAL_ERRORS = Counter(
    "mcp_external_errors_total",
    "Total errors from external MCP requests",
    labelnames=("provider", "operation", "code"),
)

MCP_EXTERNAL_HEALTH = Gauge(
    "mcp_external_health_status",
    "Health status of external MCP providers (1=healthy,0=unhealthy)",
    labelnames=("provider",),
)


