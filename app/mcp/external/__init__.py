"""External MCP integration layer (clients, errors, retry, metrics).

Packages:
- interfaces: common client interface
- errors: normalized error schema
- retry: async retry utilities
- metrics: Prometheus counters/histograms
- providers: vendor-specific clients (e.g., GitHub)
"""

__all__ = [
    "interfaces",
    "errors",
    "retry",
    "metrics",
    "providers",
]


