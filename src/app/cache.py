"""
Redis caching layer.

Gracefully degrades to a no-op when REDIS_URL is not set or Redis is
unreachable — the app behaves identically, just without caching.

TTLs
----
LOOKUP_TTL   : 1 hour  — Parliament data can change but rarely does mid-day.
ANALYSIS_TTL : 24 hours — AI analysis is stable within a day; prompt version
               is included in the key so bumping a prompt file auto-invalidates.
"""

import json
import logging
import os
import re

import redis

log = logging.getLogger(__name__)

LOOKUP_TTL   = 3_600      # 1 hour
ANALYSIS_TTL = 86_400     # 24 hours

_client: redis.Redis | None = None


def _get() -> redis.Redis | None:
    """Return a connected Redis client, or None if unavailable."""
    global _client
    if _client is not None:
        return _client
    url = os.environ.get("REDIS_URL")
    if not url:
        return None
    try:
        client = redis.from_url(url, decode_responses=True, socket_timeout=2)
        client.ping()
        _client = client
        log.info("Redis connected: %s", url.split("@")[-1])  # hide credentials
        return _client
    except Exception as exc:
        log.warning("Redis unavailable, caching disabled: %s", exc)
        return None


def get(key: str) -> dict | list | None:
    client = _get()
    if not client:
        return None
    try:
        raw = client.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def set(key: str, value: dict | list, ttl: int) -> None:
    client = _get()
    if not client:
        return
    try:
        client.setex(key, ttl, json.dumps(value, default=str))
    except Exception:
        pass


def make_key(*parts: str) -> str:
    """Normalise and join parts into a colon-separated cache key."""
    def _clean(s: str) -> str:
        return re.sub(r"\s+", "_", str(s).lower().strip())
    return "paidup:" + ":".join(_clean(p) for p in parts)
