# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for TTLCache, ControlTreeCache, and LLMResponseCache.

All caches are purely in-memory — the LLMResponseCache test explicitly
verifies that no disk I/O occurs.
"""

from __future__ import annotations

import time
from decimal import Decimal
from unittest import mock

import pytest

from agent_uia.llm_client import LLMResponse, LLMUsage
from agent_uia.performance.cache import (
    ControlTreeCache,
    LLMResponseCache,
    TTLCache,
)


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_llm_response(text: str = "hello") -> LLMResponse:
    """Create a minimal LLMResponse for cache tests."""
    from agent_uia.llm_client import AssistantMessage

    return LLMResponse(
        message=AssistantMessage(content=text),
        usage=LLMUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10,
                       estimated_cost_usd=Decimal("0.0")),
        finish_reason="stop",
    )


# ── TTLCache tests ───────────────────────────────────────────────────────────


class TestTTLCache:
    """Tests for the generic TTLCache."""

    def test_get_set_basic(self) -> None:
        """Set a value and retrieve it."""
        cache: TTLCache[str] = TTLCache(max_size=16, default_ttl_s=300.0)
        cache.set("greeting", "hello")
        assert cache.get("greeting") == "hello"

    def test_ttl_expiry(self) -> None:
        """A value set with 0.1s TTL must be gone after 0.2s."""
        cache: TTLCache[str] = TTLCache(max_size=16, default_ttl_s=300.0)
        cache.set("ephemeral", "now you see me", ttl_s=0.1)
        assert cache.get("ephemeral") == "now you see me"
        time.sleep(0.2)
        assert cache.get("ephemeral") is None

    def test_lru_eviction(self) -> None:
        """Fill past max_size and verify the oldest entry is evicted."""
        cache: TTLCache[int] = TTLCache(max_size=3, default_ttl_s=300.0)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        # Access "a" to make it recently used so "b" becomes LRU.
        cache.get("a")
        cache.set("d", 4)  # should evict "b" (the LRU)
        assert cache.get("a") == 1
        assert cache.get("b") is None  # evicted
        assert cache.get("c") == 3
        assert cache.get("d") == 4

    def test_invalidate(self) -> None:
        """Invalidate a specific key and verify it is removed."""
        cache: TTLCache[str] = TTLCache(max_size=16, default_ttl_s=300.0)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.invalidate("key1")
        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"

    def test_invalidate_prefix(self) -> None:
        """Invalidate all keys with a given prefix."""
        cache: TTLCache[str] = TTLCache(max_size=16, default_ttl_s=300.0)
        cache.set("user:1:name", "Alice")
        cache.set("user:2:name", "Bob")
        cache.set("config:theme", "dark")
        cache.invalidate_prefix("user:")
        assert cache.get("user:1:name") is None
        assert cache.get("user:2:name") is None
        assert cache.get("config:theme") == "dark"

    def test_clear(self) -> None:
        """Clear the cache and verify size is 0."""
        cache: TTLCache[str] = TTLCache(max_size=16, default_ttl_s=300.0)
        cache.set("a", "1")
        cache.set("b", "2")
        cache.clear()
        stats = cache.stats()
        assert stats["size"] == 0

    def test_stats(self) -> None:
        """Verify hits, misses, evictions, and hit_rate are tracked."""
        cache: TTLCache[str] = TTLCache(max_size=4, default_ttl_s=300.0)
        cache.set("a", "1")
        cache.set("b", "2")
        cache.set("c", "3")
        cache.set("d", "4")
        # Evict "a" by adding "e".
        cache.set("e", "5")

        cache.get("b")  # hit
        cache.get("c")  # hit
        cache.get("missing")  # miss

        stats = cache.stats()
        assert stats["size"] == 4  # b, c, d, e
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["evictions"] == 1
        assert stats["hit_rate"] == pytest.approx(2 / 3, rel=1e-4)


# ── LLMResponseCache tests ───────────────────────────────────────────────────


class TestLLMResponseCache:
    """Tests for LLMResponseCache — purely in-memory, never touches disk."""

    def test_cache_not_persisted_to_disk(self) -> None:
        """LLMResponseCache must never call open() for disk I/O.

        We monkeypatch the built-in open() so that any attempt to write
        the cache to disk will raise an AssertionError.
        """
        cache = LLMResponseCache(max_size=16, default_ttl_s=300.0)

        response = _make_llm_response("cached reply")
        key = cache.make_key([{"role": "user", "content": "hello"}], model="gpt-4")
        cache.set(key, response)

        with mock.patch("builtins.open") as mock_open:
            # Perform cache operations — none should touch disk.
            retrieved = cache.get(key)
            cache.invalidate(key)
            cache.get(key)  # miss, no disk I/O

            mock_open.assert_not_called()

        assert retrieved is not None
        assert retrieved.message.content == "cached reply"


# ── ControlTreeCache tests ───────────────────────────────────────────────────


class TestControlTreeCache:
    """Tests for ControlTreeCache (TTLCache[UIAControlNode] subclass)."""

    def test_make_key(self) -> None:
        """Verify make_key produces the expected format."""
        key = ControlTreeCache.make_key("notepad")
        assert key == "ct:notepad"

        key_hash = ControlTreeCache.make_key("notepad", tree_hash="abc123")
        assert key_hash == "ct:notepad:abc123"

    def test_invalidate_on_action(self) -> None:
        """invalidate_on_action must clear all entries for the given window."""
        cache = ControlTreeCache(max_size=16, default_ttl_s=30.0)

        # Insert two control trees for "notepad" and one for "calc".
        key_a = ControlTreeCache.make_key("notepad", tree_hash="aaa")
        key_b = ControlTreeCache.make_key("notepad", tree_hash="bbb")
        key_c = ControlTreeCache.make_key("calc")

        cache.set(key_a, object())  # sentinel values
        cache.set(key_b, object())
        cache.set(key_c, 42)

        cache.invalidate_on_action("notepad")

        assert cache.get(key_a) is None
        assert cache.get(key_b) is None
        assert cache.get(key_c) is not None  # "calc" unaffected
        assert cache.get(key_c) == 42
