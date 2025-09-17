from __future__ import annotations

from prometheus_client import Counter, Histogram


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


