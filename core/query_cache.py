"""Redis-backed query cache to avoid repeated LLM calls for the same query.

Cached value is the full API response, e.g.:

  {
    "answer": "...",
    "sources": [{"text": "...", "file": "..."}, ...],
    "graph_context": [],
    "explanation": null,
    "graph_paths": [{"source": "...", "relation": "...", "target": "..."}, ...]
  }

Key format: "{query}|{graph_version}" (e.g. "How is Company A related to Europe?|v1").
"""

import json
import logging

import redis

logger = logging.getLogger(__name__)

# 默认 graph 版本，后续 ingestion 后可更新
GRAPH_VERSION = "v1"
GRAPH_VERSION_KEY = "graph:version"
DEFAULT_TTL = 3600


class QueryCache:
    """Simple Redis wrapper for caching full query responses."""

    def __init__(self, url: str = "redis://localhost:6379/0") -> None:
        self.client = redis.from_url(url)

    def get(self, key: str):
        """Return cached value as dict, or None if miss."""
        val = self.client.get(key)
        if val is None:
            return None
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("Query cache get: invalid value for key %s: %s", key, e)
            return None

    def set(self, key: str, value: dict, ttl: int = DEFAULT_TTL) -> None:
        """Store value (dict) as JSON with optional TTL in seconds."""
        self.client.set(key, json.dumps(value), ex=ttl)

    def get_graph_version(self) -> str:
        """Read current graph version from Redis; default to GRAPH_VERSION."""
        raw = self.client.get(GRAPH_VERSION_KEY)
        if raw is None:
            try:
                self.client.set(GRAPH_VERSION_KEY, GRAPH_VERSION)
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to initialize graph version: %s", e)
            return GRAPH_VERSION
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="ignore") or GRAPH_VERSION
        return str(raw) or GRAPH_VERSION

    def bump_graph_version(self) -> str:
        """
        Increment graph version in Redis and return new version string.
        Format: v{n}
        """
        cur = self.get_graph_version()
        m = cur[1:] if cur.startswith("v") else cur
        try:
            n = int(m)
        except (TypeError, ValueError):
            n = 1
        nxt = f"v{n + 1}"
        self.client.set(GRAPH_VERSION_KEY, nxt)
        return nxt
