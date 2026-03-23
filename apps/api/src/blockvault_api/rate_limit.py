from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import Deque

from fastapi import HTTPException, Request, status


@dataclass(frozen=True)
class RateLimitPolicy:
    name: str
    limit: int
    window_seconds: int
    scope: str = "client"


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, Deque[float]] = {}
        self._lock = Lock()

    def check(self, key: str, limit: int, window_seconds: int) -> None:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._events.setdefault(key, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many requests. Please retry later.",
                )
            bucket.append(now)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


rate_limiter = InMemoryRateLimiter()


def reset_rate_limiter() -> None:
    rate_limiter.reset()


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _scope_key(request: Request, *, scope: str, wallet_address: str | None) -> str:
    if scope == "wallet" and wallet_address:
        return wallet_address.lower()
    return client_ip(request)


def enforce_rate_limit(
    request: Request,
    *,
    policy: RateLimitPolicy,
    wallet_address: str | None = None,
) -> None:
    subject = _scope_key(request, scope=policy.scope, wallet_address=wallet_address)
    bucket_key = f"{policy.name}:{subject}"
    rate_limiter.check(bucket_key, policy.limit, policy.window_seconds)
