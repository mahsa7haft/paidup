"""Prometheus counters for PaidUp-specific business metrics."""
from prometheus_client import Counter

lookup_cache = Counter(
    "paidup_lookup_cache_total",
    "Lookup requests by cache outcome",
    ["layer"],  # "redis" | "miss"
)

analysis_cache = Counter(
    "paidup_analysis_cache_total",
    "Analyze requests by cache layer served",
    ["layer"],  # "redis" | "db" | "api"
)
