"""Ruxsatlar: ish tokeni, ixtiyoriy kirish kaliti va so'rovlar chegarasi."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque


def new_job_id() -> str:
    # 128 bit tasodifiy, taxmin qilib bo'lmaydi
    return secrets.token_hex(16)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_matches(token: str | None, token_hash: str) -> bool:
    if not token:
        return False
    return hmac.compare_digest(hash_token(token), token_hash)


def access_key_ok(provided: str | None, expected: str) -> bool:
    if not expected:
        return True
    if not provided:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


class RateLimiter:
    """Oddiy xotiradagi sirpanuvchi oyna: IP bo'yicha soatiga N ta yangi ish."""

    def __init__(self, per_hour: int):
        self.per_hour = per_hour
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        if self.per_hour <= 0:
            return True
        now = time.time()
        with self._lock:
            q = self._hits[key]
            while q and q[0] < now - 3600:
                q.popleft()
            if len(q) >= self.per_hour:
                return False
            q.append(now)
            return True
