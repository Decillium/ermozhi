import time
import threading
from typing import Dict, List, Tuple, Optional
from fastapi import Request, HTTPException, status


class RateLimiter:
    """
    Thread-safe in-memory sliding window rate limiter.
    Protects ingress endpoints and storage backlog from bursts and abuse.
    """

    def __init__(self, max_requests: int = 30, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._windows: Dict[str, List[float]] = {}

    def is_allowed(self, key: str) -> Tuple[bool, int, float]:
        """
        Checks if a request under `key` is allowed within the current window.
        Returns:
            Tuple[bool, int, float]: (allowed, remaining_capacity, retry_after_seconds)
        """
        now = time.time()
        window_start = now - self.window_seconds

        with self._lock:
            if key not in self._windows:
                self._windows[key] = []

            # Filter out timestamps outside the sliding window
            self._windows[key] = [t for t in self._windows[key] if t > window_start]
            current_count = len(self._windows[key])

            if current_count < self.max_requests:
                self._windows[key].append(now)
                remaining = self.max_requests - current_count - 1
                return True, remaining, 0.0
            else:
                oldest_timestamp = self._windows[key][0]
                retry_after = max(0.1, (oldest_timestamp + self.window_seconds) - now)
                return False, 0, round(retry_after, 2)

    def clear(self) -> None:
        """Clears all rate limit windows (for testing)."""
        with self._lock:
            self._windows.clear()


# Default global rate limiter instance (30 req / 60s per key)
default_rate_limiter = RateLimiter(max_requests=30, window_seconds=60)


async def check_rate_limit(
    key: str,
    limiter: Optional[RateLimiter] = None
) -> None:
    """
    FastAPI helper to enforce rate limiting.
    Raises HTTPException 429 if the request exceeds threshold.
    """
    rl = limiter or default_rate_limiter
    allowed, remaining, retry_after = rl.is_allowed(key)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please retry later.",
            headers={"Retry-After": str(int(retry_after) + 1)}
        )
