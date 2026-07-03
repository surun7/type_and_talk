# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Caches for LLM responses and control trees.

Caches MUST NOT leak sensitive data.  LLM cache is in-memory only, cleared on
app exit.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Generic, TypeVar

if TYPE_CHECKING:
    from agent_uia.executor import UIAControlNode
    from agent_uia.llm_client import LLMResponse

T = TypeVar("T")


@dataclass
class CacheEntry(Generic[T]):
    """A single entry in a TTL cache.

    Attributes:
        value: The cached value.
        created_at: Unix timestamp of creation or last update.
        expires_at: Unix timestamp after which the entry is considered stale.
        hit_count: Number of times this entry was retrieved while fresh.
    """

    value: T
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 300.0)
    hit_count: int = 0


class TTLCache(Generic[T]):
    """Thread-safe in-memory LRU cache with time-to-live eviction.

    Args:
        max_size: Maximum number of entries before LRU eviction kicks in.
        default_ttl_s: Default TTL in seconds for entries that do not specify
            their own.
    """

    def __init__(self, max_size: int = 256, default_ttl_s: float = 300.0) -> None:
        self._max_size = max_size
        self._default_ttl_s = default_ttl_s
        self._store: OrderedDict[str, CacheEntry[T]] = OrderedDict()
        self._hits: int = 0
        self._misses: int = 0
        self._evictions: int = 0
        self._lock = __import__("threading").Lock()

    # ── public API ──────────────────────────────────────────────────────────────

    def get(self, key: str) -> T | None:
        """Return the cached value for *key*, or ``None`` if missing / expired.

        Moves a hit entry to the end of the LRU order.
        """
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None

            if entry.expires_at <= time.time():
                del self._store[key]
                self._evictions += 1
                self._misses += 1
                return None

            # LRU: move to end (most recently used)
            self._store.move_to_end(key)
            entry.hit_count += 1
            self._hits += 1
            return entry.value

    def set(self, key: str, value: T, ttl_s: float | None = None) -> None:
        """Store *value* under *key* with an optional per-entry TTL.

        If the cache is at capacity the least recently used entry is evicted
        first.
        """
        now = time.time()
        ttl = ttl_s if ttl_s is not None else self._default_ttl_s
        expires_at = now + ttl

        with self._lock:
            if key in self._store:
                # Update existing entry in-place and move to end.
                entry = self._store[key]
                entry.value = value
                entry.created_at = now
                entry.expires_at = expires_at
                entry.hit_count = 0
                self._store.move_to_end(key)
                return

            # Evict LRU if at capacity.
            if len(self._store) >= self._max_size:
                self._store.popitem(last=False)  # FIFO = LRU
                self._evictions += 1

            self._store[key] = CacheEntry(value=value, created_at=now, expires_at=expires_at)

    def invalidate(self, key: str) -> None:
        """Remove a single key from the cache, if present."""
        with self._lock:
            self._store.pop(key, None)

    def invalidate_prefix(self, prefix: str) -> None:
        """Remove all keys starting with *prefix*."""
        with self._lock:
            keys_to_remove = [k for k in self._store if k.startswith(prefix)]
            for k in keys_to_remove:
                del self._store[k]

    def clear(self) -> None:
        """Remove all entries from the cache."""
        with self._lock:
            self._store.clear()

    def stats(self) -> dict[str, Any]:
        """Return operational statistics for this cache.

        Returns:
            A dict with keys ``size``, ``hits``, ``misses``, ``evictions``,
            and ``hit_rate`` (a float in [0, 1], or 0 if no lookups were
            performed).
        """
        with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0.0
            return {
                "size": len(self._store),
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "hit_rate": round(hit_rate, 4),
            }


class LLMResponseCache(TTLCache):
    """In-memory cache for LLM chat completions.

    Default TTL is 300 seconds (5 minutes).  The cache is purely in-memory
    and is never persisted to disk.  Keys are derived from the SHA-256 hash
    of the serialised messages and model name — the key itself is never
    logged or written to any external store.
    """

    def __init__(self, max_size: int = 256, default_ttl_s: float = 300.0) -> None:
        super().__init__(max_size=max_size, default_ttl_s=default_ttl_s)

    def make_key(self, messages: list[dict[str, Any]], model: str) -> str:
        """Produce a deterministic cache key from *messages* and *model*.

        The key is the hex-encoded SHA-256 digest of the JSON-serialised
        payload.

        .. warning::

            The returned key MUST NOT be logged or persisted anywhere.
        """
        payload = json.dumps({"messages": messages, "model": model}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ControlTreeCache(TTLCache):
    """Short-lived cache for UI automation control trees.

    Default TTL is 3 seconds with a maximum of 32 entries.  Call
    ``invalidate_on_action(window_id)`` after any user interaction (click,
    type, etc.) that may have changed the tree.
    """

    def __init__(self, max_size: int = 32, default_ttl_s: float = 3.0) -> None:
        super().__init__(max_size=max_size, default_ttl_s=default_ttl_s)

    @staticmethod
    def make_key(window_id: str, tree_hash: str | None = None) -> str:
        """Produce a cache key for a control tree.

        Args:
            window_id: The identifier of the target window.
            tree_hash: Optional hash that can be used to invalidate the tree
                without waiting for TTL expiry.
        """
        if tree_hash:
            return f"ct:{window_id}:{tree_hash}"
        return f"ct:{window_id}"

    def invalidate_on_action(self, window_id: str) -> None:
        """Invalidate all cached control trees for *window_id*.

        Call this after any action that may have mutated the UI tree (click,
        type, key press, etc.).
        """
        self.invalidate_prefix(f"ct:{window_id}")
