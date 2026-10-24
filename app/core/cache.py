"""
app/core/cache.py
─────────────────
Modular, extensible, and generalized caching system for Kotchy.

Features:
- Completely decoupled from domain logic (no hardcoded domain entities).
- Dynamic namespaces via `cache[namespace]` or `cache.namespace(namespace)`:
    cache["contest_problems"].get(key)
    cache["contest_problems"].add(key, value, lifetime=...)
    cache["contest_problems"].set(key, value, ttl=...)
    cache["contest_problems"].clear()
- Support for composite keys (tuples, strings, ints).
- Abstract `BaseCache` interface allowing seamless swapping of backends (Memory -> Redis/Disk).
- Thread-safe `InMemoryCache` with lifetime/TTL expiration and mutation protection.
- Default lifetime is None (null) so data is stored indefinitely unless specified.
- Expired data is lazily removed on access (get/has) and returns None/null.
- Function decorator `@cache.cached(namespace=..., lifetime=...)`.
"""

from __future__ import annotations

import functools
import logging
import threading
import time
from abc import ABC, abstractmethod
from copy import deepcopy
from datetime import timedelta
from typing import Any, Callable, Dict, Optional, Tuple, Union

logger = logging.getLogger(__name__)


def _resolve_lifetime(
    lifetime: Optional[Union[int, float, timedelta]] = None,
    ttl: Optional[Union[int, float, timedelta]] = None,
    **kwargs: Any,
) -> Optional[float]:
    """Resolve lifetime/ttl/time into seconds as a float, or None if indefinite."""
    val = lifetime if lifetime is not None else ttl
    if val is None and "time" in kwargs:
        val = kwargs["time"]
    if val is None:
        return None
    if hasattr(val, "total_seconds"):
        return float(val.total_seconds())
    return float(val)


# ── Base Cache Interface ────────────────────────────────────────

class BaseCache(ABC):
    """Abstract cache backend interface."""

    @abstractmethod
    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value by key. Returns `default` (None) if missing or expired."""
        pass

    @abstractmethod
    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[Union[int, float, timedelta]] = None,
        lifetime: Optional[Union[int, float, timedelta]] = None,
        **kwargs: Any,
    ) -> None:
        """Store a key-value pair with optional lifetime/TTL (in seconds)."""
        pass

    @abstractmethod
    def add(
        self,
        key: str,
        value: Any,
        lifetime: Optional[Union[int, float, timedelta]] = None,
        ttl: Optional[Union[int, float, timedelta]] = None,
        **kwargs: Any,
    ) -> None:
        """Store a key-value pair with optional lifetime (in seconds). Default is None (indefinite)."""
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Remove a key from the cache. Returns True if deleted, False if not found."""
        pass

    @abstractmethod
    def has(self, key: str) -> bool:
        """Check if a key exists and has not expired."""
        pass

    @abstractmethod
    def clear(self, namespace: Optional[str] = None) -> None:
        """Clear all keys, or keys prefixed by `namespace`."""
        pass


# ── In-Memory Cache Backend ─────────────────────────────────────

class InMemoryCache(BaseCache):
    """Thread-safe in-memory cache supporting lifetime/TTL expiration and namespaces."""

    def __init__(self) -> None:
        self._store: Dict[str, Tuple[Any, Optional[float]]] = {}
        self._lock = threading.RLock()

    def _is_expired(self, expires_at: Optional[float]) -> bool:
        """Check if an expiration timestamp has passed. None means valid indefinitely."""
        if expires_at is None:
            return False
        return time.time() >= expires_at

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value by key.
        
        If the entry's lifetime has expired, it is removed from the cache and returns `default` (None).
        """
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return default

            value, expires_at = entry
            if self._is_expired(expires_at):
                del self._store[key]
                return default

            try:
                return deepcopy(value)
            except Exception:
                return value

    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[Union[int, float, timedelta]] = None,
        lifetime: Optional[Union[int, float, timedelta]] = None,
        **kwargs: Any,
    ) -> None:
        """Store a key-value pair with an optional lifetime/TTL in seconds.
        
        Default value is None, meaning the data will always be available.
        """
        effective_ttl = _resolve_lifetime(lifetime=lifetime, ttl=ttl, **kwargs)
        expires_at = (time.time() + effective_ttl) if effective_ttl is not None else None
        with self._lock:
            try:
                stored_value = deepcopy(value)
            except Exception:
                stored_value = value
            self._store[key] = (stored_value, expires_at)

    def add(
        self,
        key: str,
        value: Any,
        lifetime: Optional[Union[int, float, timedelta]] = None,
        ttl: Optional[Union[int, float, timedelta]] = None,
        **kwargs: Any,
    ) -> None:
        """Add data with a lifetime parameter.
        
        Default lifetime is None (null) so it will always be available unless a lifetime is given.
        """
        self.set(key, value, ttl=ttl, lifetime=lifetime, **kwargs)

    def delete(self, key: str) -> bool:
        """Remove a key from the cache. Returns True if deleted, False if not found."""
        with self._lock:
            if key in self._store:
                del self._store[key]
                return True
            return False

    def has(self, key: str) -> bool:
        """Check if a key exists and has not expired.
        
        If expired, removes the key from the cache and returns False.
        """
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return False
            _, expires_at = entry
            if self._is_expired(expires_at):
                del self._store[key]
                return False
            return True

    def get_ttl(self, key: str) -> Optional[float]:
        """Return remaining lifetime in seconds, or None if indefinite, not found, or expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            _, expires_at = entry
            if self._is_expired(expires_at):
                del self._store[key]
                return None
            if expires_at is None:
                return None
            return max(0.0, expires_at - time.time())

    def clear(self, namespace: Optional[str] = None) -> None:
        """Clear all keys, or keys prefixed by `namespace`."""
        with self._lock:
            if namespace is None:
                self._store.clear()
            else:
                prefix = f"{namespace}:"
                keys_to_delete = [k for k in self._store if k.startswith(prefix) or k == namespace]
                for k in keys_to_delete:
                    del self._store[k]


# ── Namespace Bucket ────────────────────────────────────────────

class NamespaceCache:
    """Scoped cache proxy for a specific namespace.

    Provides intuitive access like:
        cache["contest_problems"].get(1878)
        cache["contest_problems"].add(1878, problems, lifetime=3600)
        cache["contest_problems"].set(1878, problems, ttl=3600)
        cache["contest_problems"].clear()
    """

    def __init__(self, manager: "CacheManager", namespace: str) -> None:
        self._manager = manager
        self._namespace = namespace

    @property
    def namespace(self) -> str:
        return self._namespace

    def _format_key(self, key: Any) -> str:
        if isinstance(key, (tuple, list)):
            part = ":".join(str(k) for k in key)
        else:
            part = str(key)
        return f"{self._namespace}:{part}"

    def get(self, key: Any, default: Any = None) -> Any:
        return self._manager.get(self._format_key(key), default=default)

    def set(
        self,
        key: Any,
        value: Any,
        ttl: Optional[Union[int, float, timedelta]] = None,
        lifetime: Optional[Union[int, float, timedelta]] = None,
        **kwargs: Any,
    ) -> None:
        self._manager.set(self._format_key(key), value, ttl=ttl, lifetime=lifetime, **kwargs)

    def add(
        self,
        key: Any,
        value: Any,
        lifetime: Optional[Union[int, float, timedelta]] = None,
        ttl: Optional[Union[int, float, timedelta]] = None,
        **kwargs: Any,
    ) -> None:
        self._manager.add(self._format_key(key), value, lifetime=lifetime, ttl=ttl, **kwargs)

    def delete(self, key: Any) -> bool:
        return self._manager.delete(self._format_key(key))

    def has(self, key: Any) -> bool:
        return self._manager.has(self._format_key(key))

    def get_ttl(self, key: Any) -> Optional[float]:
        return self._manager.get_ttl(self._format_key(key))

    def clear(self) -> None:
        self._manager.clear(namespace=self._namespace)

    def __contains__(self, key: Any) -> bool:
        return self.has(key)

    def __getitem__(self, key: Any) -> Any:
        val = self.get(key)
        if val is None:
            raise KeyError(key)
        return val

    def __setitem__(self, key: Any, value: Any) -> None:
        self.set(key, value)

    def __delitem__(self, key: Any) -> None:
        if not self.delete(key):
            raise KeyError(key)


# ── Cache Manager (Central Facade) ──────────────────────────────

class CacheManager:
    """Central cache manager with generic operations, dynamic namespaces, and decorators."""

    def __init__(self, backend: Optional[BaseCache] = None) -> None:
        self._backend: BaseCache = backend or InMemoryCache()

    @property
    def backend(self) -> BaseCache:
        return self._backend

    @backend.setter
    def backend(self, new_backend: BaseCache) -> None:
        self._backend = new_backend

    # ── Dynamic Namespace Bucket Access ─────────────────────────

    def __getitem__(self, namespace: str) -> NamespaceCache:
        """Access a namespace bucket via dictionary syntax: `cache[namespace]`."""
        return self.namespace(namespace)

    def namespace(self, namespace: str) -> NamespaceCache:
        """Return a scoped NamespaceCache for the given namespace string."""
        return NamespaceCache(self, namespace)

    # ── Generic Operations ──────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        return self._backend.get(key, default=default)

    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[Union[int, float, timedelta]] = None,
        lifetime: Optional[Union[int, float, timedelta]] = None,
        **kwargs: Any,
    ) -> None:
        self._backend.set(key, value, ttl=ttl, lifetime=lifetime, **kwargs)

    def add(
        self,
        key: str,
        value: Any,
        lifetime: Optional[Union[int, float, timedelta]] = None,
        ttl: Optional[Union[int, float, timedelta]] = None,
        **kwargs: Any,
    ) -> None:
        self._backend.add(key, value, lifetime=lifetime, ttl=ttl, **kwargs)

    def delete(self, key: str) -> bool:
        return self._backend.delete(key)

    def has(self, key: str) -> bool:
        return self._backend.has(key)

    def get_ttl(self, key: str) -> Optional[float]:
        if hasattr(self._backend, "get_ttl"):
            return self._backend.get_ttl(key)
        return None

    def clear(self, namespace: Optional[str] = None) -> None:
        self._backend.clear(namespace=namespace)

    # ── Function Decorator ──────────────────────────────────────

    def cached(
        self,
        namespace: str = "default",
        ttl: Optional[Union[int, float, timedelta]] = None,
        lifetime: Optional[Union[int, float, timedelta]] = None,
        key_builder: Optional[Callable[..., str]] = None,
        **kwargs: Any,
    ) -> Callable:
        """Decorator to cache function results under a namespace.

        Example:
            @cache.cached(namespace="ratings", lifetime=300)
            def get_user_rating(handle: str):
                ...
        """
        effective_ttl = _resolve_lifetime(lifetime=lifetime, ttl=ttl, **kwargs)

        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                if key_builder:
                    sub_key = key_builder(*args, **kwargs)
                else:
                    arg_str = ":".join(map(str, args))
                    kwarg_str = ":".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
                    sub_key = f"{func.__name__}:{arg_str}:{kwarg_str}".rstrip(":")

                cache_key = f"{namespace}:{sub_key}"
                cached_val = self.get(cache_key)
                if cached_val is not None:
                    return cached_val

                result = func(*args, **kwargs)
                if result is not None:
                    self.set(cache_key, result, ttl=effective_ttl)
                return result

            return wrapper
        return decorator


# Global singleton instance
cache = CacheManager()
