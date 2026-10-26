"""Rate limiting module for Angel Brush image generation."""

from __future__ import annotations

import asyncio
import time
from typing import Any


class RateLimiter:
    """Thread-safe and async-safe rate limiter supporting cooldown and sliding windows."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        # key -> list of float timestamps
        self._records: dict[str, list[float]] = {}
        # key -> float timestamp of last call
        self._last_call: dict[str, float] = {}

    def _resolve_key(self, scope: str, user_id: str | None, chat_id: str | None) -> str:
        s = (scope or "user").strip().lower()
        if s == "global":
            return "global"
        elif s == "chat":
            return f"chat:{chat_id or 'unknown_chat'}"
        else:  # default user
            return f"user:{user_id or 'unknown_user'}"

    def _clean_stale(self, now: float, max_window: float = 86400.0) -> None:
        """Periodically clean records older than 24 hours to prevent memory leaks."""
        stale_threshold = now - max_window
        empty_keys = []
        for k, timestamps in self._records.items():
            self._records[k] = [t for t in timestamps if t > stale_threshold]
            if not self._records[k]:
                empty_keys.append(k)
        for k in empty_keys:
            self._records.pop(k, None)

    async def check_and_record(
        self,
        config: dict[str, Any],
        user_id: str | None = None,
        chat_id: str | None = None,
    ) -> tuple[bool, str | None]:
        """Check if request is allowed by rate limits.
        
        If allowed, records timestamp and returns (True, None).
        If rejected, returns (False, error_reason).
        """
        if not config.get("enabled", False):
            return True, None

        now = time.time()
        scope = str(config.get("scope") or "user").strip().lower()
        key = self._resolve_key(scope, user_id, chat_id)

        cooldown = max(0, int(config.get("cooldown_seconds") or 0))
        max_min = max(0, int(config.get("max_per_minute") or 0))
        max_hour = max(0, int(config.get("max_per_hour") or 0))
        max_day = max(0, int(config.get("max_per_day") or 0))
        custom_msg = str(config.get("custom_message") or "").strip()

        async with self._lock:
            self._clean_stale(now)

            # 1. Check cooldown
            last = self._last_call.get(key, 0.0)
            if cooldown > 0 and (now - last) < cooldown:
                remaining = int(cooldown - (now - last)) + 1
                reason = custom_msg or f"操作过于频繁，处于冷却中，请在 {remaining} 秒后再试。"
                return False, reason

            # 2. Check sliding windows
            timestamps = self._records.setdefault(key, [])
            
            # Count in 60s
            if max_min > 0:
                count_min = sum(1 for t in timestamps if now - t <= 60.0)
                if count_min >= max_min:
                    reason = custom_msg or f"已达到每分钟调用上限（{max_min} 次/分），请稍候再试。"
                    return False, reason

            # Count in 3600s
            if max_hour > 0:
                count_hour = sum(1 for t in timestamps if now - t <= 3600.0)
                if count_hour >= max_hour:
                    reason = custom_msg or f"已达到每小时调用上限（{max_hour} 次/时），请稍候再试。"
                    return False, reason

            # Count in 86400s
            if max_day > 0:
                count_day = sum(1 for t in timestamps if now - t <= 86400.0)
                if count_day >= max_day:
                    reason = custom_msg or f"已达到每日调用上限（{max_day} 次/天），请明日再试。"
                    return False, reason

            # Record this call
            self._last_call[key] = now
            timestamps.append(now)
            return True, None

    async def reset(self) -> None:
        """Clear all rate limit records."""
        async with self._lock:
            self._records.clear()
            self._last_call.clear()


# Global singleton instance
rate_limiter = RateLimiter()
