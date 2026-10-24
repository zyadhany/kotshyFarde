"""
tests/test_cache.py
───────────────────
Unit tests for the modular caching system in app/core/cache.py.
"""

import time
from datetime import timedelta
import pytest

from app.core.cache import CacheManager, InMemoryCache, cache


def test_in_memory_cache_basic_ops():
    c = InMemoryCache()
    assert c.get("k1") is None
    assert c.has("k1") is False

    c.set("k1", "val1")
    assert c.has("k1") is True
    assert c.get("k1") == "val1"

    deleted = c.delete("k1")
    assert deleted is True
    assert c.has("k1") is False
    assert c.get("k1") is None
    assert c.delete("k1") is False


def test_in_memory_cache_ttl_expiration():
    c = InMemoryCache()
    c.set("temp", "hello", ttl=0.05)
    assert c.get("temp") == "hello"

    time.sleep(0.06)
    assert c.get("temp") is None
    assert c.has("temp") is False


def test_in_memory_cache_add_indefinite_default():
    """Verify add() with default lifetime (None/null) is always available."""
    c = InMemoryCache()
    # Default lifetime parameter is None
    c.add("perm1", "always_here")
    assert c.get("perm1") == "always_here"
    assert c.has("perm1") is True
    assert c.get_ttl("perm1") is None

    # Explicit lifetime=None
    c.add("perm2", "also_always_here", lifetime=None)
    assert c.get("perm2") == "also_always_here"
    assert c.has("perm2") is True
    assert c.get_ttl("perm2") is None


def test_in_memory_cache_add_with_lifetime_and_lazy_removal():
    """Verify add() data is valid only through lifetime, and removed when expired."""
    c = InMemoryCache()
    c.add("temp_data", {"score": 100}, lifetime=0.05)
    assert c.get("temp_data") == {"score": 100}
    assert c.has("temp_data") is True
    assert "temp_data" in c._store

    # Wait for lifetime to expire
    time.sleep(0.06)

    # Calling get() detects expired lifetime, removes it from store, and returns None
    assert c.get("temp_data") is None
    assert "temp_data" not in c._store
    assert c.has("temp_data") is False


def test_add_parameter_aliases():
    """Verify add() works with positional lifetime, lifetime kwarg, ttl, time, and timedelta."""
    c = InMemoryCache()
    c.add("k_pos", "v_pos", 0.05)
    c.add("k_life", "v_life", lifetime=0.05)
    c.add("k_ttl", "v_ttl", ttl=0.05)
    c.add("k_time", "v_time", time=0.05)
    c.add("k_delta", "v_delta", lifetime=timedelta(seconds=0.05))

    # All valid initially
    assert c.get("k_pos") == "v_pos"
    assert c.get("k_life") == "v_life"
    assert c.get("k_ttl") == "v_ttl"
    assert c.get("k_time") == "v_time"
    assert c.get("k_delta") == "v_delta"

    time.sleep(0.06)

    # All expired, deleted on get(), returning None
    for k in ["k_pos", "k_life", "k_ttl", "k_time", "k_delta"]:
        assert c.get(k) is None
        assert k not in c._store


def test_in_memory_cache_namespace_clearing():
    c = InMemoryCache()
    c.set("ns1:a", 1)
    c.set("ns1:b", 2)
    c.set("ns2:c", 3)

    c.clear(namespace="ns1")
    assert c.get("ns1:a") is None
    assert c.get("ns1:b") is None
    assert c.get("ns2:c") == 3

    c.clear()
    assert c.get("ns2:c") is None


def test_in_memory_cache_mutation_protection():
    c = InMemoryCache()
    orig = [{"name": "A"}]
    c.set("data", orig)

    # Mutating original should not change cached
    orig.append({"name": "B"})
    assert len(c.get("data")) == 1

    # Mutating retrieved value should not change cached
    retrieved = c.get("data")
    retrieved[0]["name"] = "MUTATED"
    assert c.get("data")[0]["name"] == "A"


def test_dynamic_namespace_bucket_syntax():
    """Verify cache[namespace] dynamic bucket syntax and composite keys."""
    mgr = CacheManager()
    problems = [{"index": "A", "name": "Prob A"}, {"index": "B", "name": "Prob B"}]

    # Initially empty
    assert mgr["contest_problems"].get(1878) is None
    assert 1878 not in mgr["contest_problems"]

    # Simple key via add with lifetime
    mgr["contest_problems"].add(1878, problems, lifetime=3600)
    assert mgr["contest_problems"].get(1878) == problems
    assert 1878 in mgr["contest_problems"]

    # Composite key (tuple)
    composite_key = (1878, True)
    assert mgr["contest_problems"].get(composite_key) is None
    mgr["contest_problems"].set(composite_key, [{"index": "A_auth"}])
    assert mgr["contest_problems"].get(composite_key) == [{"index": "A_auth"}]
    # Simple key remains intact
    assert mgr["contest_problems"].get(1878) == problems

    # Another namespace does not conflict
    mgr["user_ratings"].add("tourist", 3900)
    assert mgr["user_ratings"].get("tourist") == 3900
    assert mgr["contest_problems"].get("tourist") is None

    # Clear only contest_problems namespace
    mgr["contest_problems"].clear()
    assert mgr["contest_problems"].get(1878) is None
    assert mgr["contest_problems"].get(composite_key) is None
    # user_ratings untouched
    assert mgr["user_ratings"].get("tourist") == 3900


def test_namespace_add_with_lifetime():
    """Verify namespace.add() with lifetime expiration and lazy eviction."""
    mgr = CacheManager()
    mgr["ratings"].add("tourist", 3900, lifetime=0.05)
    mgr["ratings"].add("petr", 3000)  # default lifetime=None -> indefinite

    assert mgr["ratings"].get("tourist") == 3900
    assert mgr["ratings"].get("petr") == 3000

    time.sleep(0.06)

    # tourist expired -> returns None and evicted
    assert mgr["ratings"].get("tourist") is None
    assert "tourist" not in mgr["ratings"]

    # petr had no lifetime -> still available
    assert mgr["ratings"].get("petr") == 3000
    assert "petr" in mgr["ratings"]


def test_namespace_dict_subscript_syntax():
    mgr = CacheManager()
    ns = mgr["test_ns"]

    ns["key1"] = "val1"
    assert ns["key1"] == "val1"

    del ns["key1"]
    with pytest.raises(KeyError):
        _ = ns["key1"]


def test_cache_decorator():
    mgr = CacheManager()
    call_count = 0

    @mgr.cached(namespace="test_fn", lifetime=10)
    def compute(x, y=1):
        nonlocal call_count
        call_count += 1
        return x + y

    assert compute(2, 3) == 5
    assert call_count == 1

    # Second call with same args must be served from cache
    assert compute(2, 3) == 5
    assert call_count == 1

    # Different args must compute
    assert compute(2, 4) == 6
    assert call_count == 2
