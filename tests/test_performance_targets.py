# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Performance target tests — verify cache hit latencies are within budget.

All tests in this module are marked ``@pytest.mark.slow`` because they
measure wall-clock time and may be sensitive to system load.  Run them
in isolation with::

    pytest tests/test_performance_targets.py -v
"""

from __future__ import annotations

import time

import pytest

from agent_uia.llm_client import (
    AssistantMessage,
    LLMResponse,
    LLMUsage,
)
from agent_uia.performance.cache import (
    ControlTreeCache,
    LLMResponseCache,
)


pytestmark = pytest.mark.slow


# ── helpers ──────────────────────────────────────────────────────────────────


def _dummy_llm_response(text: str = "cached reply") -> LLMResponse:
    """Create a minimal LLMResponse for cache hit testing."""
    return LLMResponse(
        message=AssistantMessage(content=text),
        usage=LLMUsage(prompt_tokens=5, completion_tokens=5, cost_usd=0.0),
        finish_reason="stop",
    )


# ── LLM cache hit target: ≤ 5 ms ─────────────────────────────────────────────


class TestLLMCacheHitLatency:
    """Verify that a pre-populated LLMResponseCache returns in ≤ 5 ms."""

    def test_llm_cache_hit_under_5ms(self) -> None:
        """A cache hit via LLMResponseCache must complete in under 5 ms."""
        cache = LLMResponseCache(max_size=16, default_ttl_s=300.0)

        # Pre-populate the cache with a known key and response.
        messages = [{"role": "user", "content": "hello"}]
        key = cache.make_key(messages, model="deepseek-chat")
        response = _dummy_llm_response()
        cache.set(key, response)

        # Warm-up: one get to avoid JIT / page-fault overhead.
        _ = cache.get(key)

        # Timed measurement.
        N = 1000
        start = time.perf_counter()
        for _ in range(N):
            hit = cache.get(key)
            assert hit is not None  # sanity
        elapsed_ms = (time.perf_counter() - start) * 1000.0 / N

        assert elapsed_ms < 5.0, (
            f"LLM cache hit took {elapsed_ms:.3f} ms avg over {N} iterations "
            f"(target ≤ 5 ms)"
        )


# ── Control tree cache hit target: ≤ 1 ms ────────────────────────────────────


class TestControlTreeCacheHitLatency:
    """Verify that a pre-populated ControlTreeCache returns in ≤ 1 ms."""

    def test_control_tree_cache_hit_under_1ms(self) -> None:
        """A cache hit via ControlTreeCache must complete in under 1 ms."""
        cache = ControlTreeCache(max_size=16, default_ttl_s=30.0)

        # Pre-populate.
        key = ControlTreeCache.make_key("notepad", tree_hash="abc")
        cache.set(key, None)  # None as stand-in for UIAControlNode

        # Warm-up.
        _ = cache.get(key)

        # Timed measurement.
        N = 2000
        start = time.perf_counter()
        for _ in range(N):
            hit = cache.get(key)
            assert hit is not None  # sanity
        elapsed_ms = (time.perf_counter() - start) * 1000.0 / N

        assert elapsed_ms < 1.0, (
            f"ControlTreeCache hit took {elapsed_ms:.3f} ms avg over {N} iterations "
            f"(target ≤ 1 ms)"
        )
